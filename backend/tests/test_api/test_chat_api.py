"""API tests for ``app.api.chat`` — session CRUD, transcript, history.

These exercise the router via FastAPI's TestClient with ``get_current_user``
and ``get_db`` overridden so we don't need a JWT or a real Postgres.

We construct a local in-memory SQLite engine inside the module because the
shared ``db_session`` fixture in ``tests/conftest.py`` references the missing
``app.models.interview`` module.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Iterator

import app.models  # noqa: F401  — ensure mappers registered
import pytest
from app.api import chat as chat_api
from app.api.chat import sessions as conversations_mod
from app.api.interviews import mock as mock_api
from app.core.security import get_current_user
from app.db.database import Base, get_db
from app.models.chat import Conversation, ConversationMessage
from app.models.conversation_turn import ConversationTurn
from app.models.pending_submission import PendingSubmission
from app.models.user import User
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool


def test_terminal_sse_recovery_preserves_failure_and_cancellation():
    from app.api.chat.streaming import _recovery_events

    failed = [json.loads(event) for event in _recovery_events("failed", "worker died")]
    cancelled = [json.loads(event) for event in _recovery_events("cancelled", None)]
    completed = [json.loads(event) for event in _recovery_events("completed", None)]
    blocked = [json.loads(event) for event in _recovery_events("blocked", None)]

    assert [event["type"] for event in failed] == ["error", "done"]
    assert failed[0]["data"]["error"] == "worker died"
    assert [event["type"] for event in cancelled] == ["error", "done"]
    assert cancelled[0]["data"]["error"] == "本轮已取消"
    assert [event["type"] for event in completed] == ["done"]
    assert completed[-1]["data"]["outcome"] == "completed"
    assert [event["type"] for event in blocked] == ["done"]
    assert blocked[-1]["data"]["outcome"] == "blocked"


# ── Helpers ─────────────────────────────────────────────────────────────


def _uid(db: Session, username: str) -> int:
    """Seed a ``users`` row for ``username`` (idempotent) and return its
    integer ``users.id``.

    ``conversations.user_id`` is the integer ``users.id`` FK now (CLEANUP #2),
    and every chat ownership/scoping path resolves the request principal's
    username → ``users.id`` via ``resolve_user_pk`` before filtering. Seeded
    ``Conversation`` rows therefore must carry the integer pk of a real
    ``users`` row, not the username string.
    """
    row = db.query(User).filter(User.username == username).first()
    if row is None:
        row = User(username=username, hashed_password="x")
        db.add(row)
        db.commit()
    return row.id


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
    app.include_router(mock_api.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = fake_user
    app.dependency_overrides[get_db] = fake_db
    yield TestClient(app)


# ── /chat/sessions ────────────────────────────────────────────────────────


def test_create_chat_session_defaults_to_general(client: TestClient, db: Session):
    alice_pk = _uid(db, "alice")  # endpoint resolves "alice" → this pk on insert
    resp = client.post("/api/v1/chat/sessions", json={})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["type"] == "general"
    assert body["title"] == "通用对话"
    # DB-side effect: row exists, owned by alice's integer pk (not the username).
    row = db.query(Conversation).filter(Conversation.id == body["session_id"]).first()
    assert row is not None
    assert row.user_id == alice_pk
    assert row.mode == "agent"
    assert body["execution_mode_version"] == 0


def test_new_conversation_inherits_account_execution_mode(
    client: TestClient, db: Session
):
    alice_pk = _uid(db, "alice")
    alice = db.get(User, alice_pk)
    alice.default_execution_mode = "auto"
    db.commit()
    client.app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        username="alice", default_execution_mode="auto"
    )

    response = client.post("/api/v1/chat/sessions", json={})

    assert response.status_code == 200
    assert response.json()["execution_mode"] == "auto"
    assert response.json()["execution_mode_version"] == 0
    assert db.get(Conversation, response.json()["session_id"]).execution_mode == "auto"


def test_general_turn_cannot_downgrade_career_runtime_to_chat(
    client: TestClient, db: Session, monkeypatch
):
    from app.services.chat import turn_executor
    from app.services.chat.turn_event_buffer import turn_event_buffer

    user_id = _uid(db, "alice")
    db.add(
        Conversation(
            id="career_mode",
            user_id=user_id,
            title="Career",
            type="general",
            mode="chat",
        )
    )
    db.commit()

    async def ping():
        return None

    monkeypatch.setattr(turn_event_buffer, "ping", ping)
    monkeypatch.setattr(turn_executor, "schedule_turn", lambda _turn_id: None)

    response = client.post(
        "/api/v1/chat/career_mode/turns",
        json={
            "submission_id": "sub-career-mode",
            "message": "直接回答也由 Agent 决策",
            "mode": "chat",
        },
    )

    assert response.status_code == 202
    turn = db.get(ConversationTurn, response.json()["turn_id"])
    assert turn is not None and turn.mode == "agent"
    db.expire_all()
    assert db.get(Conversation, "career_mode").mode == "agent"


def test_create_turn_is_backgrounded(client: TestClient, db: Session, monkeypatch):
    from app.services.chat import turn_executor
    from app.services.chat.turn_event_buffer import turn_event_buffer

    user_id = _uid(db, "alice")
    db.add(Conversation(id="s_turn", user_id=user_id, title="T", type="general"))
    db.commit()

    async def ping():
        return None

    scheduled: list[str] = []
    monkeypatch.setattr(turn_event_buffer, "ping", ping)
    monkeypatch.setattr(turn_executor, "schedule_turn", scheduled.append)
    response = client.post(
        "/api/v1/chat/s_turn/turns",
        json={
            "submission_id": "sub-backgrounded",
            "message": "继续完成任务",
            "mode": "agent",
            "execution_mode": "standard",
            "question_indexes": [5, 2, 5],
        },
    )

    assert response.status_code == 202
    turn = db.get(ConversationTurn, response.json()["turn_id"])
    assert response.json()["status"] == "admitted"
    assert turn and turn.status == "pending" and turn.mode == "agent"
    assert turn.submission_id == "sub-backgrounded"
    assert turn.question_indexes_json == [5, 2]
    assert db.get(Conversation, "s_turn").active_turn_id == turn.id
    user_message = (
        db.query(ConversationMessage)
        .filter_by(
            conversation_id="s_turn",
            seq=turn.user_message_seq,
        )
        .one()
    )
    assert user_message.role == "User" and user_message.content == "继续完成任务"
    assert scheduled == [turn.id]


def test_submission_retry_is_idempotent(client: TestClient, db: Session, monkeypatch):
    from app.services.chat import turn_executor
    from app.services.chat.turn_event_buffer import turn_event_buffer

    user_id = _uid(db, "alice")
    db.add(Conversation(id="s_retry", user_id=user_id, title="T", type="general"))
    db.commit()

    async def ping():
        return None

    scheduled: list[str] = []
    monkeypatch.setattr(turn_event_buffer, "ping", ping)
    monkeypatch.setattr(turn_executor, "schedule_turn", scheduled.append)
    payload = {
        "submission_id": "sub-retry",
        "version": 1,
        "message": "只发送一次",
        "mode": "agent",
    }

    first = client.post("/api/v1/chat/s_retry/turns", json=payload)
    second = client.post("/api/v1/chat/s_retry/turns", json=payload)

    assert first.status_code == second.status_code == 202
    assert first.json() == second.json()
    assert first.json()["status"] == "admitted"
    assert len(scheduled) == 1
    assert db.query(PendingSubmission).filter_by(id="sub-retry").count() == 1
    assert db.query(ConversationTurn).filter_by(submission_id="sub-retry").count() == 1
    assert (
        db.query(ConversationMessage)
        .filter_by(conversation_id="s_retry", content="只发送一次")
        .count()
        == 1
    )

    conflict = client.post(
        "/api/v1/chat/s_retry/turns",
        json={**payload, "message": "不能覆盖原输入"},
    )
    assert conflict.status_code == 409


def test_create_turn_dispatch_failure_is_terminal(
    client: TestClient,
    db: Session,
    monkeypatch,
):
    from app.services.chat import turn_executor
    from app.services.chat.turn_event_buffer import turn_event_buffer

    user_id = _uid(db, "alice")
    db.add(Conversation(id="s_dispatch", user_id=user_id, title="T", type="general"))
    db.commit()

    async def ping():
        return None

    def fail_dispatch(_turn_id: str):
        raise ConnectionError("broker offline")

    monkeypatch.setattr(turn_event_buffer, "ping", ping)
    monkeypatch.setattr(turn_executor, "schedule_turn", fail_dispatch)
    response = client.post(
        "/api/v1/chat/s_dispatch/turns",
        json={
            "submission_id": "sub-dispatch-failure",
            "message": "继续完成任务",
            "mode": "agent",
        },
    )

    assert response.status_code == 503
    turn = db.query(ConversationTurn).filter_by(conversation_id="s_dispatch").one()
    db.refresh(turn)
    assert turn.status == "failed"
    assert db.get(Conversation, "s_dispatch").active_turn_id is None


def test_active_turn_queues_submission_without_writing_history(
    client: TestClient, db: Session, monkeypatch
):
    from app.services.chat.turn_event_buffer import turn_event_buffer

    user_id = _uid(db, "alice")
    conversation = Conversation(id="s_busy", user_id=user_id, title="T", type="general")
    turn = ConversationTurn(
        id="turn_busy",
        conversation_id="s_busy",
        user_id=user_id,
        mode="agent",
        message="work",
        status="running",
    )
    conversation.active_turn_id = turn.id
    db.add_all([conversation, turn])
    db.commit()

    async def ping():
        return None

    monkeypatch.setattr(turn_event_buffer, "ping", ping)
    payload = {
        "submission_id": "sub-queued",
        "message": "next request",
        "mode": "agent",
    }
    response = client.post(
        "/api/v1/chat/s_busy/turns",
        json=payload,
    )
    assert response.status_code == 202
    assert response.json() == {
        "submission_id": "sub-queued",
        "version": 1,
        "status": "queued",
        "turn_id": None,
        "queue_position": 1,
        "error": None,
    }
    pending = db.get(PendingSubmission, "sub-queued")
    assert pending is not None and pending.status == "pending"
    retry = client.post("/api/v1/chat/s_busy/turns", json=payload)
    assert retry.status_code == 202 and retry.json() == response.json()
    assert db.query(PendingSubmission).filter_by(id="sub-queued").count() == 1
    assert (
        db.query(ConversationMessage)
        .filter_by(conversation_id="s_busy", content="next request")
        .count()
        == 0
    )
    queue = client.get("/api/v1/chat/s_busy/submissions")
    assert queue.status_code == 200
    assert queue.json() == [
        {
            "submission_id": "sub-queued",
            "version": 1,
            "status": "queued",
            "queue_position": 1,
            "message": "next request",
            "mode": "agent",
            "execution_mode": "standard",
            "question_indexes": [],
            "attachments": [],
            "object_references": [],
            "source_client_id": None,
            "error": None,
        }
    ]


def test_cancel_pending_turn_releases_session(
    client: TestClient, db: Session, monkeypatch
):
    from app.services.chat.turn_event_buffer import turn_event_buffer

    user_id = _uid(db, "alice")
    conversation = Conversation(
        id="cancel-session",
        user_id=user_id,
        title="T",
        type="general",
        active_turn_id="cancel-turn",
    )
    turn = ConversationTurn(
        id="cancel-turn",
        conversation_id=conversation.id,
        user_id=user_id,
        mode="agent",
        message="work",
        status="pending",
    )
    db.add_all([conversation, turn])
    db.commit()

    async def request_cancel(_turn_id: str):
        return None

    monkeypatch.setattr(turn_event_buffer, "request_cancel", request_cancel)
    response = client.post("/api/v1/chat/cancel-session/turns/cancel-turn/cancel")

    assert response.status_code == 202
    assert response.json()["status"] == "cancelled"
    db.expire_all()
    assert db.get(ConversationTurn, turn.id).status == "cancelled"
    assert db.get(Conversation, conversation.id).active_turn_id is None


def test_create_debrief_session_requires_existing_interview(client: TestClient):
    resp = client.post(
        "/api/v1/chat/sessions",
        json={"type": "debrief", "subject_id": "ir_missing"},
    )
    assert resp.status_code == 404


def test_list_conversations_is_user_scoped(client: TestClient, db: Session):
    # Seed BOTH users as real rows so isolation is exercised via DISTINCT
    # integer pks (not a string-vs-int type accident): the list endpoint
    # filters Conversation.user_id == resolve_user_pk(db, "alice").
    db.add_all(
        [
            Conversation(
                id="s_a", user_id=_uid(db, "alice"), title="A", type="general"
            ),
            Conversation(id="s_b", user_id=_uid(db, "bob"), title="B", type="general"),
        ]
    )
    db.commit()
    resp = client.get("/api/v1/chat/sessions")
    assert resp.status_code == 200
    ids = [s["session_id"] for s in resp.json()]
    assert ids == ["s_a"]


def test_execution_mode_get_patch_is_owner_scoped_and_cas(
    client: TestClient, db: Session
):
    alice_pk = _uid(db, "alice")
    db.add_all(
        [
            Conversation(
                id="mode-alice",
                user_id=alice_pk,
                title="A",
                type="general",
                execution_mode="standard",
            ),
            Conversation(
                id="mode-bob",
                user_id=_uid(db, "bob"),
                title="B",
                type="general",
                execution_mode="auto",
            ),
        ]
    )
    db.commit()

    current = client.get("/api/v1/chat/sessions/mode-alice/execution-mode")
    assert current.status_code == 200
    assert current.json() == {
        "session_id": "mode-alice",
        "execution_mode": "standard",
        "version": 0,
    }

    saved = client.patch(
        "/api/v1/chat/sessions/mode-alice/execution-mode",
        json={"execution_mode": "auto", "expected_version": 0},
    )
    assert saved.status_code == 200
    assert saved.json() == {
        "session_id": "mode-alice",
        "execution_mode": "auto",
        "version": 1,
    }

    stale = client.patch(
        "/api/v1/chat/sessions/mode-alice/execution-mode",
        json={"execution_mode": "standard", "expected_version": 0},
    )
    assert stale.status_code == 409
    assert (
        client.get("/api/v1/chat/sessions/mode-alice/execution-mode").json()["version"]
        == 1
    )
    assert (
        client.get("/api/v1/chat/sessions/mode-bob/execution-mode").status_code == 404
    )
    assert (
        client.patch(
            "/api/v1/chat/sessions/mode-bob/execution-mode",
            json={"execution_mode": "standard", "expected_version": 0},
        ).status_code
        == 404
    )


def test_execution_mode_change_only_affects_future_admissions(
    client: TestClient, db: Session, monkeypatch
):
    from app.services.chat.turn_event_buffer import turn_event_buffer

    user_id = _uid(db, "alice")
    conversation = Conversation(
        id="mode-freeze",
        user_id=user_id,
        title="Freeze",
        type="general",
        execution_mode="standard",
        active_turn_id="active-mode-turn",
    )
    active = ConversationTurn(
        id="active-mode-turn",
        conversation_id=conversation.id,
        user_id=user_id,
        mode="agent",
        execution_mode="standard",
        message="running",
        status="running",
    )
    db.add_all([conversation, active])
    db.commit()

    async def ping():
        return None

    monkeypatch.setattr(turn_event_buffer, "ping", ping)
    stale_device_payload = {
        "version": 1,
        "message": "queued",
        "mode": "agent",
        "execution_mode": "standard",
    }
    before = client.post(
        "/api/v1/chat/mode-freeze/turns",
        json={"submission_id": "mode-before", **stale_device_payload},
    )
    assert before.status_code == 202 and before.json()["status"] == "queued"
    assert db.get(PendingSubmission, "mode-before").execution_mode == "standard"

    changed = client.patch(
        "/api/v1/chat/sessions/mode-freeze/execution-mode",
        json={"execution_mode": "auto", "expected_version": 0},
    )
    assert changed.status_code == 200
    db.expire_all()
    assert db.get(ConversationTurn, active.id).execution_mode == "standard"
    assert db.get(PendingSubmission, "mode-before").execution_mode == "standard"

    # A stale device may still submit its last rendered value, but the server
    # rereads the Conversation and freezes the current authoritative mode.
    after = client.post(
        "/api/v1/chat/mode-freeze/turns",
        json={"submission_id": "mode-after", **stale_device_payload},
    )
    assert after.status_code == 202 and after.json()["status"] == "queued"
    assert db.get(PendingSubmission, "mode-after").execution_mode == "auto"


def test_pending_submission_execution_mode_is_an_explicit_editable_snapshot(
    client: TestClient, db: Session, monkeypatch
):
    """Editing a queued task changes only that pre-claim task snapshot.

    Conversation remains the owner for new submissions and an active Turn is
    immutable.  The queued row is user-editable ingress until claim, so its
    mode may intentionally diverge without becoming a second default owner.
    """

    from app.services.chat.turn_event_buffer import turn_event_buffer

    user_id = _uid(db, "alice")
    conversation = Conversation(
        id="mode-edit-snapshot",
        user_id=user_id,
        title="Edit snapshot",
        type="general",
        execution_mode="standard",
        active_turn_id="mode-edit-active",
    )
    active = ConversationTurn(
        id="mode-edit-active",
        conversation_id=conversation.id,
        user_id=user_id,
        mode="agent",
        execution_mode="standard",
        message="running",
        status="running",
    )
    db.add_all([conversation, active])
    db.commit()

    async def ping():
        return None

    monkeypatch.setattr(turn_event_buffer, "ping", ping)
    queued = client.post(
        "/api/v1/chat/mode-edit-snapshot/turns",
        json={
            "submission_id": "mode-edit-queued",
            "version": 1,
            "message": "queued",
            "mode": "agent",
            "execution_mode": "auto",
        },
    )
    assert queued.status_code == 202
    # New admission ignored the stale/request value and copied Conversation.
    assert db.get(PendingSubmission, "mode-edit-queued").execution_mode == "standard"

    edited = client.patch(
        "/api/v1/chat/mode-edit-snapshot/submissions/mode-edit-queued",
        json={
            "expected_version": 1,
            "message": "queued",
            "mode": "agent",
            "execution_mode": "auto",
            "question_indexes": [],
            "attachments": [],
            "object_references": [],
        },
    )
    assert edited.status_code == 200
    assert edited.json()["execution_mode"] == "auto"
    db.expire_all()
    assert db.get(Conversation, conversation.id).execution_mode == "standard"
    assert db.get(ConversationTurn, active.id).execution_mode == "standard"
    assert db.get(PendingSubmission, "mode-edit-queued").execution_mode == "auto"


def test_rename_session_validates_non_empty(client: TestClient, db: Session):
    db.add(
        Conversation(id="s1", user_id=_uid(db, "alice"), title="old", type="general")
    )
    db.commit()
    resp = client.patch("/api/v1/chat/sessions/s1/title", json={"title": "   "})
    assert resp.status_code == 400


def test_rename_session_updates_title(client: TestClient, db: Session):
    db.add(
        Conversation(id="s1", user_id=_uid(db, "alice"), title="old", type="general")
    )
    db.commit()
    resp = client.patch("/api/v1/chat/sessions/s1/title", json={"title": "new"})
    assert resp.status_code == 200
    db.expire_all()
    assert db.get(Conversation, "s1").title == "new"


def test_rename_session_rejects_other_user(client: TestClient, db: Session):
    # alice (authed principal) and bob are distinct real users → the 404 is a
    # genuine pk mismatch (alice_pk != bob_pk), not an unseeded user → None.
    _uid(db, "alice")
    db.add(
        Conversation(id="s_bob", user_id=_uid(db, "bob"), title="old", type="general")
    )
    db.commit()
    resp = client.patch("/api/v1/chat/sessions/s_bob/title", json={"title": "new"})
    assert resp.status_code == 404


def _delete_session_after_preview(client: TestClient, session_id: str):
    impact = client.get(f"/api/v1/chat/sessions/{session_id}/deletion-impact")
    assert impact.status_code == 200
    body = impact.json()
    return client.request(
        "DELETE",
        f"/api/v1/chat/sessions/{session_id}",
        json={
            "confirmation_token": body["confirmation_token"],
            "confirm_conversation_id": session_id,
        },
    )


def test_delete_session_removes_row_and_messages(client: TestClient, db: Session):
    db.add(Conversation(id="s1", user_id=_uid(db, "alice"), title="t", type="general"))
    # conversation_messages has NO user_id (keyed via session_id FK) — leave it as-is.
    db.add(ConversationMessage(conversation_id="s1", seq=1, role="User", content="hi"))
    db.commit()
    resp = _delete_session_after_preview(client, "s1")
    assert resp.status_code == 200
    db.expire_all()
    assert db.get(Conversation, "s1") is None
    assert (
        db.query(ConversationMessage)
        .filter(ConversationMessage.conversation_id == "s1")
        .count()
        == 0
    )


def test_delete_session_safely_cancels_active_turn(client: TestClient, db: Session):
    user_id = _uid(db, "alice")
    conversation = Conversation(
        id="active-session",
        user_id=user_id,
        title="t",
        type="general",
        active_turn_id="active-turn",
    )
    turn = ConversationTurn(
        id="active-turn",
        conversation_id=conversation.id,
        user_id=user_id,
        mode="agent",
        message="work",
        status="running",
    )
    db.add_all([conversation, turn])
    db.commit()

    response = _delete_session_after_preview(client, "active-session")
    assert response.status_code == 200
    assert response.json()["cancelled_turn_id"] == "active-turn"
    assert db.get(Conversation, conversation.id) is None


@pytest.mark.parametrize("turn_status", ["pending", "running", "waiting"])
def test_delete_session_safely_terminalizes_every_nonterminal_active_turn(
    client: TestClient,
    db: Session,
    turn_status: str,
):
    user_id = _uid(db, "alice")
    conversation = Conversation(
        id=f"nonterminal-{turn_status}",
        user_id=user_id,
        title="t",
        type="general",
        active_turn_id=f"turn-{turn_status}",
    )
    turn = ConversationTurn(
        id=f"turn-{turn_status}",
        conversation_id=conversation.id,
        user_id=user_id,
        mode="agent",
        message="work",
        status=turn_status,
        waiting_reason="interaction" if turn_status == "waiting" else None,
    )
    db.add_all([conversation, turn])
    db.commit()

    response = _delete_session_after_preview(client, conversation.id)

    assert response.status_code == 200
    assert response.json()["cancelled_turn_id"] == turn.id
    assert db.get(Conversation, conversation.id) is None


def test_delete_session_cannot_bypass_persistent_task_lifecycle(
    client: TestClient,
    db: Session,
):
    conversation = Conversation(
        id="automation-conversation",
        user_id=_uid(db, "alice"),
        title="automation",
        type="persistent_task",
        mode="agent",
    )
    db.add(conversation)
    db.commit()

    response = client.request(
        "DELETE",
        "/api/v1/chat/sessions/automation-conversation",
        json={
            "confirmation_token": "0" * 64,
            "confirm_conversation_id": "automation-conversation",
        },
    )

    assert response.status_code == 409
    assert "PersistentTask" in response.json()["detail"]
    assert db.get(Conversation, conversation.id) is not None


def test_list_sessions_can_filter_persistent_task_conversations(
    client: TestClient,
    db: Session,
):
    user_id = _uid(db, "alice")
    db.add_all(
        [
            Conversation(
                id="automation-list",
                user_id=user_id,
                title="automation",
                type="persistent_task",
                mode="agent",
            ),
            Conversation(
                id="ordinary-list",
                user_id=user_id,
                title="ordinary",
                type="general",
            ),
        ]
    )
    db.commit()

    response = client.get("/api/v1/chat/sessions", params={"type": "persistent_task"})

    assert response.status_code == 200
    assert [item["session_id"] for item in response.json()] == ["automation-list"]


# ── /chat/transcript ──────────────────────────────────────────────────────


def test_transcript_returns_structured_state(
    client: TestClient, db: Session, monkeypatch
):
    db.add(Conversation(id="s1", user_id=_uid(db, "alice"), title="t", type="debrief"))
    db.commit()

    class FakeTranscriptSvc:
        @staticmethod
        def get_session_meta(session_id, *, db=None):
            return {
                "turn_count": 2,
                "compaction_cursor": 4,
                "type": "debrief",
                "current_conversation_id": "s1",
            }

        @staticmethod
        def get_full_transcript(session_id, *, db=None):
            return [{"seq": 1, "role": "User", "content": "hi", "created_at": "t"}]

    monkeypatch.setattr(conversations_mod, "transcript_service", FakeTranscriptSvc)
    resp = client.get("/api/v1/chat/transcript", params={"session_id": "s1"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["type"] == "debrief"
    assert body["compaction_cursor"] == 4
    assert body["total_messages"] == 1


def test_transcript_404_for_other_user(client: TestClient, db: Session):
    _uid(db, "alice")  # authed principal — a distinct real user
    db.add(Conversation(id="s_bob", user_id=_uid(db, "bob"), title="t", type="general"))
    db.commit()
    resp = client.get("/api/v1/chat/transcript", params={"session_id": "s_bob"})
    assert resp.status_code == 404


def _seed_started_mock(
    db: Session, *, username="alice", record_id="ir_m", conv_id="c_m"
):
    """Seed a started mock: record(mock_in_progress) + conversation + opening
    message + runtime(in_progress), as the start endpoint would have."""
    from app.models.interview_record import InterviewRecord
    from app.models.mock_interview_runtime import MockInterviewRuntime

    pk = _uid(db, username)
    db.add(
        InterviewRecord(
            id=record_id,
            user_id=pk,
            source="mock",
            title="模拟面试",
            status="mock_in_progress",
            resume_text_snapshot="三年后端经验",
            jd_text_snapshot="JD",
        )
    )
    db.add(
        Conversation(
            id=conv_id,
            user_id=pk,
            title="模拟面试",
            type="mock_interview",
            subject_type="interview_record",
            subject_id=record_id,
        )
    )
    db.flush()
    opening = ConversationMessage(
        conversation_id=conv_id,
        seq=1,
        role="assistant",
        content="请做个自我介绍",
    )
    db.add(opening)
    db.flush()
    db.add(
        MockInterviewRuntime(
            user_id=pk,
            interview_record_id=record_id,
            conversation_id=conv_id,
            current_stage_key="self_intro",
            current_question_message_id=opening.id,
            plan_json=[
                {"key": "self_intro", "title": "自我介绍"},
                {"key": "candidate_questions", "title": "反问"},
            ],
            interviewer_style="professional",
            target_question_count=20,
        )
    )
    db.commit()
    return record_id, conv_id


def test_mock_start_creates_record_conversation_runtime(
    client: TestClient,
    db: Session,
    monkeypatch,
):
    """``POST /mock-interviews/start`` atomically creates the record
    (mock_in_progress), the bound conversation, the runtime (in_progress) and
    the opening interviewer message — resolving resume context from the
    canonical resume Artifact. No pre-created chat session is required."""
    from app.models.interview_record import InterviewRecord
    from app.models.job_opportunity import JobOpportunity
    from app.models.mock_interview_runtime import MockInterviewRuntime
    from app.services.resume import resume_artifact_service

    pk = _uid(db, "alice")
    resume = resume_artifact_service.create_resume_artifact(
        db,
        user_pk=pk,
        operation_key="mock-start-resume",
        title="我的简历",
        file_asset_id=None,
        raw_text="三年后端开发经验，主导过推荐系统项目",
        make_default=True,
    )
    # Migration 0029 aliases remain accepted without reading the retired row.
    resume.state.legacy_resume_id = "rsm_1"
    db.add(resume.state)
    db.add(
        JobOpportunity(
            id="jo_mock",
            user_id=pk,
            company_name="Example Co",
            job_title="Backend Engineer",
        )
    )
    db.commit()
    plan_payload = {
        "guidance": {
            "self_intro": "判断与后端岗位的整体匹配。",
            "resume_project_deep_dive": "围绕推荐系统验证个人贡献。",
            "role_technical_assessment": "抽样考察岗位相关技术能力。",
            "candidate_questions": "只根据 JD 回答候选人反问。",
        }
    }

    class _PlanningLLM:
        def complete(self, *args, **kwargs):
            return type(
                "PlanningResponse",
                (),
                {"text": json.dumps(plan_payload, ensure_ascii=False)},
            )()

    monkeypatch.setattr(
        "app.services.interview.mock_interview_service.get_llm_for_role",
        lambda *args, **kwargs: _PlanningLLM(),
    )

    resp = client.post(
        "/api/v1/mock-interviews/start",
        json={
            "resume_id": "rsm_1",
            "jd_text": "高级后端工程师岗位，要求系统设计、数据库和稳定性经验。",
            "interviewer_style": "professional",
            "target_question_count": 30,
            "job_opportunity_id": "jo_mock",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body) == {"record_id", "message"}
    assert body["record_id"]
    assert body["message"]["speaker"] == "interviewer"
    assert "自我介绍" in body["message"]["text"]

    # The exact ArtifactVersion text was frozen onto the historical record.
    record = (
        db.query(InterviewRecord)
        .filter(InterviewRecord.id == body["record_id"])
        .first()
    )
    assert record is not None and record.status == "mock_in_progress"
    assert record.job_opportunity_id == "jo_mock"
    assert "推荐系统" in (record.resume_text_snapshot or "")
    assert record.resume_id is None
    assert record.resume_artifact_id == resume.artifact.id
    assert record.resume_artifact_version_id == resume.current_version.id
    # Runtime exists and points at the opening message.
    rt = (
        db.query(MockInterviewRuntime)
        .filter(MockInterviewRuntime.interview_record_id == body["record_id"])
        .first()
    )
    assert rt is not None
    assert rt.current_question_message_id is not None
    assert rt.target_question_count == 30


def test_mock_start_rejects_other_users_opportunity_before_planning(
    client: TestClient,
    db: Session,
    monkeypatch,
):
    from app.models.job_opportunity import JobOpportunity
    from app.services.resume import resume_artifact_service

    alice_pk = _uid(db, "alice")
    bob_pk = _uid(db, "bob")
    resume = resume_artifact_service.create_resume_artifact(
        db,
        user_pk=alice_pk,
        operation_key="owned-resume",
        title="我的简历",
        file_asset_id=None,
        raw_text="三年后端开发经验",
        make_default=True,
    )
    db.add(
        JobOpportunity(
            id="jo_bob",
            user_id=bob_pk,
            company_name="Other Co",
            job_title="Backend Engineer",
        )
    )
    db.commit()
    planning_called = False

    def fail_if_planned(*_args, **_kwargs):
        nonlocal planning_called
        planning_called = True
        raise AssertionError("ownership must be checked before model planning")

    monkeypatch.setattr(
        "app.services.interview.mock_interview_service.generate_plan",
        fail_if_planned,
    )
    response = client.post(
        "/api/v1/mock-interviews/start",
        json={
            "resume_id": resume.artifact.id,
            "jd_text": "这是满足长度要求的后端工程师岗位说明文本。",
            "job_opportunity_id": "jo_bob",
        },
    )

    assert response.status_code == 404
    assert planning_called is False


def test_mock_start_rejects_resume_that_has_not_been_parsed(
    client: TestClient,
    db: Session,
):
    from app.models.file_asset import FileAsset
    from app.services.resume import resume_artifact_service

    pk = _uid(db, "alice")
    asset = FileAsset(
        id="fa_pending_resume",
        user_id=pk,
        purpose="resume",
        original_filename="resume.pdf",
        object_key="uploads/alice/fa_pending_resume/resume.pdf",
        storage_uri="s3://test/uploads/alice/fa_pending_resume/resume.pdf",
        upload_status="uploaded",
        validation_status="passed",
    )
    db.add(asset)
    db.flush()
    resume = resume_artifact_service.create_resume_artifact(
        db,
        user_pk=pk,
        operation_key="pending-resume",
        title="仍在解析的简历",
        file_asset_id=asset.id,
        raw_text=None,
        make_default=True,
    )
    db.commit()

    response = client.post(
        "/api/v1/mock-interviews/start",
        json={
            "resume_id": resume.artifact.id,
            "jd_text": "这是满足长度要求的后端工程师岗位说明文本。",
        },
    )

    assert response.status_code == 409
    assert "解析" in response.json()["detail"]


def test_mock_start_rejects_unmigrated_legacy_resume_without_reading_it(
    client: TestClient,
    db: Session,
    monkeypatch,
):
    from app.models.resume import Resume

    pk = _uid(db, "alice")
    db.add(
        Resume(
            id="rsm_unmigrated_api",
            user_id=pk,
            title="旧简历",
            raw_text_snapshot="must not reach planning",
            parse_status="ready",
        )
    )
    db.commit()

    planning_called = False

    def fail_if_planned(*_args, **_kwargs):
        nonlocal planning_called
        planning_called = True
        raise AssertionError("unmigrated Resume must fail before planning")

    monkeypatch.setattr(
        "app.services.interview.mock_interview_service.generate_plan",
        fail_if_planned,
    )
    response = client.post(
        "/api/v1/mock-interviews/start",
        json={
            "resume_id": "rsm_unmigrated_api",
            "jd_text": "这是满足长度要求的后端工程师岗位说明文本。",
        },
    )

    assert response.status_code == 404
    assert "0029" in response.json()["detail"]
    assert planning_called is False


def test_mock_answer_audio_transcribes_and_stores_one_asset(
    client: TestClient,
    db: Session,
    monkeypatch,
):
    from app.models.file_asset import FileAsset

    record_id, _ = _seed_started_mock(
        db,
        record_id="ir_audio_draft",
        conv_id="c_audio_draft",
    )

    async def fake_transcribe(_path: str, *, language: str = "zh") -> str:
        assert language == "zh"
        return "我负责了核心接口的性能优化"

    stored: dict[str, bytes] = {}

    def fake_store(file_obj, object_key: str, content_type: str | None = None) -> str:
        stored["body"] = file_obj.read()
        stored["content_type"] = (content_type or "").encode()
        return f"s3://test/{object_key}"

    monkeypatch.setattr(
        "app.services.voice.short_clip_transcription.transcribe_short_clip",
        fake_transcribe,
    )
    monkeypatch.setattr(
        "app.services.uploads.file_asset_service.upload_file_to_owned_key",
        fake_store,
    )

    audio = b"\x1a\x45\xdf\xa3" + b"mock-webm-audio" * 3
    response = client.post(
        f"/api/v1/mock-interviews/{record_id}/answer-audio",
        files={"file": ("answer.webm", audio, "audio/webm")},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"text", "audio_file_asset_id"}
    assert body["text"] == "我负责了核心接口的性能优化"
    assert stored["body"] == audio

    asset = db.get(FileAsset, body["audio_file_asset_id"])
    assert asset is not None
    assert asset.purpose == "mock_audio_clip"
    assert asset.upload_status == "uploaded"
    assert asset.validation_status == "passed"
    assert asset.size_bytes == len(audio)


def test_mock_answer_audio_does_not_store_empty_transcript(
    client: TestClient,
    db: Session,
    monkeypatch,
):
    from app.models.file_asset import FileAsset

    record_id, _ = _seed_started_mock(
        db,
        record_id="ir_audio_empty",
        conv_id="c_audio_empty",
    )

    async def fake_transcribe(_path: str, *, language: str = "zh") -> str:
        return "  "

    monkeypatch.setattr(
        "app.services.voice.short_clip_transcription.transcribe_short_clip",
        fake_transcribe,
    )
    audio = b"\x1a\x45\xdf\xa3" + b"mock-webm-audio" * 3

    response = client.post(
        f"/api/v1/mock-interviews/{record_id}/answer-audio",
        files={"file": ("answer.webm", audio, "audio/webm")},
    )

    assert response.status_code == 422
    assert "重新录制" in response.json()["detail"]
    assert db.query(FileAsset).count() == 0


def test_mock_answer_audio_reports_storage_failure_and_marks_asset_failed(
    client: TestClient,
    db: Session,
    monkeypatch,
):
    from app.models.file_asset import FileAsset

    record_id, _ = _seed_started_mock(
        db,
        record_id="ir_audio_storage_failure",
        conv_id="c_audio_storage_failure",
    )

    async def fake_transcribe(_path: str, *, language: str = "zh") -> str:
        return "已经成功转写"

    def fail_store(*_args, **_kwargs):
        raise RuntimeError("storage unavailable")

    monkeypatch.setattr(
        "app.services.voice.short_clip_transcription.transcribe_short_clip",
        fake_transcribe,
    )
    monkeypatch.setattr(
        "app.services.uploads.file_asset_service.upload_file_to_owned_key",
        fail_store,
    )
    audio = b"\x1a\x45\xdf\xa3" + b"mock-webm-audio" * 3

    response = client.post(
        f"/api/v1/mock-interviews/{record_id}/answer-audio",
        files={"file": ("answer.webm", audio, "audio/webm")},
    )

    assert response.status_code == 503
    assert "录音仍保留" in response.json()["detail"]
    asset = db.query(FileAsset).one()
    assert asset.upload_status == "failed"
    assert asset.validation_status == "failed"


def test_mock_answer_audio_reports_unavailable_transcription_without_storing(
    client: TestClient,
    db: Session,
    monkeypatch,
):
    from app.models.file_asset import FileAsset
    from app.services.voice.short_clip_transcription import TranscriptionUnavailable

    record_id, _ = _seed_started_mock(
        db,
        record_id="ir_audio_asr_unavailable",
        conv_id="c_audio_asr_unavailable",
    )

    async def fail_transcribe(_path: str, *, language: str = "zh") -> str:
        raise TranscriptionUnavailable("model unavailable")

    monkeypatch.setattr(
        "app.services.voice.short_clip_transcription.transcribe_short_clip",
        fail_transcribe,
    )
    audio = b"\x1a\x45\xdf\xa3" + b"mock-webm-audio" * 3

    response = client.post(
        f"/api/v1/mock-interviews/{record_id}/answer-audio",
        files={"file": ("answer.webm", audio, "audio/webm")},
    )

    assert response.status_code == 503
    assert "录音仍保留" in response.json()["detail"]
    assert db.query(FileAsset).count() == 0


def test_mock_answer_appends_messages_and_advances(
    client: TestClient,
    db: Session,
    monkeypatch,
):
    """``POST /mock-interviews/{id}/answer`` persists the candidate's answer,
    generates the next interviewer line, persists it, and advances the runtime
    stage — without any Director/retry machinery."""
    from app.models.mock_interview_runtime import MockInterviewRuntime
    from app.services.interview.mock_interview_service import NextTurn

    record_id, conv_id = _seed_started_mock(db)
    runtime = (
        db.query(MockInterviewRuntime)
        .filter(MockInterviewRuntime.interview_record_id == record_id)
        .one()
    )

    async def fake_next_turn(**kwargs):
        return NextTurn(
            interviewer_message="好的。讲讲你最近的项目？",
            next_stage_key="candidate_questions",
            is_ready_to_finish=False,
        )

    monkeypatch.setattr(
        "app.services.interview.mock_interview_service.generate_next_turn",
        fake_next_turn,
    )

    resp = client.post(
        f"/api/v1/mock-interviews/{record_id}/answer",
        json={
            "answer_text": "我叫小王，三年后端。",
            "question_message_id": runtime.current_question_message_id,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body) == {"message", "end_suggested"}
    assert body["message"]["speaker"] == "interviewer"
    assert body["message"]["text"].startswith("好的")
    assert body["end_suggested"] is False

    # The user answer + the new assistant line are both persisted (opening + 2).
    msgs = (
        db.query(ConversationMessage)
        .filter(ConversationMessage.conversation_id == conv_id)
        .order_by(ConversationMessage.seq)
        .all()
    )
    assert [m.role for m in msgs] == ["assistant", "user", "assistant"]
    rt = (
        db.query(MockInterviewRuntime)
        .filter(MockInterviewRuntime.interview_record_id == record_id)
        .first()
    )
    assert rt.current_stage_key == "candidate_questions"


def test_mock_answer_failure_preserves_candidate_answer_for_recovery(
    client: TestClient,
    db: Session,
    monkeypatch,
):
    from app.models.mock_interview_runtime import MockInterviewRuntime
    from app.services.interview.mock_interview_service import (
        NextTurnGenerationError,
    )

    record_id, conv_id = _seed_started_mock(
        db,
        record_id="ir_answer_recovery",
        conv_id="c_answer_recovery",
    )
    runtime = (
        db.query(MockInterviewRuntime)
        .filter(MockInterviewRuntime.interview_record_id == record_id)
        .one()
    )

    async def fail_next_turn(**kwargs):
        raise NextTurnGenerationError("LLM unavailable")

    monkeypatch.setattr(
        "app.services.interview.mock_interview_service.generate_next_turn",
        fail_next_turn,
    )
    response = client.post(
        f"/api/v1/mock-interviews/{record_id}/answer",
        json={
            "answer_text": "这段回答必须被保留",
            "question_message_id": runtime.current_question_message_id,
        },
    )

    assert response.status_code == 503
    assert "回答已保存" in response.json()["detail"]
    messages = (
        db.query(ConversationMessage)
        .filter(ConversationMessage.conversation_id == conv_id)
        .order_by(ConversationMessage.seq)
        .all()
    )
    assert [(message.role, message.content) for message in messages] == [
        ("assistant", "请做个自我介绍"),
        ("user", "这段回答必须被保留"),
    ]
    db.refresh(runtime)
    assert runtime.answer_claimed_at is None


def test_mock_finish_transitions_to_processing_review_and_dispatches(
    client: TestClient,
    db: Session,
    monkeypatch,
):
    """``finish`` flips the record to processing_review and dispatches the
    review task; the record drops out of the review list until review_ready."""
    from app.models.interview_record import InterviewRecord

    record_id, conv_id = _seed_started_mock(db)
    # Finish requires at least one answered turn.
    db.add(
        ConversationMessage(
            conversation_id=conv_id, seq=2, role="user", content="我的回答"
        )
    )
    db.commit()

    dispatched: dict = {}

    class _FakeAsyncResult:
        id = "task_123"

    def fake_delay(rid):
        dispatched["record_id"] = rid
        return _FakeAsyncResult()

    monkeypatch.setattr(
        "app.services.interview.mock_flow.dispatch_mock_interview_review", fake_delay
    )

    resp = client.post(f"/api/v1/mock-interviews/{record_id}/finish")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {"status": "processing_review", "record_id": record_id}
    assert dispatched["record_id"] == record_id

    db.expire_all()
    assert db.get(InterviewRecord, record_id).status == "processing_review"
    from app.models.mock_interview_runtime import MockInterviewRuntime

    assert db.get(MockInterviewRuntime, record_id) is None


def test_mock_abandon_deletes_everything(client: TestClient, db: Session):
    """``DELETE /mock-interviews/{id}`` removes the conversation + messages +
    runtime + draft record for an unfinished mock."""
    from app.models.interview_record import InterviewRecord
    from app.models.mock_interview_runtime import MockInterviewRuntime

    record_id, conv_id = _seed_started_mock(db)

    resp = client.delete(f"/api/v1/mock-interviews/{record_id}")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"status": "deleted", "record_id": record_id}

    db.expire_all()
    assert db.get(InterviewRecord, record_id) is None
    assert db.get(Conversation, conv_id) is None
    assert (
        db.query(MockInterviewRuntime)
        .filter(MockInterviewRuntime.interview_record_id == record_id)
        .first()
        is None
    )
    assert (
        db.query(ConversationMessage)
        .filter(ConversationMessage.conversation_id == conv_id)
        .count()
        == 0
    )


def test_in_progress_returns_active_runtime(client: TestClient, db: Session):
    """``GET /mock-interviews/in-progress`` surfaces the user's active runtime
    for the resume banner."""
    record_id, conv_id = _seed_started_mock(db)
    resp = client.get("/api/v1/mock-interviews/in-progress")
    assert resp.status_code == 200
    body = resp.json()
    assert body["has_in_progress"] is True
    assert body["record_id"] == record_id
    assert set(body) == {
        "has_in_progress",
        "record_id",
        "title",
        "last_activity_at",
    }


def test_live_state_returns_complete_user_facing_conversation(
    client: TestClient,
    db: Session,
):
    record_id, conv_id = _seed_started_mock(db)
    db.add_all(
        [
            ConversationMessage(
                conversation_id=conv_id,
                seq=2,
                role="user",
                content="我的第一段回答",
            ),
            ConversationMessage(
                conversation_id=conv_id,
                seq=3,
                role="assistant",
                content="请继续讲讲项目难点",
            ),
        ]
    )
    db.commit()

    response = client.get(f"/api/v1/mock-interviews/{record_id}/live-state")

    assert response.status_code == 200
    messages = response.json()["messages"]
    assert [message["speaker"] for message in messages] == [
        "interviewer",
        "candidate",
        "interviewer",
    ]
    assert [message["text"] for message in messages] == [
        "请做个自我介绍",
        "我的第一段回答",
        "请继续讲讲项目难点",
    ]


def test_in_progress_false_when_no_active_runtime(client: TestClient, db: Session):
    _uid(db, "alice")
    resp = client.get("/api/v1/mock-interviews/in-progress")
    assert resp.status_code == 200
    assert resp.json()["has_in_progress"] is False


# ── Phase 5 (MOCK-3): endpoint-level guard mappings ──────────────────────


def test_answer_with_stale_token_maps_to_409(client: TestClient, db: Session):
    from app.models.mock_interview_runtime import MockInterviewRuntime

    record_id, conv_id = _seed_started_mock(db, record_id="ir_tok", conv_id="c_tok")
    rt = (
        db.query(MockInterviewRuntime)
        .filter(MockInterviewRuntime.interview_record_id == record_id)
        .first()
    )
    rt.current_question_message_id = 42
    db.commit()

    resp = client.post(
        f"/api/v1/mock-interviews/{record_id}/answer",
        json={"answer_text": "回答", "question_message_id": 41},
    )
    assert resp.status_code == 409
    assert "已推进" in resp.json()["detail"]


def test_finish_on_non_in_progress_record_maps_to_409(client: TestClient, db: Session):
    from app.models.interview_record import InterviewRecord

    record_id, _ = _seed_started_mock(db, record_id="ir_fin409", conv_id="c_fin409")
    rec = db.query(InterviewRecord).filter(InterviewRecord.id == record_id).first()
    rec.status = "processing_review"  # a double-click already dispatched
    db.commit()

    resp = client.post(f"/api/v1/mock-interviews/{record_id}/finish")
    assert resp.status_code == 409


def test_start_with_active_run_maps_to_409(client: TestClient, db: Session):
    _seed_started_mock(db, record_id="ir_dup", conv_id="c_dup")
    resp = client.post(
        "/api/v1/mock-interviews/start",
        json={
            "resume_id": "any",
            "jd_text": "这是满足接口校验长度要求的岗位说明文本内容。",
        },
    )
    assert resp.status_code == 409
    assert "进行中" in resp.json()["detail"]
