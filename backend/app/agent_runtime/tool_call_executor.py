from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Collection
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from app.core.config import settings
from app.db.database import SessionLocal
from app.db.types import utc_now
from app.models.agent_execution import AgentToolCall
from app.models.conversation_turn import ConversationTurn
from app.models.user import User
from app.schemas.agent_interaction import ToolInteractionRequest
from app.services.chat.interaction_service import (
    InteractionConflictError,
    create_pending_interaction,
    get_pending_interaction,
)
from app.services.chat.conversation_deletion_service import (
    settle_deleted_conversation_receipt,
)
from app.services.chat.conversation_deletion_resource_service import (
    has_unresolved_conversation_deletion_resource_conflict,
)

from .tool_policy import (
    ToolEffect,
    ToolPolicyContext,
    ToolPolicyDecision,
    evaluate_tool_policy,
)
from .tool_redaction import redact_tool_text, redact_tool_value

Dispatch = Callable[[], Awaitable[dict[str, Any]]]
_TIMELINE_EVENT_LIMIT = 64
_RECEIPT_REF_LIMIT = 32
_RESOURCE_IDENTITY_LIMIT = 32
_RESOURCE_IDENTITY_CHARS = 255
_UNRESOLVED_RESOURCE_STATUSES = ("running", "unknown")
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ToolExecutionPlan:
    """Side-effect-free Policy and durable-identity preflight for one call."""

    call_id: str
    tool_name: str
    arguments_fingerprint: str
    decision: ToolPolicyDecision
    model_step: int | None = None
    model_call_index: int | None = None
    model_call_order: int | None = None
    handler_identity: str | None = None
    provider_identity: str | None = None
    connection_identity: str | None = None
    resource_identities: tuple[str, ...] = ()
    receipt_ref_resolver: Callable[[dict[str, Any]], Collection[str]] | None = None
    existing_result: dict[str, Any] | None = None
    preflight_error: dict[str, Any] | None = None

    @property
    def requires_interaction(self) -> bool:
        return (
            self.existing_result is None
            and self.preflight_error is None
            and self.decision.outcome == "ask"
        )


def _arguments_fingerprint(arguments: dict[str, Any]) -> str:
    return json.dumps(
        arguments,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


async def plan_tool_call(
    *,
    call_id: str,
    turn_id: str | None,
    tool_name: str,
    arguments: dict[str, Any],
    effect: ToolEffect,
    policy_context: ToolPolicyContext | None = None,
    dispatch_generation: int = 1,
    resume_waiting: bool = False,
    preflight_error: dict[str, Any] | None = None,
    model_step: int | None = None,
    model_call_index: int | None = None,
    model_call_order: int | None = None,
    handler_identity: str | None = None,
    provider_identity: str | None = None,
    connection_identity: str | None = None,
    resource_identities: Collection[str] = (),
    receipt_ref_resolver: Callable[[dict[str, Any]], Collection[str]] | None = None,
) -> ToolExecutionPlan:
    """Preflight Policy and exact call identity before any handler starts.

    The check is deliberately read-only. ``execute_tool_call`` repeats the
    durable fence while starting the call, so this seam enables whole-batch
    planning without weakening the existing exact-once boundary.
    """

    decision = evaluate_tool_policy(effect, policy_context or ToolPolicyContext())
    bounded_resources = _bounded_resource_identities(resource_identities)
    existing_result = None
    if turn_id:
        audited_arguments = redact_tool_value(arguments)
        existing_result = await asyncio.to_thread(
            _inspect_identity,
            call_id,
            turn_id,
            tool_name,
            audited_arguments,
            effect.value,
            handler_identity,
            provider_identity,
            connection_identity,
            bounded_resources,
            dispatch_generation,
            resume_waiting,
        )
    return ToolExecutionPlan(
        call_id=call_id,
        tool_name=tool_name,
        arguments_fingerprint=_arguments_fingerprint(arguments),
        decision=decision,
        model_step=model_step,
        model_call_index=model_call_index,
        model_call_order=model_call_order,
        handler_identity=handler_identity,
        provider_identity=provider_identity,
        connection_identity=connection_identity,
        resource_identities=bounded_resources,
        receipt_ref_resolver=receipt_ref_resolver,
        existing_result=_safe_result(existing_result) if existing_result else None,
        preflight_error=(
            _safe_result(preflight_error) if preflight_error is not None else None
        ),
    )


def _durable_result(result: dict[str, Any] | None) -> dict[str, Any] | None:
    """Canonical complete ToolResult owned by the durable Interaction record."""

    if result is None:
        return None
    return _safe_result(result)


def _is_legacy_truncated_audit_result(result: dict[str, Any]) -> bool:
    """Recognize lossy rows written before full ToolResult persistence."""

    return bool(
        set(result) == {"truncated", "original_chars", "preview"}
        and result.get("truncated") is True
        and isinstance(result.get("original_chars"), int)
        and isinstance(result.get("preview"), str)
    )


def _safe_result(result: dict[str, Any] | None) -> dict[str, Any]:
    """Return the only Tool result representation allowed past execution.

    Handlers receive their original typed inputs, but their output is external
    data.  Redact it once at this boundary before it can reach the model,
    Conversation history, persisted overflow storage, SSE, or audit views.
    """

    safe = redact_tool_value(dict(result or {}))
    return dict(safe) if isinstance(safe, dict) else {"result": safe}


def _timeline_event(
    event: str,
    dispatch_generation: int,
    *,
    status: str | None = None,
    completion_sequence: int | None = None,
    blocked_by_call_id: str | None = None,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "event": event,
        "at": utc_now().isoformat(),
        "dispatch_generation": int(dispatch_generation),
    }
    if status:
        item["status"] = status[:32]
    if completion_sequence is not None:
        item["completion_sequence"] = int(completion_sequence)
    if blocked_by_call_id:
        item["blocked_by_call_id"] = blocked_by_call_id[:128]
    return item


def _append_timeline(row: AgentToolCall, event: dict[str, Any]) -> None:
    timeline = [
        dict(item) for item in (row.timeline_json or []) if isinstance(item, dict)
    ]
    timeline.append(dict(redact_tool_value(event)))
    row.timeline_json = timeline[-_TIMELINE_EVENT_LIMIT:]


def _handler_was_started(row: AgentToolCall) -> bool:
    return any(
        isinstance(item, dict) and item.get("event") == "handler_started"
        for item in (row.timeline_json or [])
    )


def _bounded_resource_identities(
    identities: Collection[str] | None,
) -> tuple[str, ...]:
    """Canonicalize declared resources without creating a second registry."""

    bounded: list[str] = []
    for candidate in identities or ():
        value = str(candidate).strip()
        resource_type, separator, resource_value = value.partition(":")
        if (
            not separator
            or not resource_type.strip()
            or not resource_value.strip()
            or len(value) > _RESOURCE_IDENTITY_CHARS
        ):
            continue
        redacted = redact_tool_text(value)
        if redacted != value or "[REDACTED]" in redacted:
            continue
        if value not in bounded:
            bounded.append(value)
        if len(bounded) >= _RESOURCE_IDENTITY_LIMIT:
            break
    return tuple(bounded)


def _resource_overlap(
    left: Collection[str] | None,
    right: Collection[str] | None,
) -> tuple[str, ...]:
    right_set = set(_bounded_resource_identities(right))
    return tuple(
        identity
        for identity in _bounded_resource_identities(left)
        if identity in right_set
    )


def _declared_receipt_refs(
    resolver: Callable[[dict[str, Any]], Collection[str]] | None,
    result: dict[str, Any],
) -> list[str]:
    """Extract only receipt identities declared by the ToolDefinition."""

    if resolver is None:
        return []
    try:
        candidates = resolver(result)
    except Exception as exc:  # noqa: BLE001 - audit metadata cannot fail the call
        logger.warning("receipt reference extraction failed (%s)", type(exc).__name__)
        return []
    refs: list[str] = []
    for candidate in candidates:
        value = str(candidate).strip()
        if not value or len(value) > 255:
            continue
        redacted = redact_tool_text(value)
        if redacted != value or "[REDACTED]" in redacted:
            continue
        if value not in refs:
            refs.append(value)
        if len(refs) >= _RECEIPT_REF_LIMIT:
            break
    return refs


async def execute_tool_call(
    *,
    call_id: str,
    turn_id: str | None,
    session_id: str,
    user_id: int,
    tool_name: str,
    arguments: dict[str, Any],
    timeout_seconds: float,
    dispatch: Dispatch,
    effect: ToolEffect = ToolEffect.UNKNOWN,
    policy_context: ToolPolicyContext | None = None,
    dispatch_generation: int = 1,
    resume_waiting: bool = False,
    plan: ToolExecutionPlan | None = None,
    preflight_error: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute one call with timeout/cancellation and durable lifecycle audit."""
    started = time.perf_counter()
    encoded_arguments = json.dumps(arguments, ensure_ascii=False, default=str)
    redacted_arguments = redact_tool_value(arguments)
    encoded_redacted_arguments = json.dumps(
        redacted_arguments,
        ensure_ascii=False,
        default=str,
    )
    arguments_too_large = len(encoded_arguments) > settings.AGENT_MAX_TOOL_ARG_CHARS
    audited_arguments = (
        redacted_arguments
        if not arguments_too_large
        else {
            "truncated": True,
            "original_chars": len(encoded_arguments),
            "preview": encoded_redacted_arguments[: settings.AGENT_MAX_TOOL_ARG_CHARS],
        }
    )
    if plan is None:
        plan = await plan_tool_call(
            call_id=call_id,
            turn_id=turn_id,
            tool_name=tool_name,
            arguments=arguments,
            effect=effect,
            policy_context=policy_context,
            dispatch_generation=dispatch_generation,
            resume_waiting=resume_waiting,
            preflight_error=preflight_error,
        )
    if (
        plan.call_id != call_id
        or plan.tool_name != tool_name
        or plan.arguments_fingerprint != _arguments_fingerprint(arguments)
    ):
        return {"error": "tool_execution_plan_mismatch", "tool_name": tool_name}
    if plan.existing_result is not None:
        if turn_id:
            await asyncio.to_thread(
                _record_replay,
                call_id,
                turn_id,
                dispatch_generation,
            )
        return _safe_result(plan.existing_result)
    decision = plan.decision

    async def audit_cancellation() -> None:
        if not turn_id:
            return
        await asyncio.to_thread(
            _finish,
            call_id,
            turn_id,
            session_id,
            user_id,
            tool_name,
            "cancelled",
            None,
            "tool_cancelled",
            (time.perf_counter() - started) * 1000,
            dispatch_generation,
        )

    if turn_id:
        start_task = asyncio.create_task(
            asyncio.to_thread(
                _start,
                call_id,
                turn_id,
                session_id,
                user_id,
                tool_name,
                audited_arguments,
                timeout_seconds,
                effect.value,
                decision.outcome,
                decision.reason,
                dispatch_generation,
                resume_waiting,
                plan.model_step,
                plan.model_call_index,
                plan.model_call_order,
                plan.handler_identity,
                plan.provider_identity,
                plan.connection_identity,
                plan.resource_identities,
            )
        )
        try:
            existing = await asyncio.shield(start_task)
        except asyncio.CancelledError:
            await start_task
            await audit_cancellation()
            raise
        if existing is not None:
            return existing
    if plan.preflight_error is not None:
        result = _safe_result(plan.preflight_error)
        if turn_id:
            finished = await asyncio.to_thread(
                _finish,
                call_id,
                turn_id,
                session_id,
                user_id,
                tool_name,
                "failed",
                result,
                str(result.get("error") or "tool_preflight_failed"),
                (time.perf_counter() - started) * 1000,
                dispatch_generation,
            )
            if finished is not None:
                result = finished
        return _safe_result(result)
    if decision.outcome != "allow":
        is_connector_unavailable = (
            decision.outcome == "deny" and decision.reason == "connector_unavailable"
        )
        result = {
            "error": (
                "interaction_required"
                if decision.outcome == "ask"
                else (
                    "connector_unavailable"
                    if is_connector_unavailable
                    else "permission_denied"
                )
            ),
            "tool_name": tool_name,
            "reason": decision.reason,
        }
        if decision.outcome == "ask":
            result["interaction_type"] = (
                "connection" if decision.reason == "connection_required" else "approval"
            )
        elif is_connector_unavailable and plan.provider_identity:
            result["provider"] = plan.provider_identity
        if turn_id:
            finished = await asyncio.to_thread(
                _finish,
                call_id,
                turn_id,
                session_id,
                user_id,
                tool_name,
                "waiting" if decision.outcome == "ask" else "denied",
                result,
                str(result["error"]),
                (time.perf_counter() - started) * 1000,
                dispatch_generation,
            )
            if finished is not None:
                result = finished
        return result
    if arguments_too_large:
        result = {"error": "tool_args_too_large", "tool_name": tool_name}
        if turn_id:
            finished = await asyncio.to_thread(
                _finish,
                call_id,
                turn_id,
                session_id,
                user_id,
                tool_name,
                "failed",
                result,
                "tool_args_too_large",
                (time.perf_counter() - started) * 1000,
                dispatch_generation,
            )
            if finished is not None:
                result = finished
        return result
    try:
        if turn_id:
            handler_admitted = await asyncio.to_thread(
                _mark_handler_started,
                call_id,
                turn_id,
                dispatch_generation,
            )
            if not handler_admitted:
                return {
                    "error": "stale_dispatch_generation",
                    "tool_name": tool_name,
                }
        async with asyncio.timeout(timeout_seconds):
            result = _safe_result(await dispatch())
        status = _status_for_result(result)
        error = str(result.get("error")) if "error" in result else None
    except TimeoutError:
        result = {"error": "tool_timeout", "tool_name": tool_name}
        status, error = "timeout", "tool_timeout"
    except asyncio.CancelledError:
        await audit_cancellation()
        raise
    except ValueError as exc:
        safe_error = redact_tool_text(str(exc))
        result = {"error": safe_error}
        status, error = "failed", safe_error
    except Exception as exc:  # noqa: BLE001
        # Traceback exception text can contain request headers or signed URLs.
        # Keep the exception type for operations without copying its value.
        logger.error("tool call failed: %s (%s)", tool_name, type(exc).__name__)
        result = {"error": "tool_execution_failed", "tool_name": tool_name}
        status, error = "failed", type(exc).__name__

    if turn_id:
        receipt_refs = _declared_receipt_refs(
            plan.receipt_ref_resolver,
            result,
        )
        finished = await asyncio.to_thread(
            _finish,
            call_id,
            turn_id,
            session_id,
            user_id,
            tool_name,
            status,
            result,
            error,
            (time.perf_counter() - started) * 1000,
            dispatch_generation,
            receipt_refs,
        )
        if finished is not None:
            result = finished
    return _safe_result(result)


def _inspect_identity(
    call_id: str,
    turn_id: str,
    tool_name: str,
    arguments: dict[str, Any],
    effect: str,
    handler_identity: str | None,
    provider_identity: str | None,
    connection_identity: str | None,
    resource_identities: Collection[str],
    dispatch_generation: int,
    resume_waiting: bool,
) -> dict[str, Any] | None:
    """Read the durable call fence without creating or mutating a row."""

    db = SessionLocal()
    try:
        turn = db.get(ConversationTurn, turn_id)
        if (
            turn is None
            or int(turn.dispatch_generation or 1) != dispatch_generation
            or turn.status in {"completed", "blocked", "failed", "cancelled"}
        ):
            return {
                "error": "stale_dispatch_generation",
                "tool_name": tool_name,
            }
        existing = (
            db.query(AgentToolCall)
            .filter(
                AgentToolCall.turn_id == turn_id,
                AgentToolCall.call_id == call_id,
            )
            .one_or_none()
        )
        if existing is None:
            return None
        if (
            existing.tool_name != tool_name
            or existing.arguments_json != arguments
            or _execution_identity_conflicts(
                existing,
                effect=effect,
                handler_identity=handler_identity,
                provider_identity=provider_identity,
                connection_identity=connection_identity,
                resource_identities=resource_identities,
            )
        ):
            return {"error": "tool_call_identity_conflict", "tool_name": tool_name}
        if existing.status == "running":
            return {"error": "tool_call_in_progress", "tool_name": tool_name}
        if existing.status in {"waiting", "deferred"} and resume_waiting:
            return None
        if isinstance(existing.result_json, dict):
            if _is_legacy_truncated_audit_result(existing.result_json):
                return {
                    "error": "tool_outcome_unknown",
                    "tool_name": tool_name,
                    "call_id": call_id,
                }
            return dict(existing.result_json)
        return {
            "error": "tool_outcome_unknown",
            "tool_name": tool_name,
            "call_id": call_id,
        }
    finally:
        db.close()


async def defer_tool_calls(
    *,
    turn_id: str | None,
    session_id: str,
    user_id: int,
    dispatch_generation: int,
    blocked_by_call_id: str,
    calls: list[dict[str, Any]],
) -> bool:
    """Durably reserve an untouched batch tail in original model order."""

    if not turn_id:
        return False

    def save() -> bool:
        db = SessionLocal()
        try:
            turn = (
                db.query(ConversationTurn)
                .filter(ConversationTurn.id == turn_id)
                .with_for_update()
                .one_or_none()
            )
            if (
                turn is None
                or int(turn.dispatch_generation or 1) != dispatch_generation
                or turn.status in {"completed", "blocked", "failed", "cancelled"}
            ):
                return False
            for call in calls:
                call_id = str(call["call_id"])
                tool_name = str(call["tool_name"])
                arguments = dict(redact_tool_value(call.get("arguments") or {}))
                existing = (
                    db.query(AgentToolCall)
                    .filter(
                        AgentToolCall.turn_id == turn_id,
                        AgentToolCall.call_id == call_id,
                    )
                    .one_or_none()
                )
                if existing is not None:
                    if (
                        existing.tool_name != tool_name
                        or existing.arguments_json != arguments
                        or _execution_identity_conflicts(
                            existing,
                            effect=str(call.get("effect") or ToolEffect.UNKNOWN.value),
                            handler_identity=call.get("handler_identity"),
                            provider_identity=call.get("provider_identity"),
                            connection_identity=call.get("connection_identity"),
                        )
                    ):
                        return False
                    continue
                db.add(
                    AgentToolCall(
                        call_id=call_id,
                        turn_id=turn_id,
                        session_id=session_id,
                        user_id=user_id,
                        tool_name=tool_name,
                        effect=str(call.get("effect") or ToolEffect.UNKNOWN.value),
                        arguments_json=arguments,
                        timeout_seconds=float(
                            call.get("timeout_seconds")
                            or settings.AGENT_TOOL_TIMEOUT_SECONDS
                        ),
                        status="deferred",
                        dispatch_generation=dispatch_generation,
                        policy_decision="defer",
                        policy_reason=f"batch_waiting:{blocked_by_call_id}"[:128],
                        model_step=call.get("model_step"),
                        model_call_index=call.get("model_call_index"),
                        model_call_order=call.get("model_call_order"),
                        handler_identity=call.get("handler_identity"),
                        provider_identity=call.get("provider_identity"),
                        connection_identity=call.get("connection_identity"),
                        resource_identities_json=list(
                            _bounded_resource_identities(
                                call.get("resource_identities") or ()
                            )
                        ),
                        timeline_json=[
                            _timeline_event(
                                "deferred",
                                dispatch_generation,
                                status="deferred",
                                blocked_by_call_id=blocked_by_call_id,
                            )
                        ],
                        receipt_refs_json=[],
                    )
                )
                db.flush()
            db.commit()
            return True
        finally:
            db.close()

    return await asyncio.to_thread(save)


def cancel_deferred_tool_calls(
    *,
    turn_id: str,
    dispatch_generation: int,
    blocked_by_call_id: str,
) -> list[dict[str, Any]]:
    """Close never-started calls after the user rejects their prerequisite."""

    db = SessionLocal()
    try:
        turn = db.get(ConversationTurn, turn_id)
        if turn is None or int(turn.dispatch_generation or 1) != dispatch_generation:
            return []
        rows = (
            db.query(AgentToolCall)
            .filter(
                AgentToolCall.turn_id == turn_id,
                AgentToolCall.status == "deferred",
            )
            .order_by(AgentToolCall.id)
            .with_for_update()
            .all()
        )
        closed: list[dict[str, Any]] = []
        now = utc_now()
        for row in rows:
            completion_sequence = _next_completion_sequence(db, turn_id)
            result = {
                "error": "tool_not_dispatched",
                "reason": "prerequisite_rejected",
                "blocked_by_call_id": blocked_by_call_id,
                "tool_name": row.tool_name,
            }
            row.status = "cancelled"
            row.result_json = _durable_result(result)
            row.error = "prerequisite_rejected"
            row.completed_at = now
            row.completion_sequence = completion_sequence
            _append_timeline(
                row,
                _timeline_event(
                    "finished",
                    dispatch_generation,
                    status="cancelled",
                    completion_sequence=completion_sequence,
                    blocked_by_call_id=blocked_by_call_id,
                ),
            )
            closed.append(
                {
                    "call_id": row.call_id,
                    "tool_name": row.tool_name,
                    "arguments": dict(row.arguments_json or {}),
                    "result": result,
                    "status": "cancelled",
                }
            )
        db.commit()
        return closed
    finally:
        db.close()


def _unresolved_live_resource_conflict(
    db: Any,
    *,
    user_id: int,
    turn_id: str,
    call_id: str,
    effect: str,
    resource_identities: Collection[str],
) -> dict[str, Any] | None:
    """Return the first same-user unresolved mutation touching this resource."""

    candidate_resources = _bounded_resource_identities(resource_identities)
    if effect == ToolEffect.READ.value or not candidate_resources:
        return None
    rows = (
        db.query(AgentToolCall)
        .filter(
            AgentToolCall.user_id == user_id,
            AgentToolCall.status.in_(_UNRESOLVED_RESOURCE_STATUSES),
            AgentToolCall.effect != ToolEffect.READ.value,
            # Policy asks are registered before `_finish` projects them as
            # waiting, but no handler has been admitted.  Only an allowed
            # call can reserve a resource at registration time.
            AgentToolCall.policy_decision == "allow",
        )
        .order_by(AgentToolCall.id)
        .with_for_update()
        .all()
    )
    for row in rows:
        if row.turn_id == turn_id and row.call_id == call_id:
            continue
        overlap = _resource_overlap(
            candidate_resources,
            row.resource_identities_json or (),
        )
        if overlap:
            return {
                "error": "reconcile_required",
                "reason": "unresolved_resource_side_effect",
                "blocking_call_id": row.call_id,
                "blocking_session_id": row.session_id,
                "resource_identities": list(overlap),
            }
    if has_unresolved_conversation_deletion_resource_conflict(
        db,
        user_id=user_id,
        resource_identities=candidate_resources,
        lock=True,
    ):
        return {
            "error": "reconcile_required",
            "reason": "deleted_conversation_unresolved_resource_side_effect",
            "resource_identities": list(candidate_resources),
        }
    return None


def _start(
    call_id: str,
    turn_id: str,
    session_id: str,
    user_id: int,
    tool_name: str,
    arguments: dict[str, Any],
    timeout_seconds: float,
    effect: str,
    policy_decision: str,
    policy_reason: str,
    dispatch_generation: int,
    resume_waiting: bool,
    model_step: int | None = None,
    model_call_index: int | None = None,
    model_call_order: int | None = None,
    handler_identity: str | None = None,
    provider_identity: str | None = None,
    connection_identity: str | None = None,
    resource_identities: Collection[str] = (),
) -> dict[str, Any] | None:
    db = SessionLocal()
    try:
        # Serialize admission in the durable user domain. Locking only the
        # candidate Turn cannot prevent two Conversations from observing an
        # empty unresolved-call set and starting the same external mutation.
        owner = (
            db.query(User).filter(User.id == user_id).with_for_update().one_or_none()
        )
        if owner is None:
            return {"error": "tool_owner_not_found", "tool_name": tool_name}
        # Short Turn-row lock makes call registration/resume exact-once across
        # competing workers without serializing the actual handler/network IO.
        turn = (
            db.query(ConversationTurn)
            .filter(ConversationTurn.id == turn_id)
            .with_for_update()
            .one_or_none()
        )
        if (
            turn is None
            or int(turn.dispatch_generation or 1) != dispatch_generation
            or turn.status in {"completed", "blocked", "failed", "cancelled"}
        ):
            return {
                "error": "stale_dispatch_generation",
                "tool_name": tool_name,
            }
        resource_conflict = _unresolved_live_resource_conflict(
            db,
            user_id=user_id,
            turn_id=turn_id,
            call_id=call_id,
            effect=effect,
            resource_identities=resource_identities,
        )
        if resource_conflict is not None:
            return resource_conflict
        existing = (
            db.query(AgentToolCall)
            .filter(
                AgentToolCall.turn_id == turn_id,
                AgentToolCall.call_id == call_id,
            )
            .one_or_none()
        )
        if existing is not None:
            if (
                existing.tool_name != tool_name
                or existing.arguments_json != arguments
                or _execution_identity_conflicts(
                    existing,
                    effect=effect,
                    handler_identity=handler_identity,
                    provider_identity=provider_identity,
                    connection_identity=connection_identity,
                    resource_identities=resource_identities,
                )
            ):
                return {
                    "error": "tool_call_identity_conflict",
                    "tool_name": tool_name,
                }
            if existing.status == "running":
                return {"error": "tool_call_in_progress", "tool_name": tool_name}
            if existing.status in {"waiting", "deferred"} and resume_waiting:
                previous_status = existing.status
                existing.status = "running"
                existing.dispatch_generation = dispatch_generation
                existing.policy_decision = policy_decision
                existing.policy_reason = policy_reason
                existing.result_json = None
                existing.error = None
                existing.started_at = utc_now()
                existing.completed_at = None
                existing.duration_ms = None
                existing.completion_sequence = None
                existing.handler_identity = (
                    handler_identity or existing.handler_identity
                )
                existing.provider_identity = provider_identity
                existing.connection_identity = connection_identity
                existing.resource_identities_json = list(
                    _bounded_resource_identities(resource_identities)
                )
                _append_timeline(
                    existing,
                    _timeline_event(
                        "resumed" if previous_status == "waiting" else "admitted",
                        dispatch_generation,
                        status="running",
                    ),
                )
                db.commit()
                return None
            if isinstance(existing.result_json, dict):
                if _is_legacy_truncated_audit_result(existing.result_json):
                    return {
                        "error": "tool_outcome_unknown",
                        "tool_name": tool_name,
                        "call_id": call_id,
                    }
                return dict(existing.result_json)
            return {
                "error": "tool_outcome_unknown",
                "tool_name": tool_name,
                "call_id": call_id,
            }
        db.add(
            AgentToolCall(
                call_id=call_id,
                turn_id=turn_id,
                session_id=session_id,
                user_id=user_id,
                tool_name=tool_name,
                effect=effect,
                arguments_json=arguments,
                timeout_seconds=timeout_seconds,
                status="running",
                dispatch_generation=dispatch_generation,
                policy_decision=policy_decision,
                policy_reason=policy_reason,
                model_step=model_step,
                model_call_index=model_call_index,
                model_call_order=model_call_order,
                handler_identity=handler_identity,
                provider_identity=provider_identity,
                connection_identity=connection_identity,
                resource_identities_json=list(
                    _bounded_resource_identities(resource_identities)
                ),
                timeline_json=[
                    _timeline_event(
                        "registered",
                        dispatch_generation,
                        status="running",
                    )
                ],
                receipt_refs_json=[],
            )
        )
        db.commit()
        return None
    finally:
        db.close()


def _execution_identity_conflicts(
    row: AgentToolCall,
    *,
    effect: str,
    handler_identity: str | None,
    provider_identity: str | None,
    connection_identity: str | None,
    resource_identities: Collection[str] = (),
) -> bool:
    persisted_resources = _bounded_resource_identities(
        row.resource_identities_json or ()
    )
    candidate_resources = _bounded_resource_identities(resource_identities)
    if (
        persisted_resources
        and candidate_resources
        and set(persisted_resources) != set(candidate_resources)
    ):
        return True
    """Reject a persisted call being redirected to a different dispatch target."""

    if row.effect != effect:
        return True
    for persisted, candidate in (
        (row.handler_identity, handler_identity),
        (row.provider_identity, provider_identity),
        (row.connection_identity, connection_identity),
    ):
        # Historical/connection-required rows may not yet know an identity.
        # Once both sides know it, an exact-call approval cannot cross it.
        if persisted is not None and candidate is not None and persisted != candidate:
            return True
    return False


def _record_replay(
    call_id: str,
    turn_id: str,
    dispatch_generation: int,
) -> None:
    db = SessionLocal()
    try:
        row = (
            db.query(AgentToolCall)
            .filter(
                AgentToolCall.turn_id == turn_id,
                AgentToolCall.call_id == call_id,
            )
            .one_or_none()
        )
        if row is None:
            return
        _append_timeline(
            row,
            _timeline_event(
                "replayed",
                dispatch_generation,
                status=row.status,
            ),
        )
        db.commit()
    finally:
        db.close()


def _mark_handler_started(
    call_id: str,
    turn_id: str,
    dispatch_generation: int,
) -> bool:
    db = SessionLocal()
    try:
        turn = (
            db.query(ConversationTurn)
            .filter(ConversationTurn.id == turn_id)
            .with_for_update()
            .one_or_none()
        )
        row = (
            db.query(AgentToolCall)
            .filter(
                AgentToolCall.turn_id == turn_id,
                AgentToolCall.call_id == call_id,
            )
            .one_or_none()
        )
        if (
            turn is None
            or row is None
            or row.status != "running"
            or row.dispatch_generation != dispatch_generation
            or int(turn.dispatch_generation or 1) != dispatch_generation
            or turn.status in {"completed", "blocked", "failed", "cancelled"}
        ):
            return False
        _append_timeline(
            row,
            _timeline_event(
                "handler_started",
                dispatch_generation,
                status="running",
            ),
        )
        db.commit()
        return True
    finally:
        db.close()


def _next_completion_sequence(db: Any, turn_id: str) -> int:
    """Allocate real completion order while holding the canonical Turn lock."""

    (
        db.query(ConversationTurn)
        .filter(ConversationTurn.id == turn_id)
        .with_for_update()
        .one_or_none()
    )
    maximum = 0
    rows = (
        db.query(AgentToolCall.completion_sequence, AgentToolCall.timeline_json)
        .filter(AgentToolCall.turn_id == turn_id)
        .all()
    )
    for completion_sequence, timeline in rows:
        if completion_sequence is not None:
            maximum = max(maximum, int(completion_sequence))
        for event in timeline or []:
            if isinstance(event, dict) and event.get("completion_sequence") is not None:
                try:
                    maximum = max(maximum, int(event["completion_sequence"]))
                except (TypeError, ValueError):
                    continue
    return maximum + 1


def record_tool_call_interrupt(
    db: Any,
    *,
    row: AgentToolCall,
    status: str,
    result: dict[str, Any],
    error: str,
) -> int:
    """Close a registered handler at the interrupt fence on its canonical row."""

    if status not in {"cancelled", "unknown"}:
        raise ValueError("interrupt status must be cancelled or unknown")
    completion_sequence = _next_completion_sequence(db, str(row.turn_id))
    row.status = status
    row.result_json = _durable_result(result)
    row.error = redact_tool_text(error)[:4_000]
    row.completed_at = utc_now()
    row.completion_sequence = completion_sequence
    _append_timeline(
        row,
        _timeline_event(
            "interrupted",
            int(row.dispatch_generation),
            status=status,
            completion_sequence=completion_sequence,
        ),
    )
    return completion_sequence


def _status_for_result(result: dict[str, Any]) -> str:
    reported_status = str(result.get("status") or "").casefold()
    if reported_status in {"partial", "unknown"}:
        # A partial external response cannot prove whether the side effect
        # happened.  Keep the call unresolved until a concrete reconciler
        # supplies a receipt/read-back.
        return "unknown"
    error = result.get("error")
    if error == "permission_denied":
        return "denied"
    if error in {"connection_required", "interaction_required", "policy_required"}:
        return "waiting"
    return "failed" if error else "completed"


def _finish(
    call_id: str,
    turn_id: str,
    session_id: str,
    user_id: int,
    tool_name: str,
    status: str,
    result: dict[str, Any] | None,
    error: str | None,
    duration_ms: float,
    dispatch_generation: int,
    receipt_refs: list[str] | None = None,
) -> dict[str, Any] | None:
    db = SessionLocal()
    try:
        row = (
            db.query(AgentToolCall)
            .filter(
                AgentToolCall.turn_id == turn_id,
                AgentToolCall.call_id == call_id,
            )
            .one_or_none()
        )
        if row is None:
            # Conversation deletion removes the original call/Turn rows but
            # leaves a minimal receipt tombstone for already-started provider
            # work.  A late terminal result may settle only its whitelisted
            # correlation fields; it never recreates History or runtime state.
            if status in {"completed", "failed", "cancelled"}:
                settled = settle_deleted_conversation_receipt(
                    db,
                    user_pk=user_id,
                    deleted_conversation_id=session_id,
                    turn_id=turn_id,
                    call_id=call_id,
                    status=status,
                    correlation=_safe_result(result),
                )
                if settled:
                    db.commit()
            return result
        turn = db.get(ConversationTurn, turn_id)
        stale = (
            turn is None
            or row.dispatch_generation != dispatch_generation
            or int(turn.dispatch_generation or 1) != dispatch_generation
            or turn.status in {"completed", "blocked", "failed", "cancelled"}
        )
        if stale:
            # The fence prevents a late worker from resuming or mutating the
            # terminal Turn, but it must not erase a real provider outcome.
            # Record it on the original call identity for reconciliation and
            # return only a stale signal to the obsolete execution pass.
            if (
                turn is not None
                and row.dispatch_generation == dispatch_generation
                # Waiting/deferred/denied calls never dispatched.  A running
                # handler (or a legacy unknown row) may still deliver a real
                # provider result after the Turn fence moved.
                and (_handler_was_started(row) or row.status == "unknown")
                and status != "cancelled"
                and row.status != "completed"
            ):
                completion_sequence = _next_completion_sequence(db, turn_id)
                late_result = _safe_result(result)
                late_result["late_result"] = True
                late_result["turn_status"] = turn.status
                late_result["requires_reconcile"] = status == "unknown"
                row.status = status
                row.result_json = _durable_result(late_result)
                row.error = redact_tool_text(error)[:4_000] if error else None
                row.duration_ms = round(duration_ms, 2)
                row.completed_at = utc_now()
                row.completion_sequence = completion_sequence
                if receipt_refs:
                    row.receipt_refs_json = list(receipt_refs)[:_RECEIPT_REF_LIMIT]
                _append_timeline(
                    row,
                    _timeline_event(
                        "late_result",
                        dispatch_generation,
                        status=status,
                        completion_sequence=completion_sequence,
                    ),
                )
                db.commit()
            return {
                "error": "stale_dispatch_generation",
                "tool_name": tool_name,
            }
        final_result = _safe_result(result)
        # Every emitted tool_done boundary, including a transition to waiting,
        # receives a Turn-atomic sequence. A resume clears the current field
        # while the bounded timeline preserves the earlier waiting boundary.
        completion_sequence = _next_completion_sequence(db, turn_id)
        if status == "waiting":
            kind = (
                "connection"
                if final_result.get("interaction_type") == "connection"
                or final_result.get("error") == "connection_required"
                else "approval"
            )
            request = ToolInteractionRequest(
                tool_name=tool_name,
                call_id=call_id,
                effect=row.effect,
                reason=(str(final_result.get("reason") or error or row.policy_reason)),
                arguments=dict(row.arguments_json or {}),
            )
            try:
                interaction = create_pending_interaction(
                    db,
                    turn_id=turn_id,
                    user_id=user_id,
                    kind=kind,
                    request=request,
                    tool_call_id=call_id,
                )
            except InteractionConflictError:
                interaction = get_pending_interaction(
                    db,
                    turn_id=turn_id,
                    user_id=user_id,
                )
            if interaction is not None:
                final_result["interaction"] = {
                    "id": interaction.id,
                    "version": interaction.version,
                    "kind": interaction.kind,
                }
        row.status = status
        row.result_json = _durable_result(final_result)
        row.error = redact_tool_text(error)[:4_000] if error else None
        row.duration_ms = round(duration_ms, 2)
        row.completed_at = utc_now()
        row.completion_sequence = completion_sequence
        if receipt_refs:
            row.receipt_refs_json = list(receipt_refs)[:_RECEIPT_REF_LIMIT]
        _append_timeline(
            row,
            _timeline_event(
                "waiting" if status == "waiting" else "finished",
                dispatch_generation,
                status=status,
                completion_sequence=completion_sequence,
            ),
        )
        db.commit()
        return final_result
    finally:
        db.close()


def reject_waiting_tool_call(
    *,
    call_id: str,
    turn_id: str,
    dispatch_generation: int,
    reason: str = "user_rejected",
) -> dict[str, Any]:
    """Pair a rejected Interaction with its original Tool Call identity."""
    db = SessionLocal()
    try:
        turn = db.get(ConversationTurn, turn_id)
        row = (
            db.query(AgentToolCall)
            .filter(
                AgentToolCall.turn_id == turn_id,
                AgentToolCall.call_id == call_id,
            )
            .with_for_update()
            .one_or_none()
        )
        if (
            turn is None
            or row is None
            or row.status != "waiting"
            or int(turn.dispatch_generation or 1) != dispatch_generation
        ):
            return {"error": "stale_dispatch_generation", "call_id": call_id}
        result = {
            "error": "user_rejected",
            "tool_name": row.tool_name,
            "reason": reason,
        }
        row.status = "denied"
        row.dispatch_generation = dispatch_generation
        row.policy_decision = "deny"
        row.policy_reason = "user_rejected"
        row.result_json = _durable_result(result)
        row.error = "user_rejected"
        row.completed_at = utc_now()
        completion_sequence = _next_completion_sequence(db, turn_id)
        row.completion_sequence = completion_sequence
        _append_timeline(
            row,
            _timeline_event(
                "finished",
                dispatch_generation,
                status="denied",
                completion_sequence=completion_sequence,
            ),
        )
        db.commit()
        return result
    finally:
        db.close()


async def persist_turn_budget(turn_id: str | None, budget: dict[str, Any]) -> None:
    if not turn_id:
        return

    def save() -> None:
        db = SessionLocal()
        try:
            row = db.get(ConversationTurn, turn_id)
            if row is not None:
                current = dict(row.budget_json or {})
                row.budget_json = {**current, **budget}
                db.commit()
        finally:
            db.close()

    await asyncio.to_thread(save)
