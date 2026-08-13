"""Durable delivery protocol for the product-owned Mock Client Action handler.

The existing ``AgentInteraction`` row is the persistence and recovery source.
This module adds initiating-client affinity, explicit takeover and typed,
idempotent client results without creating another runtime or action ledger.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import cast

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.db.types import utc_now
from app.models.agent_interaction import AgentInteraction
from app.models.conversation_turn import ConversationTurn
from app.models.pending_submission import PendingSubmission
from app.schemas.agent_interaction import InteractionPayload
from app.schemas.client_action import (
    MockClientActionName,
    MockClientActionPayload,
    MockClientActionRequest,
    MockClientActionResultRequest,
    MockClientActionView,
)
from app.services.chat.interaction_service import (
    InteractionConflictError,
    create_pending_interaction,
    resolve_interaction,
)


class ClientActionNotFoundError(LookupError):
    """The action, Turn, or owning Conversation is unavailable to this user."""


class ClientActionConflictError(RuntimeError):
    """An action identity, version or bound-client condition did not match."""


class ClientActionUnavailableError(RuntimeError):
    """The initiating Turn has no interactive product client."""


@dataclass(frozen=True)
class ClientActionResolution:
    interaction: AgentInteraction
    replayed: bool


def _parse_request(row: AgentInteraction) -> MockClientActionRequest:
    if row.kind != "client_readiness":
        raise ClientActionNotFoundError("Interaction is not a Client Action")
    try:
        return MockClientActionRequest.model_validate(row.request_json)
    except ValidationError as exc:
        raise ClientActionNotFoundError(
            "Interaction does not contain a supported Client Action"
        ) from exc


def _owned_turn(
    db: Session,
    *,
    session_id: str,
    turn_id: str,
    user_id: int,
) -> ConversationTurn:
    turn = db.get(ConversationTurn, turn_id)
    if turn is None or turn.conversation_id != session_id or turn.user_id != user_id:
        raise ClientActionNotFoundError("Turn not found or access denied")
    return turn


def initiating_client_id(db: Session, turn: ConversationTurn) -> str | None:
    """Read affinity from the admitted ingress record that created the Turn."""

    if not turn.submission_id:
        return None
    submission = db.get(PendingSubmission, turn.submission_id)
    if (
        submission is None
        or submission.conversation_id != turn.conversation_id
        or submission.user_id != turn.user_id
    ):
        return None
    client_id = (submission.source_client_id or "").strip()
    return client_id or None


def action_identity(*, turn_id: str, tool_call_id: str, action: str) -> str:
    digest = hashlib.sha256(
        f"{turn_id}\x00{tool_call_id}\x00{action}".encode("utf-8")
    ).hexdigest()[:32]
    return f"ca_{digest}"


def _rows_for_call(
    db: Session,
    *,
    turn_id: str,
    tool_call_id: str,
) -> list[AgentInteraction]:
    return (
        db.query(AgentInteraction)
        .filter(
            AgentInteraction.turn_id == turn_id,
            AgentInteraction.tool_call_id == tool_call_id,
            AgentInteraction.kind == "client_readiness",
        )
        .order_by(AgentInteraction.created_at, AgentInteraction.id)
        .all()
    )


def find_mock_client_action(
    db: Session,
    *,
    turn_id: str,
    tool_call_id: str,
    action: MockClientActionName,
) -> tuple[AgentInteraction, MockClientActionRequest] | None:
    expected_id = action_identity(
        turn_id=turn_id,
        tool_call_id=tool_call_id,
        action=action,
    )
    for row in _rows_for_call(db, turn_id=turn_id, tool_call_id=tool_call_id):
        try:
            request = _parse_request(row)
        except ClientActionNotFoundError:
            continue
        if request.action_id == expected_id and request.action == action:
            return row, request
    return None


def create_mock_client_action(
    db: Session,
    *,
    turn: ConversationTurn,
    tool_call_id: str,
    action: MockClientActionName,
    payload: MockClientActionPayload,
    original_client_id: str,
    bound_client_id: str,
) -> tuple[AgentInteraction, MockClientActionRequest]:
    """Persist one typed action before delivery, idempotently per phase."""

    existing = find_mock_client_action(
        db,
        turn_id=turn.id,
        tool_call_id=tool_call_id,
        action=action,
    )
    if existing is not None:
        return existing

    request = MockClientActionRequest(
        action_id=action_identity(
            turn_id=turn.id,
            tool_call_id=tool_call_id,
            action=action,
        ),
        action=action,
        original_client_id=original_client_id,
        bound_client_id=bound_client_id,
        payload=payload,
    )
    try:
        row = create_pending_interaction(
            db,
            turn_id=turn.id,
            user_id=turn.user_id,
            kind="client_readiness",
            request=request,
            tool_call_id=tool_call_id,
        )
    except InteractionConflictError as exc:
        # A different pending Interaction is meaningful and cannot be silently
        # replaced by a UI effect.
        raise ClientActionConflictError(str(exc)) from exc
    return row, request


def latest_handoff_client(
    db: Session,
    *,
    turn: ConversationTurn,
    tool_call_id: str,
) -> tuple[str, str]:
    """Return (original initiating client, currently participating client)."""

    original = initiating_client_id(db, turn)
    if original is None:
        raise ClientActionUnavailableError(
            "This Turn was not initiated by an interactive product client"
        )
    current = original
    for row in _rows_for_call(db, turn_id=turn.id, tool_call_id=tool_call_id):
        try:
            request = _parse_request(row)
        except ClientActionNotFoundError:
            continue
        original = request.original_client_id
        current = request.bound_client_id
        resolution = row.resolution_json or {}
        if row.status == "resolved" and isinstance(resolution, dict):
            resolved_client = str(resolution.get("client_id") or "").strip()
            if resolved_client:
                current = resolved_client
    return original, current


def pending_action_for_client(
    db: Session,
    *,
    session_id: str,
    turn_id: str,
    user_id: int,
    client_id: str,
) -> MockClientActionView | None:
    """Return the pending payload only to its currently bound client."""

    _owned_turn(db, session_id=session_id, turn_id=turn_id, user_id=user_id)
    row = (
        db.query(AgentInteraction)
        .filter(
            AgentInteraction.turn_id == turn_id,
            AgentInteraction.kind == "client_readiness",
            AgentInteraction.status == "pending",
        )
        .one_or_none()
    )
    if row is None:
        return None
    request = _parse_request(row)
    if request.bound_client_id != client_id:
        return None
    if not row.tool_call_id:
        raise ClientActionNotFoundError("Client Action has no Tool Call identity")
    return MockClientActionView(
        interaction_id=row.id,
        turn_id=row.turn_id,
        tool_call_id=row.tool_call_id,
        version=row.version,
        action_id=request.action_id,
        action=request.action,
        payload=request.payload,
        takeover_generation=request.takeover_generation,
        created_at=row.created_at,
    )


def takeover_pending_action(
    db: Session,
    *,
    session_id: str,
    turn_id: str,
    interaction_id: str,
    user_id: int,
    action_id: str,
    expected_version: int,
    client_id: str,
) -> tuple[AgentInteraction, bool]:
    """Explicitly rebind one still-pending action to another client instance."""

    _owned_turn(db, session_id=session_id, turn_id=turn_id, user_id=user_id)
    row = db.get(AgentInteraction, interaction_id)
    if row is None or row.turn_id != turn_id:
        raise ClientActionNotFoundError("Client Action not found")
    request = _parse_request(row)
    if request.action_id != action_id:
        raise ClientActionConflictError("Client Action identity does not match")
    if row.status != "pending":
        raise ClientActionConflictError("Client Action is no longer pending")

    # A transport retry after the successful CAS is safe and does not create a
    # second takeover event or version bump.
    if row.version == expected_version + 1 and request.bound_client_id == client_id:
        return row, True
    if row.version != expected_version:
        raise ClientActionConflictError(
            f"Client Action version changed (current={row.version})"
        )
    if request.bound_client_id == client_id:
        return row, True

    history = list(request.takeover_history)
    history.append(
        {
            "from_client_id": request.bound_client_id,
            "to_client_id": client_id,
            "at": utc_now().isoformat(),
        }
    )
    updated_request = request.model_copy(
        update={
            "bound_client_id": client_id,
            "takeover_generation": request.takeover_generation + 1,
            "takeover_history": history,
        }
    )
    changed = (
        db.query(AgentInteraction)
        .filter(
            AgentInteraction.id == row.id,
            AgentInteraction.turn_id == turn_id,
            AgentInteraction.status == "pending",
            AgentInteraction.version == expected_version,
        )
        .update(
            {
                AgentInteraction.request_json: updated_request.model_dump(mode="json"),
                AgentInteraction.version: AgentInteraction.version + 1,
            },
            synchronize_session=False,
        )
    )
    if changed != 1:
        raise ClientActionConflictError("Client Action takeover lost a version race")
    db.flush()
    refreshed = (
        db.query(AgentInteraction)
        .populate_existing()
        .filter(AgentInteraction.id == row.id)
        .one()
    )
    return refreshed, False


def _resolution_payload(
    request: MockClientActionRequest,
    result: MockClientActionResultRequest,
) -> dict:
    if request.action == "mock_interview.check_readiness":
        if result.outcome == "acknowledged" and result.readiness != "ready":
            raise ClientActionConflictError(
                "Readiness acknowledgement must explicitly report ready"
            )
    elif result.readiness is not None:
        raise ClientActionConflictError(
            "Only the Mock readiness action accepts a readiness result"
        )
    return {
        "protocol": request.protocol,
        "action_id": request.action_id,
        "action": request.action,
        "client_id": result.client_id,
        "outcome": result.outcome,
        "readiness": result.readiness,
        "reason": result.reason.strip() if result.reason else None,
    }


def resolve_pending_action(
    db: Session,
    *,
    session_id: str,
    turn_id: str,
    interaction_id: str,
    user_id: int,
    result: MockClientActionResultRequest,
) -> ClientActionResolution:
    """Persist a bound client's typed result; exact retries are idempotent."""

    _owned_turn(db, session_id=session_id, turn_id=turn_id, user_id=user_id)
    row = db.get(AgentInteraction, interaction_id)
    if row is None or row.turn_id != turn_id:
        raise ClientActionNotFoundError("Client Action not found")
    request = _parse_request(row)
    if request.action_id != result.action_id:
        raise ClientActionConflictError("Client Action identity does not match")
    resolution = _resolution_payload(request, result)

    if row.status == "resolved":
        if row.resolution_json == resolution:
            return ClientActionResolution(interaction=row, replayed=True)
        raise ClientActionConflictError("Client Action already has another result")
    if row.status != "pending":
        raise ClientActionConflictError("Client Action is no longer pending")
    if row.version != result.expected_version:
        raise ClientActionConflictError(
            f"Client Action version changed (current={row.version})"
        )
    if request.bound_client_id != result.client_id:
        raise ClientActionConflictError(
            "Only the currently bound client can resolve this action"
        )

    try:
        resolved = resolve_interaction(
            db,
            interaction_id=row.id,
            user_id=user_id,
            expected_version=result.expected_version,
            # Client refusal/failure is typed data for the original Tool Call,
            # not the generic Interaction lifecycle's rejection branch.
            status="resolved",
            resolution=InteractionPayload(root=cast(dict, resolution)),
        )
    except InteractionConflictError as exc:
        raise ClientActionConflictError(str(exc)) from exc
    return ClientActionResolution(interaction=resolved, replayed=False)


def action_resolution(row: AgentInteraction) -> dict | None:
    if row.status != "resolved" or not isinstance(row.resolution_json, dict):
        return None
    return dict(row.resolution_json)


def sanitized_interaction_request(row: AgentInteraction) -> dict:
    """Projection safe for other tabs observing the Turn's waiting state."""

    try:
        request = _parse_request(row)
    except ClientActionNotFoundError:
        return dict(row.request_json or {})
    return {
        "protocol": request.protocol,
        "action_id": request.action_id,
        "action": request.action,
        "delivery": "bound_client_only",
    }


__all__ = [
    "ClientActionConflictError",
    "ClientActionNotFoundError",
    "ClientActionResolution",
    "ClientActionUnavailableError",
    "action_identity",
    "action_resolution",
    "create_mock_client_action",
    "find_mock_client_action",
    "initiating_client_id",
    "latest_handoff_client",
    "pending_action_for_client",
    "resolve_pending_action",
    "sanitized_interaction_request",
    "takeover_pending_action",
]
