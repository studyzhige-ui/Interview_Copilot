"""Unit tests for the global-memory toggle policy.

Stage-H renamed the toggle from ``memory_recall_default`` /
``memory_recall_enabled`` to ``global_memory_enabled``. In-flight
session_state JSON rows still carry the legacy key — these tests pin
the back-compat read shim so a future "the new key is canonical, who
needs the old one" cleanup doesn't silently break those sessions.
"""
from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture
def engine_and_session():
    """In-memory SQLite engine with users + chat_sessions tables."""
    from app.db.database import Base
    import app.models.chat   # noqa: F401
    import app.models.user   # noqa: F401

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
    """Make the policy module use our in-memory Session."""
    import app.services.memory.recall_policy as recall_mod
    monkeypatch.setattr(recall_mod, "SessionLocal", Session, raising=False)


def _seed(Session, *, username="alice", user_default=False, session_state=None):
    from app.models.chat import ChatSession
    from app.models.user import User
    db = Session()
    try:
        db.add(User(
            username=username,
            email=f"{username}@e.com",
            hashed_password="x",
            global_memory_enabled=user_default,
        ))
        db.add(ChatSession(
            id="s1",
            user_id=username,
            session_state=(
                json.dumps(session_state) if session_state is not None else "{}"
            ),
        ))
        db.commit()
    finally:
        db.close()


def test_legacy_session_state_key_is_honoured(engine_and_session, monkeypatch):
    """A pre-Stage-H session that stored ``memory_recall_enabled`` in
    its session_state JSON must still return that value — Stage-H
    promised an opt-in back-compat shim, this test pins it."""
    from app.services.memory.recall_policy import (
        is_global_memory_enabled_for_session,
    )

    engine, Session = engine_and_session
    _rebind(monkeypatch, Session)
    _seed(
        Session,
        user_default=False,                            # user-level says OFF
        session_state={"memory_recall_enabled": True}, # legacy override says ON
    )

    # Session-level override wins, and the legacy key MUST still be
    # read — otherwise the user's per-session "memory on" choice
    # silently regresses after the upgrade.
    assert is_global_memory_enabled_for_session("s1", "alice") is True


def test_new_key_takes_precedence_over_legacy(engine_and_session, monkeypatch):
    """When both keys are present (mid-migration edge case) the
    canonical ``global_memory_enabled`` wins."""
    from app.services.memory.recall_policy import (
        is_global_memory_enabled_for_session,
    )

    engine, Session = engine_and_session
    _rebind(monkeypatch, Session)
    _seed(
        Session,
        user_default=False,
        session_state={
            "global_memory_enabled": False,   # canonical
            "memory_recall_enabled": True,    # stale legacy
        },
    )

    # Canonical key wins; legacy is ignored when both are present.
    assert is_global_memory_enabled_for_session("s1", "alice") is False


def test_user_default_used_when_session_has_no_override(engine_and_session, monkeypatch):
    """Falls through to ``users.global_memory_enabled`` when neither
    JSON key is present."""
    from app.services.memory.recall_policy import (
        is_global_memory_enabled_for_session,
    )

    engine, Session = engine_and_session
    _rebind(monkeypatch, Session)
    _seed(
        Session,
        user_default=True,
        session_state={},   # no override
    )

    assert is_global_memory_enabled_for_session("s1", "alice") is True


def test_set_session_writes_canonical_key_and_drops_legacy(engine_and_session, monkeypatch):
    """When we OWN the write, drop the legacy key — no point carrying
    both forever."""
    from app.models.chat import ChatSession
    from app.services.memory.recall_policy import set_session_global_memory

    engine, Session = engine_and_session
    _rebind(monkeypatch, Session)
    _seed(
        Session,
        session_state={"memory_recall_enabled": True, "other": "keep me"},
    )

    set_session_global_memory("s1", "alice", enabled=False)

    db = Session()
    try:
        row = db.query(ChatSession).filter(ChatSession.id == "s1").first()
        state = json.loads(row.session_state)
        assert state["global_memory_enabled"] is False
        # Legacy key removed by the write.
        assert "memory_recall_enabled" not in state
        # Unrelated keys preserved.
        assert state["other"] == "keep me"
    finally:
        db.close()
