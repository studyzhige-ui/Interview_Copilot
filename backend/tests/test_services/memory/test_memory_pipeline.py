"""Tests for the MEMORY-V3 extraction-job flow.

Realtime extraction is no longer inline: turn persistence enqueues a
persistent ``extract_memory_realtime`` outbox job in the same transaction, and the job core
(``realtime_extraction.run_realtime_extraction``) does the LLM call + dispatch +
cursor advance atomically, advancing the cursor ONLY on success and short-
circuiting a superseded/retried job. These tests pin:

  * the core advances the cursor on success, holds it on failure (raise), and
    is an idempotent no-op when a later job already passed the range
  * the dreaming enqueue guard avoids piling up duplicate jobs per record
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base
import app.models  # noqa: F401  — register mappers


def _fake_llm(acomplete):
    """A stand-in for the platform-owned worker LLM (which resolves
    a model on attribute access, raising when the test catalog is empty)."""
    llm = MagicMock()
    llm.acomplete = acomplete
    return llm


# ── run_realtime_extraction core (own session, atomic cursor) ────────────


@pytest.fixture
def mem_maker(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
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
        db.add(
            Conversation(
                id="s1",
                user_id=u.id,
                title="t",
                type="general",
                memory_extraction_cursor=cursor,
            )
        )
        db.commit()
    finally:
        db.close()


def _cursor(Maker) -> int:
    from app.models.chat import Conversation

    db = Maker()
    try:
        return (
            db.query(Conversation)
            .filter(Conversation.id == "s1")
            .first()
            .memory_extraction_cursor
        )
    finally:
        db.close()


def _resp(text):
    from unittest.mock import MagicMock

    r = MagicMock()
    r.text = text
    return r


@pytest.fixture(autouse=True)
def _no_lock(monkeypatch):
    """These tests exercise extraction logic, not locking. The raise-mode
    lock (MEM-6) would abort on a missing local Redis — stub it out."""
    import contextlib

    from app.services.memory import realtime_extraction as rt

    @contextlib.contextmanager
    def _noop(user_id, **kwargs):
        yield

    monkeypatch.setattr(rt, "user_memory_lock_sync", _noop)


def test_realtime_superseded_is_noop(mem_maker, monkeypatch):
    """If the cursor already passed upto_seq (a later job ran first), the pass
    is a no-op: no LLM call, cursor untouched."""
    from app.services.memory import realtime_extraction as rt

    _seed_conv(mem_maker, cursor=10)
    acomplete = AsyncMock(return_value=_resp("[]"))
    monkeypatch.setattr(rt, "get_internal_llm", lambda role: _fake_llm(acomplete))

    res = rt.run_realtime_extraction(
        session_id="s1", user_id="alice", record_id=None, upto_seq=8
    )
    assert res.skipped_reason == "superseded"
    assert acomplete.await_count == 0  # short-circuited before the LLM
    assert _cursor(mem_maker) == 10  # unchanged


def test_realtime_success_advances_cursor(mem_maker, monkeypatch):
    """A successful pass (here: 0 patches) advances the cursor to upto_seq."""
    from app.services.chat import chat_history_service
    from app.services.memory import realtime_extraction as rt

    _seed_conv(mem_maker, cursor=0)
    monkeypatch.setattr(
        chat_history_service.transcript_service,
        "get_messages_in_range",
        lambda session_id, start, end: [
            {"seq": 1, "role": "user", "content": "我懂了"}
        ],
    )
    # no strong signals → 0 patches, still a success
    monkeypatch.setattr(
        rt,
        "get_internal_llm",
        lambda role: _fake_llm(AsyncMock(return_value=_resp("[]"))),
    )

    res = rt.run_realtime_extraction(
        session_id="s1", user_id="alice", record_id=None, upto_seq=3
    )
    assert res.advanced_to == 3
    assert _cursor(mem_maker) == 3


def test_realtime_failure_holds_cursor(mem_maker, monkeypatch):
    """An LLM failure raises (so the outbox retries) and leaves the cursor put."""
    from app.services.chat import chat_history_service
    from app.services.memory import realtime_extraction as rt

    _seed_conv(mem_maker, cursor=0)
    monkeypatch.setattr(
        chat_history_service.transcript_service,
        "get_messages_in_range",
        lambda session_id, start, end: [{"seq": 1, "role": "user", "content": "x"}],
    )
    monkeypatch.setattr(
        rt,
        "get_internal_llm",
        lambda role: _fake_llm(AsyncMock(side_effect=RuntimeError("llm down"))),
    )

    with pytest.raises(RuntimeError):
        rt.run_realtime_extraction(
            session_id="s1", user_id="alice", record_id=None, upto_seq=3
        )
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
        count = (
            db.query(OutboxJob)
            .filter(
                OutboxJob.job_type == "extract_memory_dreaming",
                OutboxJob.aggregate_id == "ir_1",
            )
            .count()
        )
        assert count == 1
    finally:
        db.close()
