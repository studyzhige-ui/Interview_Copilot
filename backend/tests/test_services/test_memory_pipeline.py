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
                            "type": "user_profile",
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
    monkeypatch.setattr(
        module.memory_vector_service,
        "upsert_memory",
        lambda *args, **kwargs: True,
    )

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


def test_memory_retrieval_uses_user_scope_and_lexical_fusion(monkeypatch, db_session):
    from app.models.memory import MemoryItem
    from app.services import memory_extraction_service as module

    db_session.add(
        MemoryItem(
            id="mem_alice",
            user_id="alice",
            type="user_profile",
            description="Chinese answers",
            normalized_key="chinese_answers",
            content="User prefers Chinese answers with English terms explained.",
            importance=0.9,
        )
    )
    db_session.add(
        MemoryItem(
            id="mem_bob",
            user_id="bob",
            type="user_profile",
            description="Chinese answers",
            normalized_key="chinese_answers",
            content="Bob prefers Chinese answers.",
            importance=0.9,
        )
    )
    db_session.commit()

    monkeypatch.setattr(module, "SessionLocal", lambda: db_session)

    async def fake_vector(**kwargs):
        return []

    monkeypatch.setattr(module.memory_vector_service, "retrieve_vector", fake_vector)
    service = module.MemoryRetrievalService()

    result = asyncio.run(
        service.recall_relevant(
            user_id="alice",
            query="Chinese answers English terms",
            memory_types=["user_profile"],
        )
    )

    assert [item["id"] for item in result] == ["mem_alice"]


def test_post_turn_maintenance_does_not_advance_cursor_on_failed_extraction(monkeypatch):
    from app.services import memory_extraction_service as module

    updates = []

    class FakeTranscriptService:
        def get_session_meta(self, session_id):
            return {
                "compaction_cursor": 0,
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

    class FakeMemoryExtraction:
        async def extract_and_merge(self, session_id, user_id, new_messages):
            return None

    service = module.PostTurnMaintenanceService(
        compaction=FakeCompaction(),
        memory_extraction=FakeMemoryExtraction(),
    )

    monkeypatch.setattr(module, "transcript_service", FakeTranscriptService())
    asyncio.run(service.run("s1", "alice"))

    assert updates == []
