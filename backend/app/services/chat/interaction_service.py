"""Persistence boundary for one pending user Interaction per Turn.

This module deliberately does not schedule work, mutate the Turn, or dispatch
Tool calls.  It only creates, reads, and compare-and-swap resolves the durable
Interaction row used by the runtime and presentation layers.
"""

from __future__ import annotations

from typing import cast

from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.agent_runtime.tool_redaction import redact_tool_value
from app.db.types import utc_now
from app.models.agent_execution import AgentToolCall
from app.models.agent_interaction import AgentInteraction
from app.models.conversation_turn import ConversationTurn
from app.schemas.agent_interaction import (
    InteractionKind,
    InteractionResolutionStatus,
)

_KINDS = (
    "clarification",
    "connection",
    "approval",
    "client_readiness",
)
_RESOLUTION_STATUSES = ("resolved", "rejected", "cancelled")


class InteractionNotFoundError(LookupError):
    """The requested Interaction or owning Turn does not exist."""


class InteractionOwnershipError(PermissionError):
    """The caller does not own the Interaction's authoritative Turn."""


class InteractionConflictError(RuntimeError):
    """The requested create/resolve lost a concurrency or version race."""


def _redacted_payload(payload: BaseModel) -> dict:
    """Create the durable copy; never attach the caller's object to the row."""

    dumped = payload.model_dump(mode="json")
    if not isinstance(dumped, dict):
        raise TypeError("Interaction payload must serialize to a JSON object")
    return cast(dict, redact_tool_value(dumped))


def _owned_turn(db: Session, *, turn_id: str, user_id: int) -> ConversationTurn:
    turn = db.get(ConversationTurn, turn_id)
    if turn is None:
        raise InteractionNotFoundError(f"Conversation turn {turn_id} does not exist")
    if turn.user_id != user_id:
        raise InteractionOwnershipError(
            f"User {user_id} does not own conversation turn {turn_id}"
        )
    return turn


def create_pending_interaction(
    db: Session,
    *,
    turn_id: str,
    user_id: int,
    kind: InteractionKind,
    request: BaseModel,
    tool_call_id: str | None = None,
) -> AgentInteraction:
    """Create the Turn's only pending Interaction without committing.

    ``request`` must already be a concrete Pydantic payload.  A server-side
    redacted copy is produced before the ORM row is constructed, so secrets
    cannot enter ``request_json`` even if a caller missed its own redaction.
    """

    if kind not in _KINDS:
        raise ValueError(f"Unsupported Interaction kind: {kind}")
    _owned_turn(db, turn_id=turn_id, user_id=user_id)

    if tool_call_id is not None:
        linked_call = (
            db.query(AgentToolCall.id)
            .filter(
                AgentToolCall.turn_id == turn_id,
                AgentToolCall.user_id == user_id,
                AgentToolCall.call_id == tool_call_id,
            )
            .scalar()
        )
        if linked_call is None:
            raise ValueError(
                "tool_call_id must identify a Tool Call owned by the same Turn"
            )

    existing = (
        db.query(AgentInteraction.id)
        .filter(
            AgentInteraction.turn_id == turn_id,
            AgentInteraction.status == "pending",
        )
        .scalar()
    )
    if existing is not None:
        raise InteractionConflictError(
            f"Conversation turn {turn_id} already has a pending Interaction"
        )

    row = AgentInteraction(
        turn_id=turn_id,
        tool_call_id=tool_call_id,
        kind=kind,
        status="pending",
        request_json=_redacted_payload(request),
        version=1,
    )
    try:
        # The partial unique index is the final guard against concurrent
        # creators. Callers own the surrounding transaction and decide how a
        # losing create is retried or rolled back.
        db.add(row)
        db.flush()
    except IntegrityError as exc:
        raise InteractionConflictError(
            f"Conversation turn {turn_id} already has a pending Interaction"
        ) from exc
    return row


def get_pending_interaction(
    db: Session,
    *,
    turn_id: str,
    user_id: int,
) -> AgentInteraction | None:
    """Return the owned Turn's pending Interaction, if any."""

    _owned_turn(db, turn_id=turn_id, user_id=user_id)
    return (
        db.query(AgentInteraction)
        .filter(
            AgentInteraction.turn_id == turn_id,
            AgentInteraction.status == "pending",
        )
        .one_or_none()
    )


def resolve_interaction(
    db: Session,
    *,
    interaction_id: str,
    user_id: int,
    expected_version: int,
    status: InteractionResolutionStatus,
    resolution: BaseModel,
) -> AgentInteraction:
    """CAS-resolve an owned pending Interaction without committing.

    A successful update is exactly ``pending/version=N`` to the requested
    terminal status/version ``N+1``.  Replays with a stale version are
    conflicts; this service does not resume or otherwise modify the Turn.
    """

    if expected_version < 1:
        raise ValueError("expected_version must be positive")
    if status not in _RESOLUTION_STATUSES:
        raise ValueError(f"Unsupported Interaction resolution status: {status}")

    owner_row = (
        db.query(AgentInteraction.turn_id, ConversationTurn.user_id)
        .join(ConversationTurn, ConversationTurn.id == AgentInteraction.turn_id)
        .filter(AgentInteraction.id == interaction_id)
        .one_or_none()
    )
    if owner_row is None:
        raise InteractionNotFoundError(
            f"Agent Interaction {interaction_id} does not exist"
        )
    if owner_row.user_id != user_id:
        raise InteractionOwnershipError(
            f"User {user_id} does not own Agent Interaction {interaction_id}"
        )

    redacted_resolution = _redacted_payload(resolution)
    resolved_at = utc_now()
    changed = (
        db.query(AgentInteraction)
        .filter(
            AgentInteraction.id == interaction_id,
            AgentInteraction.turn_id == owner_row.turn_id,
            AgentInteraction.status == "pending",
            AgentInteraction.version == expected_version,
        )
        .update(
            {
                AgentInteraction.status: status,
                AgentInteraction.resolution_json: redacted_resolution,
                AgentInteraction.version: AgentInteraction.version + 1,
                AgentInteraction.resolved_at: resolved_at,
            },
            synchronize_session=False,
        )
    )
    if changed != 1:
        current = (
            db.query(AgentInteraction.status, AgentInteraction.version)
            .filter(AgentInteraction.id == interaction_id)
            .one_or_none()
        )
        current_state = (
            f"status={current.status}, version={current.version}"
            if current is not None
            else "missing"
        )
        raise InteractionConflictError(
            f"Agent Interaction {interaction_id} cannot resolve from "
            f"pending/version={expected_version}; current {current_state}"
        )

    db.flush()
    row = (
        db.query(AgentInteraction)
        .populate_existing()
        .filter(AgentInteraction.id == interaction_id)
        .one_or_none()
    )
    if row is None:  # pragma: no cover - protected by the successful UPDATE
        raise InteractionNotFoundError(
            f"Agent Interaction {interaction_id} disappeared after resolution"
        )
    return row


__all__ = [
    "InteractionConflictError",
    "InteractionNotFoundError",
    "InteractionOwnershipError",
    "create_pending_interaction",
    "get_pending_interaction",
    "resolve_interaction",
]
