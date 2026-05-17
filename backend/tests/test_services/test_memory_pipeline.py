"""Tests for app.services.memory.*

Covers:
  - extract_and_merge: dedup via normalized_key, vector upsert
  - retrieval recall_relevant: user_id scoping + lexical fusion
  - post_turn_maintenance: cursor independence + advance-on-success semantics

The two DB-touching tests use a local SQLite fixture because the shared
conftest db_session fixture is broken (imports a removed
``app.models.interview`` module).
"""
import asyncio
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture
def memory_db_session():
    import app.models.memory  # noqa: F401 — register MemoryItem on Base
    from app.db.database import Base

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine, tables=[Base.metadata.tables["memory_items"]])
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


class _NoCloseSession:
    """Forward attribute access to a real session but suppress close()."""

    def __init__(self, inner):
        self._inner = inner

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def close(self):
        # Flush — leave the underlying session alive for the next call.
        try:
            self._inner.commit()
        except Exception:
            self._inner.rollback()


def test_memory_merge_uses_normalized_key(monkeypatch, memory_db_session):
    """Two extractions with the same normalized_key should produce one row.

    Post-0019: user_profile lives in a separate single-doc storage and the
    multi-row dedup path is exclusively for ``interview_fact``. Test data
    accordingly. The user_profile branch is stubbed to a no-op so the
    test sqlite (which has no ``users`` table) doesn't get touched.
    """
    from app.models.memory import MemoryItem
    from app.services.memory import extraction_service as module

    class FakeResponse:
        def __init__(self, text: str):
            self.text = text

    class FakeLLM:
        async def acomplete(self, *args, **kwargs):
            return FakeResponse(
                json.dumps([
                    {
                        "type": "interview_fact",
                        "description": "Redis persistence question",
                        "normalized_key": "ivf_redis_persistence",
                        "content": "Discussed AOF vs RDB; hybrid is preferred.",
                        "confidence": 0.92,
                    }
                ])
            )

    monkeypatch.setattr(module, "SessionLocal", lambda: _NoCloseSession(memory_db_session))
    monkeypatch.setattr(module, "agent_fast_llm", FakeLLM())
    monkeypatch.setattr(module, "load_profile_doc", lambda user_id: "")
    monkeypatch.setattr(module, "apply_profile_patches", lambda *a, **kw: {"applied": 0, "dropped": 0, "skipped": 0})
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

    rows = memory_db_session.query(MemoryItem).all()
    assert len(rows) == 1
    assert rows[0].normalized_key == "ivf_redis_persistence"
    assert first[0]["normalized_key"] == second[0]["normalized_key"]


def test_memory_retrieval_uses_user_scope(monkeypatch, memory_db_session):
    """recall_relevant must only return memories belonging to the caller."""
    from app.models.memory import MemoryItem
    from app.services.memory import retrieval_service as module

    memory_db_session.add(
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
    memory_db_session.add(
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
    memory_db_session.commit()

    monkeypatch.setattr(module, "SessionLocal", lambda: _NoCloseSession(memory_db_session))

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

    # Only alice's memory is returned — bob's is filtered out.
    returned_ids = [item["id"] for item in result]
    assert "mem_alice" in returned_ids
    assert "mem_bob" not in returned_ids


# ── post_turn_maintenance ────────────────────────────────────────────────
# These tests don't touch the DB; they fake the transcript service entirely.


def test_post_turn_maintenance_does_not_advance_cursor_on_failed_extraction(monkeypatch):
    from app.services.memory import post_turn_maintenance as module

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

    class FakeMemoryExtraction:
        async def extract_and_merge(self, session_id, user_id, new_messages):
            return None  # signal failure

    service = module.PostTurnMaintenanceService(
        compaction=FakeCompaction(),
        memory_extraction=FakeMemoryExtraction(),
    )
    monkeypatch.setattr(module, "transcript_service", FakeTranscriptService())
    asyncio.run(service.run("s1", "alice"))

    # Failure → cursor must NOT advance (retry next turn)
    assert updates == []


def test_memory_extraction_cursor_independent_of_compaction(monkeypatch):
    """compaction_cursor advancement must not skip memory extraction."""
    from app.services.memory import post_turn_maintenance as module

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

    class FakeMemoryExtraction:
        async def extract_and_merge(self, session_id, user_id, new_messages):
            extracted_seqs.extend(m["seq"] for m in new_messages)
            return [{"type": "user_profile", "description": "test"}]

    service = module.PostTurnMaintenanceService(
        compaction=FakeCompaction(),
        memory_extraction=FakeMemoryExtraction(),
    )
    monkeypatch.setattr(module, "transcript_service", FakeTranscriptService())
    asyncio.run(service.run("s1", "alice"))

    assert extracted_seqs == [6, 7, 20, 21]
    assert updates == [{"memory_extraction_cursor": 21}]


def test_memory_extraction_cursor_advances_on_success(monkeypatch):
    from app.services.memory import post_turn_maintenance as module

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

    class FakeMemoryExtraction:
        async def extract_and_merge(self, session_id, user_id, new_messages):
            return [{"type": "interview_fact", "description": "redis"}]

    service = module.PostTurnMaintenanceService(
        compaction=FakeCompaction(),
        memory_extraction=FakeMemoryExtraction(),
    )
    monkeypatch.setattr(module, "transcript_service", FakeTranscriptService())
    asyncio.run(service.run("s1", "alice"))

    assert updates == [{"memory_extraction_cursor": 4}]
