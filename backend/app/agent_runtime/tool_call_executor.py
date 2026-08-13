from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Awaitable, Callable

from app.core.config import settings
from app.db.database import SessionLocal
from app.db.types import utc_now
from app.models.agent_execution import AgentToolCall
from app.models.conversation_turn import ConversationTurn
from app.schemas.agent_interaction import ToolInteractionRequest
from app.services.chat.interaction_service import (
    InteractionConflictError,
    create_pending_interaction,
    get_pending_interaction,
)

from .tool_policy import (
    ToolEffect,
    ToolPolicyContext,
    evaluate_tool_policy,
)
from .tool_redaction import redact_tool_text, redact_tool_value

Dispatch = Callable[[], Awaitable[dict[str, Any]]]
_AUDIT_RESULT_CHARS = 16_000
logger = logging.getLogger(__name__)


def _audit_result(result: dict[str, Any] | None) -> dict[str, Any] | None:
    if result is None:
        return None
    redacted = redact_tool_value(result)
    encoded = json.dumps(redacted, ensure_ascii=False, default=str)
    if len(encoded) <= _AUDIT_RESULT_CHARS:
        return redacted
    return {
        "truncated": True,
        "original_chars": len(encoded),
        "preview": encoded[:_AUDIT_RESULT_CHARS],
    }


def _safe_result(result: dict[str, Any] | None) -> dict[str, Any]:
    """Return the only Tool result representation allowed past execution.

    Handlers receive their original typed inputs, but their output is external
    data.  Redact it once at this boundary before it can reach the model,
    Conversation history, persisted overflow storage, SSE, or audit views.
    """

    safe = redact_tool_value(dict(result or {}))
    return dict(safe) if isinstance(safe, dict) else {"result": safe}


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
) -> dict[str, Any]:
    """Execute one call with timeout/cancellation and durable lifecycle audit."""
    started = time.perf_counter()
    decision = evaluate_tool_policy(effect, policy_context or ToolPolicyContext())
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
    if decision.outcome != "allow":
        result = {
            "error": (
                "interaction_required"
                if decision.outcome == "ask"
                else "permission_denied"
            ),
            "interaction_type": (
                "connection" if decision.reason == "connection_required" else "approval"
            ),
            "tool_name": tool_name,
            "reason": decision.reason,
        }
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
        )
        if finished is not None:
            result = finished
    return _safe_result(result)


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
) -> dict[str, Any] | None:
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
        if existing is not None:
            if existing.tool_name != tool_name or existing.arguments_json != arguments:
                return {
                    "error": "tool_call_identity_conflict",
                    "tool_name": tool_name,
                }
            if existing.status == "running":
                return {"error": "tool_call_in_progress", "tool_name": tool_name}
            if existing.status == "waiting" and resume_waiting:
                existing.status = "running"
                existing.dispatch_generation = dispatch_generation
                existing.policy_decision = policy_decision
                existing.policy_reason = policy_reason
                existing.result_json = None
                existing.error = None
                existing.started_at = utc_now()
                existing.completed_at = None
                existing.duration_ms = None
                db.commit()
                return None
            if isinstance(existing.result_json, dict):
                if existing.result_json.get("truncated"):
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
            )
        )
        db.commit()
        return None
    finally:
        db.close()


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
                and status != "cancelled"
                and row.status != "completed"
            ):
                late_result = _safe_result(result)
                late_result["late_result"] = True
                late_result["turn_status"] = turn.status
                late_result["requires_reconcile"] = status == "unknown"
                row.status = status
                row.result_json = _audit_result(late_result)
                row.error = redact_tool_text(error)[:4_000] if error else None
                row.duration_ms = round(duration_ms, 2)
                row.completed_at = utc_now()
                db.commit()
            return {
                "error": "stale_dispatch_generation",
                "tool_name": tool_name,
            }
        final_result = _safe_result(result)
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
        row.result_json = _audit_result(final_result)
        row.error = redact_tool_text(error)[:4_000] if error else None
        row.duration_ms = round(duration_ms, 2)
        row.completed_at = utc_now()
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
        row.result_json = _audit_result(result)
        row.error = "user_rejected"
        row.completed_at = utc_now()
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
