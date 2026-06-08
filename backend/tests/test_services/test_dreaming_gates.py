"""Path B autoDream gate tests.

Covers:
  * ``select_dreamable_users`` gate 1 (time)  — user fails when
    last_dreamed_at is too recent
  * ``select_dreamable_users`` gate 3 (volume) — passes via OR semantics
  * ``select_records_for_user``                — silent threshold
  * ``bump_user_last_dreamed_at``              — cursor moves forward
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture
def engine_and_session():
    from app.db.database import Base
    import app.models.chat            # noqa: F401
    import app.models.interview_record  # noqa: F401
    import app.models.user            # noqa: F401

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    try:
        yield engine, Session
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _rebind(monkeypatch, Session):
    import app.services.memory.dreaming_worker as dw
    monkeypatch.setattr(dw, "SessionLocal", Session, raising=False)


def _seed_user(Session, username: str, *, last_dreamed_at: datetime | None):
    from app.models.user import User
    db = Session()
    try:
        db.add(User(
            username=username, email=f"{username}@e.com", hashed_password="x",
            last_dreamed_at=last_dreamed_at,
        ))
        db.commit()
    finally:
        db.close()


def _seed_chat(Session, *, user_id: str, session_id: str, messages: int,
               session_created_at: datetime | None = None,
               message_created_at: datetime | None = None):
    from app.models.chat import ChatMessage, ChatSession
    db = Session()
    try:
        sess = ChatSession(
            id=session_id, user_id=user_id, title="t",
            session_type="debrief",
        )
        if session_created_at is not None:
            sess.created_at = session_created_at
        db.add(sess)
        for i in range(messages):
            m = ChatMessage(session_id=session_id, seq=i, role="User", content=f"m{i}")
            if message_created_at is not None:
                m.created_at = message_created_at
            db.add(m)
        db.commit()
    finally:
        db.close()


# ── Gate 1 (time) ─────────────────────────────────────────────────────


def test_gate1_filters_out_users_dreamed_recently(engine_and_session, monkeypatch):
    """A user dreamed within the last 24h must NOT be selected."""
    from app.services.memory.dreaming_worker import select_dreamable_users

    engine, Session = engine_and_session
    _rebind(monkeypatch, Session)

    now = datetime.utcnow()
    _seed_user(Session, "fresh_alice", last_dreamed_at=now - timedelta(hours=2))
    _seed_user(Session, "stale_bob",   last_dreamed_at=now - timedelta(hours=30))
    _seed_user(Session, "new_carol",   last_dreamed_at=None)

    # All three have enough activity to pass gate 3 on its own.
    for uid in ("fresh_alice", "stale_bob", "new_carol"):
        _seed_chat(
            Session, user_id=uid, session_id=f"s_{uid}", messages=60,
            session_created_at=now - timedelta(hours=12),
            message_created_at=now - timedelta(hours=12),
        )

    out = select_dreamable_users()
    assert "fresh_alice" not in out         # gate 1 fail
    assert "stale_bob" in out                # both pass
    assert "new_carol" in out                # NULL cursor → gate 1 trivially passes


# ── Gate 3 (volume) ───────────────────────────────────────────────────


def test_gate3_passes_via_message_count(engine_and_session, monkeypatch):
    from app.services.memory.dreaming_worker import (
        NEW_MESSAGES_THRESHOLD, select_dreamable_users,
    )

    engine, Session = engine_and_session
    _rebind(monkeypatch, Session)

    now = datetime.utcnow()
    _seed_user(Session, "alice", last_dreamed_at=None)
    _seed_chat(
        Session, user_id="alice", session_id="s1",
        messages=NEW_MESSAGES_THRESHOLD,   # exactly the threshold
        session_created_at=now - timedelta(hours=10),
        message_created_at=now - timedelta(hours=10),
    )
    out = select_dreamable_users()
    assert "alice" in out


def test_gate3_session_count_alone_does_not_trigger(engine_and_session, monkeypatch):
    """Gate 3 is messages-only now (``NEW_SESSIONS_THRESHOLD`` was dropped).
    A user with many new debrief SESSIONS but a message count far below
    ``NEW_MESSAGES_THRESHOLD`` must NOT be selected — a session with no real
    debrief turns produces no work for the dreamer."""
    from app.services.memory.dreaming_worker import (
        NEW_MESSAGES_THRESHOLD, select_dreamable_users,
    )

    engine, Session = engine_and_session
    _rebind(monkeypatch, Session)

    now = datetime.utcnow()
    _seed_user(Session, "alice", last_dreamed_at=None)
    # Many sessions, 1 message each → lots of sessions but total messages
    # ( = n_sessions ) stays well below NEW_MESSAGES_THRESHOLD. Pre-refactor
    # a session-count branch would have tripped the gate here; now it must
    # not. Keep n_sessions strictly < threshold so total messages < threshold.
    n_sessions = NEW_MESSAGES_THRESHOLD - 10
    for i in range(n_sessions):
        _seed_chat(
            Session, user_id="alice", session_id=f"s{i}",
            messages=1,
            session_created_at=now - timedelta(hours=10),
            message_created_at=now - timedelta(hours=10),
        )
    out = select_dreamable_users()
    assert "alice" not in out, (
        "session count alone must NOT trigger dreaming after the gate-3 "
        "messages-only refactor"
    )


def test_gate3_fails_when_below_message_threshold(engine_and_session, monkeypatch):
    from app.services.memory.dreaming_worker import select_dreamable_users

    engine, Session = engine_and_session
    _rebind(monkeypatch, Session)

    now = datetime.utcnow()
    _seed_user(Session, "alice", last_dreamed_at=None)
    _seed_chat(
        Session, user_id="alice", session_id="s1", messages=10,
        session_created_at=now - timedelta(hours=10),
        message_created_at=now - timedelta(hours=10),
    )
    out = select_dreamable_users()
    assert "alice" not in out


# ── Per-record silence gate ───────────────────────────────────────────


def test_record_quiet_threshold_excludes_active_record(engine_and_session, monkeypatch):
    """A record whose latest debrief message is < RECORD_QUIET_HOURS
    old must NOT be selected — they're 'currently being chatted'."""
    from app.models.chat import ChatMessage, ChatSession
    from app.models.interview_record import InterviewRecord
    from app.models.user import User
    from app.services.memory.dreaming_worker import (
        RECORD_QUIET_HOURS, select_records_for_user,
    )

    engine, Session = engine_and_session
    _rebind(monkeypatch, Session)

    # select_records_for_user resolves the username → users.id and filters
    # InterviewRecord.user_id on that integer pk (CLEANUP #2), so a real
    # ``users`` row must exist and the records must carry its pk.
    _seed_user(Session, "alice", last_dreamed_at=None)

    now = datetime.utcnow()
    db = Session()
    try:
        alice_pk = db.query(User.id).filter(User.username == "alice").scalar()
        db.add(InterviewRecord(
            id="ir_active", user_id=alice_pk, source="upload",
            status="completed", updated_at=now,
        ))
        db.add(InterviewRecord(
            id="ir_settled", user_id=alice_pk, source="upload",
            status="completed", updated_at=now,
        ))
        # Active record: most recent message is 30min old.
        db.add(ChatSession(
            id="s_active", user_id="alice", title="t",
            session_type="debrief", interview_id="ir_active",
        ))
        db.add(ChatMessage(
            session_id="s_active", seq=0, role="User", content="hi",
            created_at=now - timedelta(minutes=30),
        ))
        # Settled record: most recent message is (RECORD_QUIET_HOURS+1) old.
        db.add(ChatSession(
            id="s_settled", user_id="alice", title="t",
            session_type="debrief", interview_id="ir_settled",
        ))
        db.add(ChatMessage(
            session_id="s_settled", seq=0, role="User", content="hi",
            created_at=now - timedelta(hours=RECORD_QUIET_HOURS + 1),
        ))
        db.commit()
    finally:
        db.close()

    out = select_records_for_user("alice")
    ids = {r.id for r in out}
    assert "ir_active" not in ids
    assert "ir_settled" in ids


# ── Cursor bump ───────────────────────────────────────────────────────


def test_bump_user_last_dreamed_at_moves_cursor(engine_and_session, monkeypatch):
    from app.models.user import User
    from app.services.memory.dreaming_worker import bump_user_last_dreamed_at

    engine, Session = engine_and_session
    _rebind(monkeypatch, Session)

    _seed_user(Session, "alice", last_dreamed_at=None)
    before = datetime.utcnow()
    bump_user_last_dreamed_at("alice")

    db = Session()
    try:
        u = db.query(User).filter(User.username == "alice").first()
        assert u.last_dreamed_at is not None
        assert u.last_dreamed_at >= before
    finally:
        db.close()
