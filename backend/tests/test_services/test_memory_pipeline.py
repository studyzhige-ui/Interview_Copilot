"""Tests for post_turn_maintenance cursor semantics.

The v2 ``extract_and_merge`` / ``recall_relevant`` tests against the
legacy ``memory_items`` table were removed in the v3 cleanup — that
storage is retired. The post_turn_maintenance behaviour (cursor
advancement on success, cursor hold on hard failure, independence
from compaction cursor) is still meaningful because it gates whether
realtime_extraction sees the same messages twice.

Each test fakes:
  * ``transcript_service`` for the cursor + message reads
  * ``realtime_extraction.extract_and_apply`` for the actual extraction
"""
import asyncio


def test_post_turn_maintenance_does_not_advance_cursor_on_failed_extraction(monkeypatch):
    """When realtime_extraction returns None (LLM/dispatch hard failure),
    the cursor must hold so the next turn retries the same messages."""
    from app.services.memory import post_turn_maintenance as module
    from app.services.memory import realtime_extraction

    updates = []

    class FakeTranscriptService:
        def get_session_meta(self, session_id):
            return {
                "compaction_cursor": 0,
                "memory_extraction_cursor": 0,
                "session_state": "{}",
                "session_type": "general",
                "turn_count": 1,
            }

        def get_recent_turns(self, session_id, max_turns, after_seq):
            return [{"seq": 3, "role": "User", "content": "hello"}]

        def update_session_fields(self, session_id, **kwargs):
            updates.append(kwargs)

    class FakeCompaction:
        async def compact_if_needed(self, session_id):
            return False

    async def fake_extract(**kwargs):
        return None  # signal failure

    service = module.PostTurnMaintenanceService(compaction=FakeCompaction())
    monkeypatch.setattr(module, "transcript_service", FakeTranscriptService())
    monkeypatch.setattr(realtime_extraction, "extract_and_apply", fake_extract)
    monkeypatch.setattr(module.realtime_extraction, "extract_and_apply", fake_extract)
    asyncio.run(service.run("s1", "alice"))

    # Failure → cursor must NOT advance (retry next turn)
    assert updates == []


def test_memory_extraction_cursor_independent_of_compaction(monkeypatch):
    """compaction_cursor advancement must not skip memory extraction
    of older-than-compaction messages."""
    from app.services.memory import post_turn_maintenance as module
    from app.services.memory import realtime_extraction

    updates = []
    extracted_seqs = []

    class FakeTranscriptService:
        def get_session_meta(self, session_id):
            return {
                "compaction_cursor": 20,
                "memory_extraction_cursor": 5,
                "session_state": "{}",
                "session_type": "general",
                "turn_count": 10,
            }

        def get_recent_turns(self, session_id, max_turns, after_seq):
            if after_seq == 5:
                return [
                    {"seq": 6, "role": "User", "content": "q1"},
                    {"seq": 7, "role": "Agent", "content": "a1"},
                    {"seq": 20, "role": "User", "content": "q10"},
                    {"seq": 21, "role": "Agent", "content": "a10"},
                ]
            return []

        def update_session_fields(self, session_id, **kwargs):
            updates.append(kwargs)

    class FakeCompaction:
        async def compact_if_needed(self, session_id):
            return False

    async def fake_extract(*, session_id, user_id, new_messages, record_id=None):
        extracted_seqs.extend(m["seq"] for m in new_messages)
        return realtime_extraction.ExtractionResult(applied=1)

    service = module.PostTurnMaintenanceService(compaction=FakeCompaction())
    monkeypatch.setattr(module, "transcript_service", FakeTranscriptService())
    monkeypatch.setattr(module.realtime_extraction, "extract_and_apply", fake_extract)
    asyncio.run(service.run("s1", "alice"))

    assert extracted_seqs == [6, 7, 20, 21]
    assert updates == [{"memory_extraction_cursor": 21}]


def test_memory_extraction_cursor_advances_on_success(monkeypatch):
    """A successful extraction (even with 0 patches applied) advances
    the cursor — we shouldn't re-process the same messages forever."""
    from app.services.memory import post_turn_maintenance as module
    from app.services.memory import realtime_extraction

    updates = []

    class FakeTranscriptService:
        def get_session_meta(self, session_id):
            return {
                "compaction_cursor": 0,
                "memory_extraction_cursor": 0,
                "session_state": "{}",
                "session_type": "general",
                "turn_count": 2,
            }

        def get_recent_turns(self, session_id, max_turns, after_seq):
            return [
                {"seq": 1, "role": "User", "content": "hello"},
                {"seq": 2, "role": "Agent", "content": "hi"},
                {"seq": 3, "role": "User", "content": "tell me about redis"},
                {"seq": 4, "role": "Agent", "content": "Redis is..."},
            ]

        def update_session_fields(self, session_id, **kwargs):
            updates.append(kwargs)

    class FakeCompaction:
        async def compact_if_needed(self, session_id):
            return False

    async def fake_extract(*, session_id, user_id, new_messages, record_id=None):
        return realtime_extraction.ExtractionResult(applied=1)

    service = module.PostTurnMaintenanceService(compaction=FakeCompaction())
    monkeypatch.setattr(module, "transcript_service", FakeTranscriptService())
    monkeypatch.setattr(module.realtime_extraction, "extract_and_apply", fake_extract)
    asyncio.run(service.run("s1", "alice"))

    assert updates == [{"memory_extraction_cursor": 4}]
