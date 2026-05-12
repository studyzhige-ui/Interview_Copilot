"""Post-turn maintenance service — runs in the background after each turn.

Order of operations:
  1. Compact session_state via dual-threshold trigger (token growth + turns)
  2. Extract user_profile / interview_fact memories from new messages
"""

import asyncio

from app.services.chat.chat_history_service import transcript_service
from app.services.memory.compaction_service import (
    CompactionService,
    compaction_service,
)
from app.services.memory.extraction_service import (
    MemoryExtractionService,
    memory_extraction_service,
)


class PostTurnMaintenanceService:
    """Runs after each conversation turn as a background task.

    Responsibilities (in order):
    1. Compact session_state via dual-threshold trigger (token growth + turns)
    2. Extract user_profile memories from new messages
    """

    def __init__(
        self,
        compaction: CompactionService,
        memory_extraction: MemoryExtractionService,
    ):
        self.compaction = compaction
        self.memory_extraction = memory_extraction
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
        meta = transcript_service.get_session_meta(session_id)
        if meta is None:
            return
        mem_cursor = meta["memory_extraction_cursor"]

        # Compaction runs first — only advances compaction_cursor
        await self.compaction.compact_if_needed(session_id)

        if not allow_memory_write:
            return

        # Long-term memory extraction uses its own independent cursor
        pending_messages = transcript_service.get_recent_turns(
            session_id=session_id,
            max_turns=20,
            after_seq=mem_cursor,
        )
        if not pending_messages:
            return

        result = await self.memory_extraction.extract_and_merge(
            session_id=session_id,
            user_id=user_id,
            new_messages=pending_messages,
        )

        # Advance memory_extraction_cursor only on success (failure → retry next turn)
        if result is not None:
            max_seq = max(m["seq"] for m in pending_messages)
            transcript_service.update_session_fields(
                session_id,
                memory_extraction_cursor=max_seq,
            )


post_turn_maintenance_service = PostTurnMaintenanceService(
    compaction=compaction_service,
    memory_extraction=memory_extraction_service,
)


__all__ = ["PostTurnMaintenanceService", "post_turn_maintenance_service"]
