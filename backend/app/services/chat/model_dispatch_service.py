"""Durable model dispatch fencing shared by Chat and Agent strategies."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.model_provider_adapter import close_provider_stream
from app.core.context_budget import ContextCapacityError
from app.services.chat import model_budget_service
from app.db.database import SessionLocal
from app.db.types import utc_now
from app.models.conversation_turn import ConversationTurn
from app.models.model_dispatch import AgentModelDispatch

_MAX_PARTIAL_CHARS = 256_000
_FLUSH_CHARS = 2_048


class ModelDispatchConflictError(RuntimeError):
    pass


class ModelOutcomeUnknownError(RuntimeError):
    """Paid dispatch may have happened; stop instead of blindly retrying."""


class ModelStreamCapacityError(RuntimeError):
    pass


def dispatch_failure_status(exc: BaseException) -> str:
    # Local capacity validation precedes provider I/O. Explicit 4xx responses
    # other than request timeout are known refusals. Transport/5xx/cancellation
    # do not establish whether the provider ran (or charged for) the request.
    status = getattr(exc, "status_code", None)
    if isinstance(exc, ContextCapacityError) or status in {
        400,
        401,
        402,
        403,
        404,
        413,
        422,
        429,
    }:
        return "failed"
    return "unknown"


def request_fingerprint(
    *,
    messages: list[dict],
    tools: list[dict] | None,
    system: str = "",
    max_tokens: int | None = None,
    temperature: float | None = None,
) -> str:
    encoded = json.dumps(
        {
            "messages": messages,
            "tools": tools or [],
            "system": system,
            "max_tokens": max_tokens,
            "temperature": temperature,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def start_model_dispatch(
    db: Session,
    *,
    call_id: str,
    turn_id: str,
    user_id: int,
    dispatch_generation: int,
    provider: str,
    model: str,
    fingerprint: str,
    token_allowance: int = 4096,
) -> AgentModelDispatch:
    turn = (
        db.query(ConversationTurn)
        .filter(ConversationTurn.id == turn_id)
        .with_for_update()
        .populate_existing()
        .one_or_none()
    )
    if (
        turn is None
        or turn.user_id != user_id
        or int(turn.dispatch_generation or 1) != dispatch_generation
        or turn.status in {"completed", "blocked", "failed", "cancelled"}
    ):
        raise ModelDispatchConflictError("stale_model_dispatch_generation")

    row = (
        db.query(AgentModelDispatch)
        .filter(
            AgentModelDispatch.turn_id == turn_id,
            AgentModelDispatch.call_id == call_id,
        )
        .one_or_none()
    )
    if row is not None:
        if (
            row.user_id != user_id
            or row.dispatch_generation != dispatch_generation
            or row.request_fingerprint != fingerprint
            or row.provider != provider
            or row.model != model
        ):
            raise ModelDispatchConflictError("model_dispatch_identity_conflict")
        # A metadata lookup is not a second dispatch permit. The owning worker
        # may still be using the first permit; a retry must resolve its outcome.
        raise ModelDispatchConflictError(f"model_dispatch_already_{row.status}")

    model_budget_service.reserve(
        db,
        user_id=user_id,
        turn_id=turn_id,
        call_id=call_id,
        token_allowance=token_allowance,
    )
    row = AgentModelDispatch(
        call_id=call_id,
        turn_id=turn_id,
        user_id=user_id,
        dispatch_generation=dispatch_generation,
        provider=provider,
        model=model,
        request_fingerprint=fingerprint,
        status="running",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def start_model_dispatch_for_turn(**kwargs: Any) -> AgentModelDispatch:
    db = SessionLocal()
    try:
        return start_model_dispatch(db, **kwargs)
    finally:
        db.close()


def append_partial_text(
    *,
    turn_id: str,
    call_id: str,
    dispatch_generation: int,
    text: str,
) -> None:
    if not text:
        return
    db = SessionLocal()
    try:
        row = (
            db.query(AgentModelDispatch)
            .filter(
                AgentModelDispatch.turn_id == turn_id,
                AgentModelDispatch.call_id == call_id,
            )
            .with_for_update()
            .one_or_none()
        )
        turn = db.get(ConversationTurn, turn_id)
        if (
            row is None
            or turn is None
            or row.status != "running"
            or row.dispatch_generation != dispatch_generation
            or int(turn.dispatch_generation or 1) != dispatch_generation
        ):
            return
        remaining = _MAX_PARTIAL_CHARS - len(row.partial_text or "")
        if remaining > 0:
            row.partial_text = (row.partial_text or "") + text[:remaining]
            row.updated_at = utc_now()
        db.commit()
    finally:
        db.close()


def finish_model_dispatch(
    *,
    turn_id: str,
    call_id: str,
    dispatch_generation: int,
    status: str,
    usage: dict[str, int] | None = None,
    error_code: str | None = None,
) -> None:
    if status not in {"completed", "failed", "cancelled", "unknown"}:
        raise ValueError("invalid model dispatch terminal status")
    db = SessionLocal()
    try:
        row = (
            db.query(AgentModelDispatch)
            .filter(
                AgentModelDispatch.turn_id == turn_id,
                AgentModelDispatch.call_id == call_id,
            )
            .with_for_update()
            .one_or_none()
        )
        if row is None or row.dispatch_generation != dispatch_generation:
            return
        if row.status != "running":
            return
        observed_tokens = (
            max(0, int(usage.get("prompt_tokens", 0)))
            + max(0, int(usage.get("completion_tokens", 0)))
            if usage
            else None
        )
        # Cache reads/creation are already included in logical prompt_tokens.
        model_budget_service.settle(
            db,
            user_id=row.user_id,
            turn_id=turn_id,
            call_id=call_id,
            outcome=(
                "completed"
                if status == "completed"
                else "rejected"
                if status == "failed"
                else "unknown"
            ),
            observed_tokens=observed_tokens,
        )
        row.status = status
        row.usage_json = dict(usage or {})
        row.error_code = error_code
        row.completed_at = utc_now()
        row.updated_at = row.completed_at
        db.commit()
    finally:
        db.close()


async def durable_model_stream(
    stream: Any,
    *,
    turn_id: str | None,
    call_id: str | None,
    dispatch_generation: int,
    deadline: float | None = None,
) -> AsyncIterator[Any]:
    """Yield a provider stream while durably checkpointing safe text deltas."""

    pending: list[str] = []
    pending_chars = 0
    usage: dict[str, int] = {}

    async def flush() -> None:
        nonlocal pending_chars
        if not turn_id or not call_id or not pending:
            return
        text = "".join(pending)
        pending.clear()
        pending_chars = 0

        await asyncio.to_thread(
            append_partial_text,
            turn_id=turn_id,
            call_id=call_id,
            dispatch_generation=dispatch_generation,
            text=text,
        )

    if deadline is None:
        deadline = (
            asyncio.get_running_loop().time() + settings.MODEL_STREAM_DEADLINE_SECONDS
        )
    iterator = stream.__aiter__()
    received_bytes = 0
    try:
        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise TimeoutError("model_stream_deadline")
            try:
                chunk = await asyncio.wait_for(anext(iterator), remaining)
            except StopAsyncIteration:
                break
            received_bytes += len(str(chunk).encode("utf-8"))
            if received_bytes > settings.MODEL_STREAM_MAX_BYTES:
                raise ModelStreamCapacityError("model_stream_capacity_exceeded")
            delta = str(
                getattr(chunk, "text_delta", "") or getattr(chunk, "delta", "") or ""
            )
            if delta:
                pending.append(delta)
                pending_chars += len(delta)
                if pending_chars >= _FLUSH_CHARS:
                    await flush()
            observed = getattr(chunk, "usage", None)
            if observed is not None:
                # Native Anthropic reports input at message_start and output
                # later; zero in a partial event is not a reset. Components are
                # cumulative observations, not numbers to add repeatedly.
                for field in (
                    "prompt_tokens",
                    "completion_tokens",
                    "cache_read_tokens",
                    "cache_creation_tokens",
                ):
                    value = int(getattr(observed, field, 0) or 0)
                    # Bound each untrusted counter before summing or persisting;
                    # a full day of admitted calls must fit signed BIGINT too.
                    if not 0 <= value <= 2**31 - 1:
                        raise ModelStreamCapacityError("invalid_provider_usage")
                    usage[field] = max(usage.get(field, 0), value)
            yield chunk
        await flush()
        if turn_id and call_id:
            await asyncio.to_thread(
                finish_model_dispatch,
                turn_id=turn_id,
                call_id=call_id,
                dispatch_generation=dispatch_generation,
                status="completed",
                usage=usage,
            )
    except BaseException as exc:
        await flush()
        if turn_id and call_id:
            # A partial stream is not a proof of provider failure/zero charge.
            status = "unknown"
            await asyncio.to_thread(
                finish_model_dispatch,
                turn_id=turn_id,
                call_id=call_id,
                dispatch_generation=dispatch_generation,
                status=status,
                usage=usage,
                error_code=type(exc).__name__,
            )
        raise
    finally:
        await close_provider_stream(stream)


__all__ = [
    "ModelDispatchConflictError",
    "durable_model_stream",
    "finish_model_dispatch",
    "request_fingerprint",
    "start_model_dispatch",
    "start_model_dispatch_for_turn",
]
