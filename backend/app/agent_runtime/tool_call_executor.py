from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime
from typing import Any, Awaitable, Callable

from app.core.config import settings
from app.db.database import SessionLocal
from app.models.agent_execution import AgentToolCall
from app.models.conversation_turn import ConversationTurn
from app.services.capabilities import conversation_capability_service


Dispatch = Callable[[], Awaitable[dict[str, Any]]]
_AUDIT_RESULT_CHARS = 16_000
logger = logging.getLogger(__name__)


def _audit_result(result: dict[str, Any] | None) -> dict[str, Any] | None:
    if result is None:
        return None
    encoded = json.dumps(result, ensure_ascii=False, default=str)
    if len(encoded) <= _AUDIT_RESULT_CHARS:
        return result
    return {
        "truncated": True,
        "original_chars": len(encoded),
        "preview": encoded[:_AUDIT_RESULT_CHARS],
    }


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
) -> dict[str, Any]:
    """Execute one call with timeout/cancellation and durable lifecycle audit."""
    started = time.perf_counter()
    encoded_arguments = json.dumps(arguments, ensure_ascii=False, default=str)
    arguments_too_large = len(encoded_arguments) > settings.AGENT_MAX_TOOL_ARG_CHARS
    audited_arguments = (
        arguments
        if not arguments_too_large
        else {
            "truncated": True,
            "original_chars": len(encoded_arguments),
            "preview": encoded_arguments[: settings.AGENT_MAX_TOOL_ARG_CHARS],
        }
    )
    if turn_id:
        await asyncio.to_thread(
            _start,
            call_id,
            turn_id,
            session_id,
            user_id,
            tool_name,
            audited_arguments,
            timeout_seconds,
        )
    if arguments_too_large:
        result = {"error": "tool_args_too_large", "tool_name": tool_name}
        if turn_id:
            await asyncio.to_thread(
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
            )
        return result
    try:
        async with asyncio.timeout(timeout_seconds):
            result = await dispatch()
        status = (
            "denied"
            if result.get("error") == "permission_denied"
            else "failed"
            if "error" in result
            else "completed"
        )
        error = str(result.get("error")) if "error" in result else None
    except TimeoutError:
        result = {"error": "tool_timeout", "tool_name": tool_name}
        status, error = "timeout", "tool_timeout"
    except asyncio.CancelledError:
        if turn_id:
            await asyncio.shield(
                asyncio.to_thread(
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
                )
            )
        raise
    except ValueError as exc:
        result = {"error": str(exc)}
        status, error = "failed", str(exc)
    except Exception as exc:  # noqa: BLE001
        logger.exception("tool call failed: %s", tool_name)
        result = {"error": "tool_execution_failed", "tool_name": tool_name}
        status, error = "failed", type(exc).__name__

    if turn_id:
        await asyncio.to_thread(
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
        )
    return result


def _start(
    call_id: str,
    turn_id: str,
    session_id: str,
    user_id: int,
    tool_name: str,
    arguments: dict[str, Any],
    timeout_seconds: float,
) -> None:
    db = SessionLocal()
    try:
        db.add(
            AgentToolCall(
                call_id=call_id,
                turn_id=turn_id,
                session_id=session_id,
                user_id=user_id,
                tool_name=tool_name,
                arguments_json=arguments,
                timeout_seconds=timeout_seconds,
                status="running",
            )
        )
        db.commit()
    finally:
        db.close()


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
        row.status = status
        row.result_json = _audit_result(result)
        row.error = error[:4_000] if error else None
        row.duration_ms = round(duration_ms, 2)
        row.completed_at = datetime.utcnow()
        capability_state = conversation_capability_service.get_or_create(
            db,
            session_id,
            user_id,
        )
        conversation_capability_service.append_tool_history(
            db,
            capability_state,
            tool_name=tool_name,
            status=status,
            turn_id=turn_id,
        )
        db.commit()
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
