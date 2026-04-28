import asyncio
import json


def test_memory_merge_uses_normalized_key(monkeypatch, db_session):
    from app.models.memory import MemoryItem
    from app.services import memory_extraction_service as module

    class FakeResponse:
        def __init__(self, text: str):
            self.text = text

    class FakeLLM:
        async def acomplete(self, *args, **kwargs):
            return FakeResponse(
                json.dumps(
                    [
                        {
                            "type": "interaction_preference",
                            "description": "Prefer concise answers",
                            "normalized_key": "concise_answers",
                            "content": "User prefers concise answers.",
                            "confidence": 0.92,
                        }
                    ]
                )
            )

    monkeypatch.setattr(module, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(module, "agent_fast_llm", FakeLLM())

    service = module.MemoryExtractionService()
    first = asyncio.run(
        service.extract_and_merge(
            session_id="s1",
            user_id="alice",
            new_messages=[{"seq": 1, "role": "User", "content": "Please keep it concise."}],
        )
    )
    second = asyncio.run(
        service.extract_and_merge(
            session_id="s1",
            user_id="alice",
            new_messages=[{"seq": 2, "role": "User", "content": "Short answers are better."}],
        )
    )

    rows = db_session.query(MemoryItem).all()
    assert len(rows) == 1
    assert rows[0].normalized_key == "concise_answers"
    assert first[0]["normalized_key"] == second[0]["normalized_key"]


def test_post_turn_maintenance_does_not_advance_cursor_on_failed_extraction(monkeypatch):
    from app.services import memory_extraction_service as module

    updates = []

    class FakeTranscriptService:
        def get_session_meta(self, session_id):
            return {
                "memory_cursor": 2,
                "compaction_cursor": 0,
                "working_state": "{}",
                "turn_count": 1,
            }

        def get_recent_turns(self, session_id, max_turns, after_seq):
            return [{"seq": 3, "role": "User", "content": "hello"}]

        def update_session_fields(self, session_id, **kwargs):
            updates.append(kwargs)

    class FakeCompaction:
        async def compact_if_needed(self, session_id):
            return False

    class FakeInterviewUpdates:
        async def update_from_messages(self, session_id, user_id, new_messages):
            return {}

    class FakeMemoryExtraction:
        async def extract_and_merge(self, session_id, user_id, new_messages):
            return None

    service = module.PostTurnMaintenanceService(
        compaction=FakeCompaction(),
        interview_updates=FakeInterviewUpdates(),
        memory_extraction=FakeMemoryExtraction(),
    )

    monkeypatch.setattr(module, "transcript_service", FakeTranscriptService())
    asyncio.run(service.run("s1", "alice"))

    assert updates == []
