"""Post-turn maintenance service — runs in the background after each turn.

Order of operations:
  1. Compact the conversation into the ``summary`` column via dual-threshold
     trigger (token growth + turns)
  2. Run realtime memory extraction (v3) — writes the user's ability
     states / user_profile / learning_strategy.

The session-level asyncio lock here is independent of the Redis-backed
per-user lock used by realtime_extraction. Both are needed:
  * asyncio lock prevents two overlapping turns on the same session
    from doing the same work (cheap, in-process).
  * per-user Redis lock prevents this session's extraction from
    racing against the dreaming worker for the same user.
"""

import asyncio
import logging

from app.services.chat.chat_history_service import transcript_service
from app.services.memory.compaction_service import (
    CompactionService,
    compaction_service,
)
from app.services.memory import realtime_extraction

logger = logging.getLogger(__name__)


class PostTurnMaintenanceService:
    """Runs after each conversation turn as a background task.

    Responsibilities (in order):
    1. Compact the conversation into the ``summary`` column via dual-threshold
     trigger (token growth + turns)
    2. Realtime memory extraction (strong signals only — see
       ``realtime_extraction`` module)
    """

    def __init__(self, compaction: CompactionService):
        self.compaction = compaction
        self._locks: dict[str, asyncio.Lock] = {}
        self._locks_maxsize = 128

    def _lock_for(self, session_id: str) -> asyncio.Lock:
        lock = self._locks.get(session_id)
        if lock is None:
            if len(self._locks) >= self._locks_maxsize:
                oldest_key = next(iter(self._locks))
                del self._locks[oldest_key]
            lock = asyncio.Lock()
            self._locks[session_id] = lock
        return lock

    async def run(
        self,
        session_id: str,
        user_id: str,
        *,
        allow_memory_write: bool = True,
    ) -> None:
        async with self._lock_for(session_id):
            await self._run_locked(
                session_id=session_id,
                user_id=user_id,
                allow_memory_write=allow_memory_write,
            )

    async def _run_locked(
        self,
        *,
        session_id: str,
        user_id: str,
        allow_memory_write: bool,
    ) -> None:
        # Read meta BEFORE compaction so we capture memory_extraction_cursor
        # independently of any compaction_cursor advancement.
        # ``get_session_meta``, ``get_recent_turns``, ``_session_record_id``,
        # and ``update_session_fields`` all open sync ``SessionLocal``
        # sessions and run sync DB I/O — off the event loop via to_thread
        # so a background turn-maintenance task doesn't stall every
        # other SSE stream while it waits on Postgres.
        meta = await asyncio.to_thread(transcript_service.get_session_meta, session_id)
        if meta is None:
            return
        mem_cursor = meta["memory_extraction_cursor"]

        # Compaction runs first — only advances compaction_cursor.
        await self.compaction.compact_if_needed(session_id)

        if not allow_memory_write:
            return

        pending_messages = await asyncio.to_thread(
            transcript_service.get_recent_turns,
            session_id=session_id,
            max_turns=20,
            after_seq=mem_cursor,
        )
        if not pending_messages:
            return

        # If the session is bound to an interview_record, propagate the
        # source so audit log entries can be traced back to the record.
        record_id = await asyncio.to_thread(self._session_record_id, session_id)

        result = await realtime_extraction.extract_and_apply(
            session_id=session_id,
            user_id=user_id,
            new_messages=pending_messages,
            record_id=record_id,
        )

        # Advance the memory_extraction_cursor only on success
        # (None = LLM/dispatch hard failure → hold cursor, retry next
        # turn). A success with zero patches still advances — it just
        # means there were no strong signals to extract.
        if result is not None and result.error is None:
            max_seq = max(m["seq"] for m in pending_messages)
            await asyncio.to_thread(
                transcript_service.update_session_fields,
                session_id,
                memory_extraction_cursor=max_seq,
            )

    @staticmethod
    def _session_record_id(session_id: str) -> str | None:
        """Look up the interview_id this session belongs to (if any).
        Returns None for general / unbound sessions OR on any lookup
        failure — record_id is purely optional metadata for the audit
        log, so we must never let its lookup poison the extraction path.
        """
        from app.db.database import SessionLocal
        from app.models.chat import Conversation

        try:
            db = SessionLocal()
            try:
                row = (
                    db.query(Conversation.interview_id)
                    .filter(Conversation.id == session_id)
                    .first()
                )
                return row[0] if row and row[0] else None
            finally:
                db.close()
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "_session_record_id: lookup failed for %s: %s", session_id, exc,
            )
            return None


post_turn_maintenance_service = PostTurnMaintenanceService(
    compaction=compaction_service,
)


__all__ = ["PostTurnMaintenanceService", "post_turn_maintenance_service"]
