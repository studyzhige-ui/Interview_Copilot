from __future__ import annotations

import asyncio
import logging
import os
import socket
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.conversation.events import HarnessEvent
from app.core.config import settings
from app.core.error_messages import humanize_error
from app.db.database import SessionLocal
from app.models.chat import Conversation, ConversationMessage
from app.models.conversation_turn import ConversationTurn
from app.models.user import User
from app.services.chat.turn_event_buffer import turn_event_buffer
from app.services.chat.chat_history_service import transcript_service


logger = logging.getLogger(__name__)
_WORKER_ID = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"


@dataclass(frozen=True)
class TurnExecution:
    id: str
    conversation_id: str
    username: str
    mode: str
    message: str


def create_turn(
    db: Session,
    conversation: Conversation,
    *,
    user_id: int,
    mode: str,
    message: str,
) -> ConversationTurn:
    locked = (
        db.query(Conversation)
        .filter(
            Conversation.id == conversation.id,
            Conversation.user_id == user_id,
        )
        .with_for_update()
        # ``conversation`` was normally loaded earlier by the API, so it is
        # already present in this Session's identity map. Force the locked
        # SELECT to refresh it; otherwise concurrent waiters can keep seeing
        # the pre-lock ``active_turn_id=None`` snapshot and all create a turn.
        .populate_existing()
        .one()
    )
    if locked.active_turn_id:
        active = db.get(ConversationTurn, locked.active_turn_id)
        if active and active.status in {"pending", "running"}:
            raise ValueError(active.id)
    row = ConversationTurn(
        conversation_id=locked.id,
        user_id=user_id,
        mode=mode,
        message=message,
        status="pending",
    )
    max_seq = (
        db.query(func.max(ConversationMessage.seq))
        .filter(
            ConversationMessage.conversation_id == locked.id,
        )
        .scalar()
    )
    row.user_message_seq = (max_seq or 0) + 1
    db.add(
        ConversationMessage(
            conversation_id=locked.id,
            seq=row.user_message_seq,
            role="User",
            content=message,
        )
    )
    db.add(row)
    db.flush()
    locked.active_turn_id = row.id
    db.commit()
    db.refresh(row)
    return row


def cancel_pending_turn(db: Session, turn_id: str, user_id: int) -> bool:
    """Atomically cancel a turn that no worker has claimed yet."""
    row = (
        db.query(ConversationTurn)
        .filter(
            ConversationTurn.id == turn_id,
            ConversationTurn.user_id == user_id,
        )
        .with_for_update()
        .one_or_none()
    )
    if row is None or row.status != "pending":
        return False
    row.status = "cancelled"
    row.error = "Turn cancelled"
    row.completed_at = datetime.utcnow()
    conversation = db.get(Conversation, row.conversation_id)
    if conversation and conversation.active_turn_id == turn_id:
        conversation.active_turn_id = None
    db.commit()
    return True


def fail_pending_turn(
    db: Session,
    turn_id: str,
    user_id: int,
    error: str,
) -> bool:
    """Fail a durable turn when it could not be sent to the worker queue."""
    row = (
        db.query(ConversationTurn)
        .filter(
            ConversationTurn.id == turn_id,
            ConversationTurn.user_id == user_id,
        )
        .with_for_update()
        .one_or_none()
    )
    if row is None or row.status != "pending":
        return False
    row.status = "failed"
    row.error = error
    row.completed_at = datetime.utcnow()
    conversation = db.get(Conversation, row.conversation_id)
    if conversation and conversation.active_turn_id == turn_id:
        conversation.active_turn_id = None
    db.commit()
    return True


def _claim(turn_id: str) -> TurnExecution | None:
    """Atomically lease one pending turn to this worker."""
    db = SessionLocal()
    try:
        row = (
            db.query(ConversationTurn)
            .filter(
                ConversationTurn.id == turn_id,
            )
            .with_for_update()
            .one_or_none()
        )
        if row is None or row.status != "pending":
            return None
        username = db.query(User.username).filter(User.id == row.user_id).scalar()
        if username is None:
            return None
        now = datetime.utcnow()
        row.status = "running"
        row.started_at = now
        row.heartbeat_at = now
        row.owner_id = _WORKER_ID
        result = TurnExecution(
            id=row.id,
            conversation_id=row.conversation_id,
            username=username,
            mode=row.mode,
            message=row.message,
        )
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _finish(turn_id: str, status: str, error: str | None = None) -> bool:
    """Commit a terminal state only while this worker still owns the lease."""
    db = SessionLocal()
    try:
        row = (
            db.query(ConversationTurn)
            .filter(
                ConversationTurn.id == turn_id,
            )
            .with_for_update()
            .one_or_none()
        )
        if row is None or row.status != "running" or row.owner_id != _WORKER_ID:
            return False
        row.status = status
        row.error = error
        row.completed_at = datetime.utcnow()
        conversation = db.get(Conversation, row.conversation_id)
        if conversation and conversation.active_turn_id == turn_id:
            conversation.active_turn_id = None
        db.commit()
        return True
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _heartbeat(turn_id: str) -> None:
    db = SessionLocal()
    try:
        row = db.get(ConversationTurn, turn_id)
        if row is not None and row.status == "running" and row.owner_id == _WORKER_ID:
            row.heartbeat_at = datetime.utcnow()
            db.commit()
    finally:
        db.close()


def _has_assistant(turn_id: str) -> bool:
    db = SessionLocal()
    try:
        row = db.get(ConversationTurn, turn_id)
        return bool(row and row.assistant_message_seq is not None)
    finally:
        db.close()


async def execute_turn(turn_id: str) -> None:
    turn = await asyncio.to_thread(_claim, turn_id)
    if turn is None:
        return
    saw_done = False
    failure: str | None = None
    engine = None
    cancelled = False
    owner_task = asyncio.current_task()

    async def watch_cancel() -> None:
        await turn_event_buffer.wait_cancel(turn_id)
        if owner_task is not None:
            owner_task.cancel()

    cancel_watcher = asyncio.create_task(
        watch_cancel(), name=f"chat-turn-cancel:{turn_id}"
    )

    async def maintain_heartbeat() -> None:
        while True:
            await asyncio.sleep(settings.TURN_HEARTBEAT_SECONDS)
            try:
                await asyncio.to_thread(_heartbeat, turn_id)
            except Exception:  # noqa: BLE001
                logger.exception("turn heartbeat failed: %s", turn_id)

    heartbeat = asyncio.create_task(
        maintain_heartbeat(),
        name=f"chat-turn-heartbeat:{turn_id}",
    )
    try:
        from app.conversation import (
            ConversationEngine,
            make_agent_strategy,
            make_chat_strategy,
        )

        strategy = (
            make_agent_strategy() if turn.mode == "agent" else make_chat_strategy()
        )
        engine = ConversationEngine(
            user_id=turn.username,
            session_id=turn.conversation_id,
            user_message=turn.message,
            strategy=strategy,
            turn_id=turn_id,
        )
        async for event in engine.submit_message():
            await turn_event_buffer.append(turn_id, event.to_json())
            saw_done = saw_done or event.type.value == "done"
            if event.type.value == "error":
                failure = str(event.data.get("error") or "Turn execution failed")
        if not failure and not await asyncio.to_thread(_has_assistant, turn_id):
            failure = "本轮未生成有效回复"
    except asyncio.CancelledError:
        failure = "Turn cancelled"
        cancelled = True
        raise
    except Exception as exc:  # noqa: BLE001
        failure = humanize_error(exc)
        logger.exception("background turn %s failed", turn_id)
        await turn_event_buffer.append(turn_id, HarnessEvent.error(failure).to_json())
    finally:
        try:
            if failure and engine is not None and not cancelled:
                await engine.persist_background_failure(failure)
            if not saw_done:
                await turn_event_buffer.append(
                    turn_id,
                    HarnessEvent.done(step=0, elapsed_ms=0).to_json(),
                )
        finally:
            cancel_watcher.cancel()
            heartbeat.cancel()
            await asyncio.gather(cancel_watcher, heartbeat, return_exceptions=True)
            await asyncio.to_thread(
                _finish,
                turn_id,
                "cancelled" if cancelled else "failed" if failure else "completed",
                failure,
            )


def schedule_turn(turn_id: str) -> None:
    """Dispatch a durable turn to the isolated conversation-worker queue."""
    from app.task_queue.dispatch import dispatch_conversation_turn

    dispatch_conversation_turn(turn_id)


async def fail_orphaned_turns() -> int:
    """Close turns whose worker heartbeat has expired."""
    db = SessionLocal()
    try:
        cutoff = datetime.utcnow() - timedelta(seconds=settings.TURN_STALE_SECONDS)
        rows = (
            db.query(ConversationTurn)
            .filter(
                or_(
                    (ConversationTurn.status == "pending")
                    & (ConversationTurn.created_at < cutoff),
                    (ConversationTurn.status == "running")
                    & (
                        func.coalesce(
                            ConversationTurn.heartbeat_at,
                            ConversationTurn.started_at,
                            ConversationTurn.created_at,
                        )
                        < cutoff
                    ),
                )
            )
            .with_for_update(skip_locked=True)
            .all()
        )
        turn_ids = [row.id for row in rows]
        for row in rows:
            row.status = "failed"
            row.error = "服务重启，本轮执行已中断"
            row.completed_at = datetime.utcnow()
            conversation = db.get(Conversation, row.conversation_id)
            if conversation and conversation.active_turn_id == row.id:
                conversation.active_turn_id = None
        db.commit()
    finally:
        db.close()

    for turn_id in turn_ids:
        await asyncio.to_thread(
            transcript_service.complete_background_turn,
            turn_id=turn_id,
            ai_msg="⚠️ 服务重启，本轮执行已中断",
            ai_blocks=[{"type": "text", "text": "⚠️ 服务重启，本轮执行已中断"}],
        )
        await turn_event_buffer.append(
            turn_id,
            HarnessEvent.error("服务重启，本轮执行已中断").to_json(),
        )
        await turn_event_buffer.append(
            turn_id,
            HarnessEvent.done(step=0, elapsed_ms=0).to_json(),
        )
    return len(turn_ids)


async def monitor_orphaned_turns() -> None:
    interval = max(5, settings.TURN_STALE_SECONDS // 2)
    while True:
        await asyncio.sleep(interval)
        try:
            orphan_count = await fail_orphaned_turns()
            if orphan_count:
                logger.warning("Closed %d stale conversation turn(s).", orphan_count)
        except Exception:  # noqa: BLE001
            logger.exception("orphan turn monitor failed")
