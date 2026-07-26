"""Shared pytest fixtures for the whole backend test suite.

What lives here vs. per-file fixtures
-------------------------------------
* Cross-cutting setup (env defaults, stubbing heavy ML imports) goes here.
* ``test_engine`` / ``db_session`` provide an in-memory SQLite with every ORM
  model loaded, using a SAVEPOINT pattern so a test can call
  ``session.rollback()`` after an ``IntegrityError`` without losing the
  outer transaction.
* The rate-limit autouse fixture flips slowapi off so per-endpoint 5/min
  caps don't cascade-fail later tests.

If a test directory needs its own engine (e.g. spinning up real Postgres),
it can ignore these fixtures and create its own — they're independent.
"""

import os
import sys
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


# ── Stub heavy ML modules so importing app.* never blows up at test time ──
_MAYBE_MISSING = [
    "whisperx",
    "whisperx.diarize",
    "pyannote",
    "pyannote.audio",
]
for module_name in _MAYBE_MISSING:
    if module_name not in sys.modules:
        sys.modules[module_name] = MagicMock()


# ── Test-safe env defaults — set BEFORE app.core.config gets imported ─────
# In-memory URL: it only exists so app.core.config validates; every test that
# touches a DB uses the fixtures below. A file path here would litter the
# repo with stray ``test_unit.db`` files whenever something connects.
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("DEEPSEEK_API_KEY", "test-key-not-real")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-prod")


# ── In-memory SQLite engine shared across the test session ───────────────
# StaticPool keeps one connection so tests + dependency-overridden ``get_db``
# see the same schema/data. Required for SQLite-in-memory.
TEST_DB_URL = "sqlite://"


@pytest.fixture(scope="session")
def test_engine():
    """Single engine for the whole pytest run, all ORM tables created once."""
    engine = create_engine(
        TEST_DB_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    from app.db.database import Base

    # app.models.__init__ imports every model module, so this single import
    # registers all tables on Base.metadata. New models only need to be added
    # to app/models/__init__.py (alembic/env.py relies on the same package).
    import app.models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture
def db_session(test_engine):
    """Per-test SQLAlchemy session with SAVEPOINT-style rollback.

    Each test runs in an outer transaction that auto-rolls back at teardown,
    AND inside a nested SAVEPOINT that auto-restarts after every
    ``session.commit()`` / ``session.rollback()`` the test does. That lets
    tests assert ``IntegrityError`` (which dirties the transaction state)
    without poisoning the rest of the test or its peers.
    """
    connection = test_engine.connect()
    outer = connection.begin()
    session = sessionmaker(bind=connection, expire_on_commit=False)()

    nested = connection.begin_nested()

    @event.listens_for(session, "after_transaction_end")
    def _restart_savepoint(sess, trans):
        nonlocal nested
        if trans.nested and not trans._parent.nested:
            nested = connection.begin_nested()

    try:
        yield session
    finally:
        session.close()
        if outer.is_active:
            outer.rollback()
        connection.close()


# ── Autouse: keep slowapi from rate-limiting tests ────────────────────────
# Every auth endpoint has ``@limiter.limit(RATE_AUTH)`` (5/min). Without this
# fixture, a test file that hits /login a few times to set up state would
# start getting 429s mid-file. Disabling the limiter at module level is the
# standard slowapi pattern for tests.
@pytest.fixture(autouse=True)
def _disable_rate_limiter():
    try:
        from app.core.rate_limit import limiter

        prev = limiter.enabled
        limiter.enabled = False
        yield
        limiter.enabled = prev
    except ImportError:
        # rate_limit module not imported yet — nothing to disable.
        yield


class NoCloseSession:
    """Forward attribute access to a shared test session; ``close()``
    becomes a commit so cross-call state survives service-owned
    ``SessionLocal()`` usage. Context-manager protocol supported for
    ``with SessionLocal() as db`` call sites."""

    def __init__(self, inner):
        self._inner = inner

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def close(self):
        self._inner.commit()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def patch_session_locals(monkeypatch, db_session, *modules) -> None:
    """Route every listed module's ``SessionLocal`` at the test session.

    NB: enumerated modules only — a new module that owns sessions must be
    added by its tests explicitly (silently escaping to the real DB is the
    failure mode this helper documents).
    """
    for mod in modules:
        monkeypatch.setattr(mod, "SessionLocal", lambda: NoCloseSession(db_session))
