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
def db() -> Iterator[Session]:
    # StaticPool + a single shared connection so the dependency-override
    # session and the test's own session see the same in-memory DB.
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session_ = sessionmaker(bind=engine, autoflush=False, autocommit=False)
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


# ── /memory/items ─────────────────────────────────────────────────────────


def test_memory_items_list_delegates_to_service(client: TestClient):
    from app.api.chat import memory_items as memory_items_mod

    async def fake_index(user_id):
        return [{"id": "mem_1", "description": "remember this"}]

    with patch.object(
        memory_items_mod.memory_retrieval_service,
        "get_memory_index",
        side_effect=fake_index,
    ):
        resp = client.get("/api/v1/memory/items")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == "mem_1"


def test_memory_item_get_404_when_missing(client: TestClient):
    resp = client.get("/api/v1/memory/items/does_not_exist")
    assert resp.status_code == 404


# ── /chat/sse — streaming (smoke test) ────────────────────────────────────


def test_sse_chat_endpoint_streams_chunks(client: TestClient, db: Session, monkeypatch):
    """Smoke test for the SSE pipeline: dependency-overridden user owns the
    session, the agent yields two chunks, and the response is an SSE stream
    terminated with ``{"type": "done"}``."""
    db.add(ChatSession(id="s1", user_id="alice", title="t", session_type="general"))
    db.commit()

    async def fake_stream(message, user_id, session_id):
        yield "hello "
        yield "world"

    # The handler imports lazily inside the function, so patch where it lives.
    import app.qa_pipeline.agent_executor as agent_executor_mod
    monkeypatch.setattr(agent_executor_mod, "stream_chat_with_agent", fake_stream)

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
