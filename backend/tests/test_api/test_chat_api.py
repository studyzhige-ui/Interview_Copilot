"""API tests for ``app.api.chat`` — session CRUD, transcript, history.

These exercise the router via FastAPI's TestClient with ``get_current_user``
and ``get_db`` overridden so we don't need a JWT or a real Postgres.

We construct a local in-memory SQLite engine inside the module because the
shared ``db_session`` fixture in ``tests/conftest.py`` references the missing
``app.models.interview`` module.
"""
from __future__ import annotations

from typing import Iterator
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import chat as chat_api
from app.api.chat import sessions as chat_sessions_mod
from app.core.security import get_current_user
from app.db.database import Base, get_db
import app.models  # noqa: F401  — ensure mappers registered
from app.models.chat import ChatMessage, ChatSession


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def db(monkeypatch) -> Iterator[Session]:
    # StaticPool + a single shared connection so the dependency-override
    # session and the test's own session see the same in-memory DB.
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session_ = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    # The v3 memory doc services (knowledge_doc / strategy_doc / habit_doc /
    # user_profile_doc / _single_doc / _audit_log) bypass FastAPI's
    # ``get_db`` and open their own session via ``SessionLocal()`` imported
    # at module-load time. To keep memory-endpoint tests honest we must
    # rebind every such reference to a sessionmaker that points at THIS
    # in-memory engine — otherwise those endpoints would talk to the real
    # configured database (or fail with "no such table: knowledge_docs").
    import app.services.memory._audit_log_service as _audit_mod
    import app.services.memory._single_doc_service as _single_mod
    import app.services.memory.knowledge_doc_service as _kd_mod
    import app.services.memory.user_profile_doc_service as _up_mod
    for _mod in (_audit_mod, _single_mod, _kd_mod, _up_mod):
        monkeypatch.setattr(_mod, "SessionLocal", Session_, raising=False)

    session = Session_()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture
def client(db: Session) -> Iterator[TestClient]:
    """A TestClient with dependency overrides for auth + DB."""
    class FakeUser:
        username = "alice"

    def fake_user() -> FakeUser:
        return FakeUser()

    def fake_db() -> Iterator[Session]:
        yield db

    app = FastAPI()
    app.include_router(chat_api.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = fake_user
    app.dependency_overrides[get_db] = fake_db
    yield TestClient(app)


# ── /chat/sessions ────────────────────────────────────────────────────────


def test_create_chat_session_defaults_to_general(client: TestClient, db: Session):
    resp = client.post("/api/v1/chat/sessions", json={})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["session_type"] == "general"
    assert body["title"] == "通用对话"
    # DB-side effect: row exists.
    row = db.query(ChatSession).filter(ChatSession.id == body["session_id"]).first()
    assert row is not None
    assert row.user_id == "alice"


def test_create_debrief_session_requires_existing_interview(client: TestClient):
    resp = client.post(
        "/api/v1/chat/sessions",
        json={"session_type": "debrief", "interview_id": "ir_missing"},
    )
    assert resp.status_code == 404


def test_list_chat_sessions_is_user_scoped(client: TestClient, db: Session):
    db.add_all([
        ChatSession(id="s_a", user_id="alice", title="A", session_type="general"),
        ChatSession(id="s_b", user_id="bob",   title="B", session_type="general"),
    ])
    db.commit()
    resp = client.get("/api/v1/chat/sessions")
    assert resp.status_code == 200
    ids = [s["session_id"] for s in resp.json()]
    assert ids == ["s_a"]


def test_rename_session_validates_non_empty(client: TestClient, db: Session):
    db.add(ChatSession(id="s1", user_id="alice", title="old", session_type="general"))
    db.commit()
    resp = client.patch("/api/v1/chat/sessions/s1/title", json={"title": "   "})
    assert resp.status_code == 400


def test_rename_session_updates_title(client: TestClient, db: Session):
    db.add(ChatSession(id="s1", user_id="alice", title="old", session_type="general"))
    db.commit()
    resp = client.patch("/api/v1/chat/sessions/s1/title", json={"title": "new"})
    assert resp.status_code == 200
    db.expire_all()
    assert db.get(ChatSession,"s1").title == "new"


def test_rename_session_rejects_other_user(client: TestClient, db: Session):
    db.add(ChatSession(id="s_bob", user_id="bob", title="old", session_type="general"))
    db.commit()
    resp = client.patch("/api/v1/chat/sessions/s_bob/title", json={"title": "new"})
    assert resp.status_code == 404


def test_delete_session_removes_row_and_messages(client: TestClient, db: Session):
    db.add(ChatSession(id="s1", user_id="alice", title="t", session_type="general"))
    db.add(ChatMessage(session_id="s1", seq=1, role="User", content="hi"))
    db.commit()
    resp = client.delete("/api/v1/chat/sessions/s1")
    assert resp.status_code == 200
    db.expire_all()
    assert db.get(ChatSession,"s1") is None
    assert db.query(ChatMessage).filter(ChatMessage.session_id == "s1").count() == 0


# ── /chat/history ─────────────────────────────────────────────────────────


def test_history_returns_in_seq_order(client: TestClient, db: Session):
    # 0018 reverted the conversation_id split — messages are scoped only
    # by session_id again.
    db.add(ChatSession(id="s1", user_id="alice", title="t", session_type="general"))
    db.add(ChatMessage(session_id="s1", seq=1, role="User", content="hi"))
    db.add(ChatMessage(session_id="s1", seq=2, role="AI", content="hello"))
    db.commit()
    resp = client.get("/api/v1/chat/history", params={"session_id": "s1"})
    assert resp.status_code == 200
    seqs = [m["seq"] for m in resp.json()]
    assert seqs == [1, 2]


def test_history_404_for_other_user(client: TestClient, db: Session):
    db.add(ChatSession(id="s_bob", user_id="bob", title="t", session_type="general"))
    db.commit()
    resp = client.get("/api/v1/chat/history", params={"session_id": "s_bob"})
    assert resp.status_code == 404


# ── /chat/transcript ──────────────────────────────────────────────────────


def test_transcript_returns_structured_state(client: TestClient, db: Session, monkeypatch):
    db.add(ChatSession(id="s1", user_id="alice", title="t", session_type="debrief"))
    db.commit()

    class FakeTranscriptSvc:
        @staticmethod
        def get_session_meta(session_id):
            return {
                "turn_count": 2,
                "compaction_cursor": 4,
                "session_state": '{"mode": "debrief", "summary": "focus on redis"}',
                "session_type": "debrief",
                "current_conversation_id": "s1",
            }

        @staticmethod
        def get_full_transcript(session_id, conversation_id=None):
            # The real signature picked up a ``conversation_id`` kwarg in
            # migration 0015; the handler always passes it through (even
            # when None) so the fake must accept it.
            return [{"seq": 1, "role": "User", "content": "hi", "created_at": "t"}]

    monkeypatch.setattr(chat_sessions_mod, "transcript_service", FakeTranscriptSvc)
    resp = client.get("/api/v1/chat/transcript", params={"session_id": "s1"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["session_type"] == "debrief"
    assert body["compaction_cursor"] == 4
    assert body["session_state"]["summary"] == "focus on redis"
    assert body["total_messages"] == 1


def test_transcript_404_for_other_user(client: TestClient, db: Session):
    db.add(ChatSession(id="s_bob", user_id="bob", title="t", session_type="general"))
    db.commit()
    resp = client.get("/api/v1/chat/transcript", params={"session_id": "s_bob"})
    assert resp.status_code == 404


# ── /memory/* (v3) ────────────────────────────────────────────────────────


def test_memory_overview_returns_v3_bundle(client: TestClient):
    """Smoke: /memory/overview returns the 4-doc bundle (empty for a
    user with no memory yet)."""
    resp = client.get("/api/v1/memory/overview")
    assert resp.status_code == 200
    body = resp.json()
    assert "user_profile_body" in body
    assert "knowledge_topics" in body
    assert "strategy_body" in body
    assert "habit_body" in body
    # Fresh user → empty topic list (not None / missing).
    assert isinstance(body["knowledge_topics"], list)


def test_memory_knowledge_topic_get_404_when_missing(client: TestClient):
    resp = client.get("/api/v1/memory/knowledge/topics/does_not_exist")
    assert resp.status_code == 404


# ── /chat/sse — streaming (smoke test) ────────────────────────────────────


def test_sse_chat_endpoint_streams_chunks(client: TestClient, db: Session, monkeypatch):
    """Smoke test for the SSE pipeline: dependency-overridden user owns the
    session, the engine yields HarnessEvent text_delta + done, and the
    response is an SSE stream terminated with ``"type": "done"``."""
    db.add(ChatSession(id="s1", user_id="alice", title="t", session_type="general"))
    db.commit()

    async def fake_submit(self):
        from app.conversation.events import HarnessEvent
        yield HarnessEvent.text_delta("hello ", step=0, elapsed_ms=0)
        yield HarnessEvent.text_delta("world", step=0, elapsed_ms=0)
        yield HarnessEvent.text("hello world", step=0, elapsed_ms=0)
        yield HarnessEvent.done(step=0, elapsed_ms=0)

    # The Stage-G SSE endpoint constructs a ConversationEngine and
    # iterates its submit_message generator. Patch the method
    # directly so we don't need to wire the planner / retrieval /
    # memory subsystems in the unit test.
    from app.conversation.engine import ConversationEngine
    monkeypatch.setattr(ConversationEngine, "submit_message", fake_submit)

    resp = client.post("/api/v1/chat/sse/s1", json={"message": "hi"})
    assert resp.status_code == 200
    body = resp.text
    assert "hello" in body and "world" in body
    assert '"type": "done"' in body


def test_sse_chat_404_for_other_user(client: TestClient, db: Session):
    db.add(ChatSession(id="s_bob", user_id="bob", title="t", session_type="general"))
    db.commit()
    resp = client.post("/api/v1/chat/sse/s_bob", json={"message": "hi"})
    assert resp.status_code == 404


def test_sse_chat_mode_field_picks_strategy(client: TestClient, db: Session, monkeypatch):
    """``mode`` in the request body selects the strategy factory.

    Pre-fix, the SSE endpoint hardcoded ``make_chat_strategy()`` and the
    AGENT pill in the frontend was decorative — every request landed on
    the L1 chat path and the registered tool registry never reached
    the LLM. This test pins the dispatch contract:

      mode="chat"  (or omitted) → make_chat_strategy
      mode="agent"               → make_agent_strategy

    A wrong default ("agent") would unleash the full tool registry on
    every legacy client that doesn't send the field — exactly the
    regression we DO NOT want — so the back-compat default is
    asserted explicitly.
    """
    db.add(ChatSession(id="s_dispatch", user_id="alice", title="t", session_type="general"))
    db.commit()

    captured: dict[str, str] = {}

    class _StubStrategy:
        def __init__(self, label: str) -> None:
            captured["label"] = label

    # Patch at the source module — the endpoint lazy-imports both
    # factories from ``app.conversation`` inside its handler, so the
    # patch must hit the symbol there rather than on the endpoint
    # module (which never re-exports them as attributes).
    monkeypatch.setattr(
        "app.conversation.make_chat_strategy",
        lambda: _StubStrategy("chat"),
    )
    monkeypatch.setattr(
        "app.conversation.make_agent_strategy",
        lambda: _StubStrategy("agent"),
    )

    async def fake_submit(self):
        from app.conversation.events import HarnessEvent
        yield HarnessEvent.done(step=0, elapsed_ms=0)

    from app.conversation.engine import ConversationEngine
    monkeypatch.setattr(ConversationEngine, "submit_message", fake_submit)

    # Default (no mode) → chat.
    resp = client.post("/api/v1/chat/sse/s_dispatch", json={"message": "hi"})
    assert resp.status_code == 200
    assert captured["label"] == "chat", "default should be chat strategy"

    # Explicit chat → chat.
    resp = client.post(
        "/api/v1/chat/sse/s_dispatch", json={"message": "hi", "mode": "chat"},
    )
    assert resp.status_code == 200
    assert captured["label"] == "chat"

    # Explicit agent → agent.
    resp = client.post(
        "/api/v1/chat/sse/s_dispatch", json={"message": "hi", "mode": "agent"},
    )
    assert resp.status_code == 200
    assert captured["label"] == "agent", "mode='agent' must pick agent strategy"

    # Invalid mode → 422 (Pydantic Literal validation).
    resp = client.post(
        "/api/v1/chat/sse/s_dispatch", json={"message": "hi", "mode": "bogus"},
    )
    assert resp.status_code == 422
