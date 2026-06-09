"""Unit tests for the global-memory toggle policy.

The per-session override now lives in the dedicated
``conversations.global_memory_enabled`` Boolean column (NULL = fall
through to the per-user ``users.global_memory_enabled`` default). These
tests pin the two-tier resolution and the safety net on the writer.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture
def engine_and_session():
    """In-memory SQLite engine with users + conversations tables."""
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


def _seed(Session, *, username="alice", user_default=False, session_override=None):
    """Seed a user + one session ``s1``.

    ``user_default`` → ``users.global_memory_enabled``.
    ``session_override`` → ``conversations.global_memory_enabled`` (None = NULL).
    """
    from app.models.chat import Conversation
    from app.models.user import User
    db = Session()
    try:
        user = User(
            username=username,
            email=f"{username}@e.com",
            hashed_password="x",
            global_memory_enabled=user_default,
        )
        db.add(user)
        db.flush()  # assign users.id so the session can key on the integer pk
        # conversations.user_id is the integer users.id FK now (CLEANUP #2);
        # the writer's ownership guard resolves the username → pk and compares
        # against this column, so seed the resolved pk (not the username).
        db.add(Conversation(
            id="s1",
            user_id=user.id,
            global_memory_enabled=session_override,
        ))
        db.commit()
    finally:
        db.close()


def test_session_override_on_wins_over_user_default_off(engine_and_session, monkeypatch):
    """A per-session override of True wins even when the user default is False."""
    from app.services.memory.recall_policy import is_global_memory_enabled_for_session

    engine, Session = engine_and_session
    _rebind(monkeypatch, Session)
    _seed(Session, user_default=False, session_override=True)

    assert is_global_memory_enabled_for_session("s1", "alice") is True


def test_session_override_off_wins_over_user_default_on(engine_and_session, monkeypatch):
    """The override must DOWN-grade too — an explicit-False session override
    wins over a True user default. Guards against a buggy implementation that
    treats False the same as NULL and silently flips memory back ON."""
    from app.services.memory.recall_policy import is_global_memory_enabled_for_session

    engine, Session = engine_and_session
    _rebind(monkeypatch, Session)
    _seed(Session, user_default=True, session_override=False)

    assert is_global_memory_enabled_for_session("s1", "alice") is False


def test_user_default_used_when_session_override_is_null(engine_and_session, monkeypatch):
    """Falls through to ``users.global_memory_enabled`` when the session column
    is NULL."""
    from app.services.memory.recall_policy import is_global_memory_enabled_for_session

    engine, Session = engine_and_session
    _rebind(monkeypatch, Session)
    _seed(Session, user_default=True, session_override=None)

    assert is_global_memory_enabled_for_session("s1", "alice") is True


def test_defaults_to_false_when_both_unset(engine_and_session, monkeypatch):
    """Opt-in by design: NULL session override + False user default → False."""
    from app.services.memory.recall_policy import is_global_memory_enabled_for_session

    engine, Session = engine_and_session
    _rebind(monkeypatch, Session)
    _seed(Session, user_default=False, session_override=None)

    assert is_global_memory_enabled_for_session("s1", "alice") is False


def test_missing_session_degrades_to_false(engine_and_session, monkeypatch):
    """An unknown session id must not raise — it returns False (skip injection,
    keep answering)."""
    from app.services.memory.recall_policy import is_global_memory_enabled_for_session

    engine, Session = engine_and_session
    _rebind(monkeypatch, Session)
    _seed(Session, user_default=False, session_override=None)

    assert is_global_memory_enabled_for_session("does-not-exist", "alice") is False


def test_set_session_writes_column(engine_and_session, monkeypatch):
    """The writer persists the override into the column."""
    from app.models.chat import Conversation
    from app.services.memory.recall_policy import set_session_global_memory

    engine, Session = engine_and_session
    _rebind(monkeypatch, Session)
    _seed(Session, session_override=None)

    set_session_global_memory("s1", "alice", enabled=True)

    db = Session()
    try:
        row = db.query(Conversation).filter(Conversation.id == "s1").first()
        assert row.global_memory_enabled is True
    finally:
        db.close()


def test_set_session_is_noop_for_wrong_owner(engine_and_session, monkeypatch):
    """Ownership safety net: a write for a session owned by someone else is a
    no-op and leaves the column untouched."""
    from app.models.chat import Conversation
    from app.models.user import User
    from app.services.memory.recall_policy import set_session_global_memory

    engine, Session = engine_and_session
    _rebind(monkeypatch, Session)
    _seed(Session, session_override=None)
    # Seed mallory as a distinct real user so the no-op is driven by a genuine
    # pk mismatch (alice_pk != mallory_pk), not by an unseeded user → None.
    seed_db = Session()
    try:
        seed_db.add(User(username="mallory", email="mallory@e.com", hashed_password="x"))
        seed_db.commit()
    finally:
        seed_db.close()

    set_session_global_memory("s1", "mallory", enabled=True)

    db = Session()
    try:
        row = db.query(Conversation).filter(Conversation.id == "s1").first()
        assert row.global_memory_enabled is None
    finally:
        db.close()
