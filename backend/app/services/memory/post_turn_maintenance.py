"""Post-turn maintenance service — runs in the background after each turn.

Order of operations:
  1. Enqueue a persistent ``extract_memory_realtime`` outbox job for the new
     messages. The JOB (not this service) runs the LLM extraction, writes the
     ability states / user_profile / learning_strategy, and advances the
     ``memory_extraction_cursor`` on success — see ``extraction_jobs``.

Conversation compaction is no longer triggered here — it moved to assembly
time (``ContextAssemblyPipeline._maybe_compact``) so the context is
compressed before the LLM call, matching the Claude Code model.

The session-level asyncio lock here prevents two overlapping turns on the same
session from enqueuing duplicate work (cheap, in-process). The per-user Redis
lock that serializes extraction against the dreaming worker is held by the job
itself, not by this service.
"""

import asyncio
import logging

from app.services.chat.chat_history_service import transcript_service
from app.services.memory import extraction_jobs

logger = logging.getLogger(__name__)


class PostTurnMaintenanceService:
    """Runs after each conversation turn as a background task.

    Responsibility: enqueue the realtime memory-extraction job for the
    new messages (the job does the extraction — see ``extraction_jobs`` /
    ``realtime_extraction``).
    """

    def __init__(self) -> None:
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
        if not allow_memory_write:
            return

        meta = await asyncio.to_thread(transcript_service.get_session_meta, session_id)
        if meta is None:
            return
        mem_cursor = meta["memory_extraction_cursor"]

        pending_messages = await asyncio.to_thread(
            transcript_service.get_recent_turns,
            session_id=session_id,
            max_turns=20,
            after_seq=mem_cursor,
        )
        if not pending_messages:
            return

        record_id = await asyncio.to_thread(self._session_record_id, session_id)
        upto_seq = max(m["seq"] for m in pending_messages)

        await asyncio.to_thread(
            extraction_jobs.enqueue_realtime_extraction,
            session_id=session_id,
            user_id=user_id,
            record_id=record_id,
            upto_seq=upto_seq,
        )

    @staticmethod
    def _session_record_id(session_id: str) -> str | None:
        """Look up the bound interview_record id (conversations.subject_id)
        this session belongs to (if any).
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
                    db.query(Conversation.subject_id)
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


post_turn_maintenance_service = PostTurnMaintenanceService()


__all__ = ["PostTurnMaintenanceService", "post_turn_maintenance_service"]
