"""Tests for the MEMORY-V3 extraction-job flow.

Realtime extraction is no longer inline: ``post_turn_maintenance`` enqueues a
persistent ``extract_memory_realtime`` outbox job, and the job core
(``realtime_extraction.run_realtime_extraction``) does the LLM call + dispatch +
cursor advance atomically, advancing the cursor ONLY on success and short-
circuiting a superseded/retried job. These tests pin:

  * post_turn enqueues (with the right upto_seq) and does NOT advance the cursor
  * the core advances the cursor on success, holds it on failure (raise), and
    is an idempotent no-op when a later job already passed the range
  * the dreaming enqueue guard avoids piling up duplicate jobs per record
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base
import app.models  # noqa: F401  — register mappers


def _fake_llm(acomplete):
    """A stand-in for the catalog-backed ``agent_fast_llm`` proxy (which resolves
    a model on attribute access, raising when the test catalog is empty)."""
    llm = MagicMock()
    llm.acomplete = acomplete
    return llm


# ── post_turn now ENQUEUES a job (no inline extract / cursor advance) ────


def test_post_turn_enqueues_realtime_job(monkeypatch):
    from app.services.memory import post_turn_maintenance as module

    calls: list[dict] = []
    updates: list[dict] = []

    class FakeTranscriptService:
        def get_session_meta(self, session_id):
            return {
                "compaction_cursor": 20,
                "memory_extraction_cursor": 5,
                "type": "general",
                "turn_count": 10,
            }

        def get_recent_turns(self, session_id, max_turns, after_seq):
            assert after_seq == 5  # extraction is independent of compaction
            return [
                {"seq": 6, "role": "User", "content": "q"},
                {"seq": 21, "role": "Agent", "content": "a"},
            ]

        def update_session_fields(self, session_id, **kwargs):
            updates.append(kwargs)

    class FakeCompaction:
        async def compact_if_needed(self, session_id):
            return False

    def fake_enqueue(*, session_id, user_id, record_id, upto_seq):
        calls.append({"session_id": session_id, "user_id": user_id, "upto_seq": upto_seq})

    service = module.PostTurnMaintenanceService(compaction=FakeCompaction())
    monkeypatch.setattr(module, "transcript_service", FakeTranscriptService())
    monkeypatch.setattr(module.extraction_jobs, "enqueue_realtime_extraction", fake_enqueue)
    asyncio.run(service.run("s1", "alice"))

    # Enqueued for the full pending range; cursor NOT advanced here (the job does).
    assert calls == [{"session_id": "s1", "user_id": "alice", "upto_seq": 21}]
    assert updates == []


def test_post_turn_no_job_when_no_pending(monkeypatch):
    from app.services.memory import post_turn_maintenance as module

    calls: list = []

    class FakeTranscriptService:
        def get_session_meta(self, session_id):
            return {"compaction_cursor": 0, "memory_extraction_cursor": 0,
                    "type": "general", "turn_count": 0}

        def get_recent_turns(self, session_id, max_turns, after_seq):
            return []

        def update_session_fields(self, session_id, **kwargs):
            pass

    class FakeCompaction:
        async def compact_if_needed(self, session_id):
            return False

    service = module.PostTurnMaintenanceService(compaction=FakeCompaction())
    monkeypatch.setattr(module, "transcript_service", FakeTranscriptService())
    monkeypatch.setattr(
        module.extraction_jobs, "enqueue_realtime_extraction",
        lambda **k: calls.append(k),
    )
    asyncio.run(service.run("s1", "alice"))
    assert calls == []


def test_post_turn_no_job_when_memory_disabled(monkeypatch):
    from app.services.memory import post_turn_maintenance as module

    calls: list = []

    class FakeTranscriptService:
        def get_session_meta(self, session_id):
            return {"compaction_cursor": 0, "memory_extraction_cursor": 0,
                    "type": "general", "turn_count": 1}

        def get_recent_turns(self, session_id, max_turns, after_seq):
            return [{"seq": 1, "role": "User", "content": "q"}]

        def update_session_fields(self, session_id, **kwargs):
            pass

    class FakeCompaction:
        async def compact_if_needed(self, session_id):
            return False

    service = module.PostTurnMaintenanceService(compaction=FakeCompaction())
    monkeypatch.setattr(module, "transcript_service", FakeTranscriptService())
    monkeypatch.setattr(
        module.extraction_jobs, "enqueue_realtime_extraction",
        lambda **k: calls.append(k),
    )
    asyncio.run(service.run("s1", "alice", allow_memory_write=False))
    assert calls == []


# ── run_realtime_extraction core (own session, atomic cursor) ────────────


@pytest.fixture
def mem_maker(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Maker = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    from app.services.memory import realtime_extraction as rt
    monkeypatch.setattr(rt, "SessionLocal", Maker)
    return Maker


def _seed_conv(Maker, *, cursor: int):
    from app.models.chat import Conversation
    from app.models.user import User

    db = Maker()
    try:
        u = User(username="alice", hashed_password="x")
        db.add(u)
        db.flush()
        db.add(Conversation(
            id="s1", user_id=u.id, title="t", type="general",
            memory_extraction_cursor=cursor,
        ))
        db.commit()
    finally:
        db.close()


def _cursor(Maker) -> int:
    from app.models.chat import Conversation
    db = Maker()
    try:
        return db.query(Conversation).filter(Conversation.id == "s1").first().memory_extraction_cursor
    finally:
        db.close()


def _resp(text):
    from unittest.mock import MagicMock
    r = MagicMock()
    r.text = text
    return r


def test_realtime_superseded_is_noop(mem_maker, monkeypatch):
    """If the cursor already passed upto_seq (a later job ran first), the pass
    is a no-op: no LLM call, cursor untouched."""
    from app.services.memory import realtime_extraction as rt

    _seed_conv(mem_maker, cursor=10)
    acomplete = AsyncMock(return_value=_resp("[]"))
    monkeypatch.setattr(rt, "agent_fast_llm", _fake_llm(acomplete))

    res = rt.run_realtime_extraction(session_id="s1", user_id="alice", record_id=None, upto_seq=8)
    assert res.skipped_reason == "superseded"
    assert acomplete.await_count == 0  # short-circuited before the LLM
    assert _cursor(mem_maker) == 10    # unchanged


def test_realtime_success_advances_cursor(mem_maker, monkeypatch):
    """A successful pass (here: 0 patches) advances the cursor to upto_seq."""
    from app.services.chat import chat_history_service
    from app.services.memory import realtime_extraction as rt

    _seed_conv(mem_maker, cursor=0)
    monkeypatch.setattr(
        chat_history_service.transcript_service, "get_messages_in_range",
        lambda session_id, start, end: [{"seq": 1, "role": "user", "content": "我懂了"}],
    )
    # no strong signals → 0 patches, still a success
    monkeypatch.setattr(rt, "agent_fast_llm", _fake_llm(AsyncMock(return_value=_resp("[]"))))

    res = rt.run_realtime_extraction(session_id="s1", user_id="alice", record_id=None, upto_seq=3)
    assert res.advanced_to == 3
    assert _cursor(mem_maker) == 3


def test_realtime_failure_holds_cursor(mem_maker, monkeypatch):
    """An LLM failure raises (so the outbox retries) and leaves the cursor put."""
    from app.services.chat import chat_history_service
    from app.services.memory import realtime_extraction as rt

    _seed_conv(mem_maker, cursor=0)
    monkeypatch.setattr(
        chat_history_service.transcript_service, "get_messages_in_range",
        lambda session_id, start, end: [{"seq": 1, "role": "user", "content": "x"}],
    )
    monkeypatch.setattr(
        rt, "agent_fast_llm", _fake_llm(AsyncMock(side_effect=RuntimeError("llm down"))),
    )

    with pytest.raises(RuntimeError):
        rt.run_realtime_extraction(session_id="s1", user_id="alice", record_id=None, upto_seq=3)
    assert _cursor(mem_maker) == 0  # held → retried later


# ── dreaming enqueue guard ───────────────────────────────────────────────


def test_enqueue_dreaming_skips_when_in_flight(mem_maker):
    """A second dreaming enqueue for the same record while one is in flight is
    a no-op (avoids piling up duplicate no-op jobs within a scan)."""
    from app.models.outbox_job import OutboxJob
    from app.models.user import User
    from app.services.memory import extraction_jobs

    db = mem_maker()
    try:
        u = User(username="alice", hashed_password="x")
        db.add(u)
        db.flush()
        first = extraction_jobs.enqueue_dreaming(db, user_pk=u.id, record_id="ir_1")
        db.commit()
        assert first is not None
        second = extraction_jobs.enqueue_dreaming(db, user_pk=u.id, record_id="ir_1")
        db.commit()
        assert second is None
        count = db.query(OutboxJob).filter(
            OutboxJob.job_type == "extract_memory_dreaming",
            OutboxJob.aggregate_id == "ir_1",
        ).count()
        assert count == 1
    finally:
        db.close()
