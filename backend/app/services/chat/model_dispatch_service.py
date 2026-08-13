"""Durable model dispatch fencing shared by Chat and Agent strategies."""

from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.db.types import utc_now
from app.models.conversation_turn import ConversationTurn
from app.models.model_dispatch import AgentModelDispatch

_MAX_PARTIAL_CHARS = 256_000
_FLUSH_CHARS = 2_048


class ModelDispatchConflictError(RuntimeError):
    pass


def request_fingerprint(*, messages: list[dict], tools: list[dict] | None) -> str:
    encoded = json.dumps(
        {"messages": messages, "tools": tools or []},
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
) -> AgentModelDispatch:
    turn = db.get(ConversationTurn, turn_id)
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
        if row.status != "running":
            raise ModelDispatchConflictError(f"model_dispatch_already_{row.status}")
        return row

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
        import asyncio

        await asyncio.to_thread(
            append_partial_text,
            turn_id=turn_id,
            call_id=call_id,
            dispatch_generation=dispatch_generation,
            text=text,
        )

    try:
        async for chunk in stream:
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
                usage = {
                    "prompt_tokens": int(getattr(observed, "prompt_tokens", 0) or 0),
                    "completion_tokens": int(
                        getattr(observed, "completion_tokens", 0) or 0
                    ),
                    "cache_read_tokens": int(
                        getattr(observed, "cache_read_tokens", 0) or 0
                    ),
                    "cache_creation_tokens": int(
                        getattr(observed, "cache_creation_tokens", 0) or 0
                    ),
                }
            yield chunk
        await flush()
        if turn_id and call_id:
            import asyncio

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
            import asyncio

            status = (
                "cancelled" if isinstance(exc, asyncio.CancelledError) else "failed"
            )
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


__all__ = [
    "ModelDispatchConflictError",
    "durable_model_stream",
    "finish_model_dispatch",
    "request_fingerprint",
    "start_model_dispatch",
    "start_model_dispatch_for_turn",
]
