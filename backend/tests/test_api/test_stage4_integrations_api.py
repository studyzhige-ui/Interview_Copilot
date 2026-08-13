from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Iterator

import app.models  # noqa: F401
import pytest
from app.api import gmail_integration, persistent_tasks
from app.core.security import get_current_user
from app.db.database import Base, get_db
from app.models.conversation_turn import ConversationTurn
from app.models.persistent_task import PersistentTaskTrigger
from app.models.user import User
from app.services.gmail_integration_service import (
    GMAIL_READONLY_SCOPE,
    GmailGrantInspection,
    bind_verified_grant,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool


class FakeGmailAdapter:
    def __init__(self) -> None:
        self.inspect_calls = 0
        self.revoke_calls = 0

    async def inspect_grant(
        self,
        credential_handle: str,
        *,
        user_pk: int,
    ) -> GmailGrantInspection:
        assert credential_handle.startswith("gch_")
        assert user_pk > 0
        self.inspect_calls += 1
        return GmailGrantInspection(
            google_subject="google-subject-private",
            account_email="alice.private@gmail.com",
            granted_scopes=frozenset({GMAIL_READONLY_SCOPE}),
        )

    async def revoke_grant(
        self,
        credential_handle: str,
        *,
        user_pk: int,
    ) -> None:
        assert credential_handle.startswith("gch_")
        assert user_pk > 0
        self.revoke_calls += 1

    async def search_messages(self, *_args, **_kwargs):
        raise AssertionError("The settings API never reads Gmail messages")


@pytest.fixture
def db() -> Iterator[Session]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture
def api_context(db: Session, monkeypatch):
    user = User(username="stage4-user", hashed_password="x")
    db.add(user)
    db.commit()
    adapter = FakeGmailAdapter()
    dispatched_turns: list[str] = []
    monkeypatch.setattr(
        persistent_tasks,
        "schedule_turn",
        dispatched_turns.append,
    )
    from app.services.chat.turn_event_buffer import turn_event_buffer

    async def request_cancel(_turn_id: str) -> None:
        return None

    monkeypatch.setattr(turn_event_buffer, "request_cancel", request_cancel)

    def fake_db() -> Iterator[Session]:
        yield db

    app = FastAPI()
    app.include_router(persistent_tasks.router, prefix="/api/v1")
    app.include_router(gmail_integration.router, prefix="/api/v1")
    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[gmail_integration.get_gmail_provider_adapter] = lambda: (
        adapter
    )
    app.dependency_overrides[gmail_integration.get_gmail_oauth_connector] = lambda: (
        adapter
    )
    with TestClient(app) as client:
        yield client, db, user, adapter, app, dispatched_turns


def _persistent_task_payload(**overrides):
    payload = {
        "title": "每日岗位检查",
        "instruction": "每天检查新增的后端岗位并整理变化。",
        "trigger": {
            "kind": "scheduled",
            "schedule": "0 9 * * *",
            "timezone": "Asia/Shanghai",
        },
        "read_scope": ["career_profile", "public_jobs"],
        "action_scope": [],
        "allowed_tool_names": ["search_jobs"],
        "user_request_identity": "user-message:101",
        "user_request_version": "1",
        "idempotency_key": "create-daily-jobs",
    }
    payload.update(overrides)
    return payload


def test_persistent_task_crud_and_manual_trigger_dispatches_existing_worker(
    api_context,
):
    client, db, _user, _adapter, _app, dispatched_turns = api_context

    created = client.post(
        "/api/v1/persistent-tasks",
        json=_persistent_task_payload(),
    )
    assert created.status_code == 201, created.text
    task = created.json()
    task_id = task["id"]
    assert task["state"] == "active"
    assert task["allowed_tool_names_json"] == ["search_jobs"]

    listed = client.get("/api/v1/persistent-tasks")
    assert listed.status_code == 200
    assert [row["id"] for row in listed.json()] == [task_id]
    assert client.get(f"/api/v1/persistent-tasks/{task_id}").status_code == 200

    updated = client.patch(
        f"/api/v1/persistent-tasks/{task_id}",
        json={
            "expected_version": 1,
            "title": "工作日岗位检查",
            "user_request_identity": "user-edit:102",
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["version"] == 2

    paused = client.post(
        f"/api/v1/persistent-tasks/{task_id}/pause",
        json={
            "expected_version": 2,
            "state": "paused",
            "user_request_identity": "user-pause:103",
        },
    )
    assert paused.status_code == 200, paused.text
    assert paused.json()["state"] == "paused"

    resumed = client.post(
        f"/api/v1/persistent-tasks/{task_id}/resume",
        json={
            "expected_version": 3,
            "state": "active",
            "user_request_identity": "user-resume:104",
        },
    )
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["version"] == 4

    triggered = client.post(
        f"/api/v1/persistent-tasks/{task_id}/trigger",
        json={
            "kind": "manual",
            "occurred_at": datetime(2026, 8, 13, 2, 0, tzinfo=UTC).isoformat(),
            "source_identity": "user-click:105",
            "summary": "用户要求立即检查一次。",
            "idempotency_key": "manual-run-105",
        },
    )
    assert triggered.status_code == 202, triggered.text
    admission = triggered.json()
    assert admission["status"] == "admitted"
    assert admission["reason"] is None
    assert admission["turn_id"] is not None
    assert admission["pending_trigger_count"] == 0
    assert dispatched_turns == [admission["turn_id"]]
    assert db.query(PersistentTaskTrigger).count() == 1
    assert db.query(ConversationTurn).count() == 1

    history = client.get(f"/api/v1/persistent-tasks/{task_id}/triggers")
    assert history.status_code == 200
    assert [row["id"] for row in history.json()] == [admission["trigger_id"]]
    assert history.json()[0]["admitted_turn_id"] == admission["turn_id"]

    impact_response = client.get(f"/api/v1/persistent-tasks/{task_id}/deletion-impact")
    assert impact_response.status_code == 200, impact_response.text
    impact = impact_response.json()
    assert impact["task_id"] == task_id
    assert impact["pending_trigger_count"] == 0

    deleted = client.request(
        "DELETE",
        f"/api/v1/persistent-tasks/{task_id}",
        json={
            "expected_version": 4,
            "user_request_identity": "user-delete:106",
            "confirmation_token": impact["confirmation_token"],
            "confirm_task_id": task_id,
        },
    )
    assert deleted.status_code == 200, deleted.text
    assert deleted.json() == {
        "status": "success",
        "id": task_id,
        "receipt_tombstones": 0,
    }
    assert client.get(f"/api/v1/persistent-tasks/{task_id}").status_code == 404


def test_persistent_task_tool_choices_come_from_the_current_server_catalog(api_context):
    client, _db, _user, _adapter, _app, _dispatched = api_context

    response = client.get("/api/v1/persistent-tasks/eligible-tools")

    assert response.status_code == 200, response.text
    tools = response.json()
    names = [tool["name"] for tool in tools]
    assert names == sorted(names)
    assert "search_jobs" in names
    assert "start_mock_interview" not in names
    assert all(tool["description"] for tool in tools)


def test_persistent_task_rejects_registered_but_mutating_tool(api_context):
    client, _db, _user, _adapter, _app, _dispatched = api_context
    response = client.post(
        "/api/v1/persistent-tasks",
        json=_persistent_task_payload(
            allowed_tool_names=["write_file"],
            idempotency_key="mutating-tool-is-not-unattended-read",
        ),
    )
    assert response.status_code == 422
    assert "cloud-sustainable concrete Tools" in response.json()["detail"]


def test_manual_trigger_retains_pending_turn_when_broker_dispatch_fails(
    api_context,
    monkeypatch,
):
    client, db, _user, _adapter, _app, _dispatched = api_context
    created = client.post(
        "/api/v1/persistent-tasks",
        json=_persistent_task_payload(idempotency_key="dispatch-failure-task"),
    )
    task_id = created.json()["id"]

    def fail_dispatch(_turn_id: str):
        raise RuntimeError("broker unavailable")

    monkeypatch.setattr(persistent_tasks, "schedule_turn", fail_dispatch)
    response = client.post(
        f"/api/v1/persistent-tasks/{task_id}/trigger",
        json={
            "kind": "manual",
            "occurred_at": datetime(2026, 8, 13, 2, 0, tzinfo=UTC).isoformat(),
            "source_identity": "user-click:dispatch-failure",
            "summary": "立即运行一次。",
            "idempotency_key": "manual-dispatch-failure",
        },
    )

    assert response.status_code == 202
    assert response.json()["status"] == "admitted"
    assert response.json()["reason"] == "dispatch_deferred"
    turn = db.get(ConversationTurn, response.json()["turn_id"])
    assert turn is not None and turn.status == "pending"


def test_gmail_status_test_and_revoke_never_expose_credential(api_context):
    client, db, user, adapter, _app, _dispatched = api_context
    missing = client.get("/api/v1/integrations/gmail")
    assert missing.status_code == 200
    assert missing.json() == {
        "provider": "gmail",
        "adapter_available": True,
        "connection_required": True,
        "account": None,
    }
    assert client.post("/api/v1/integrations/gmail/test").status_code == 409

    raw_handle = "gch_abcdefghijklmnopqrstuvwx"
    asyncio.run(
        bind_verified_grant(
            db,
            user_pk=user.id,
            credential_handle=raw_handle,
            adapter=adapter,
        )
    )
    db.commit()

    connected = client.get("/api/v1/integrations/gmail")
    assert connected.status_code == 200
    assert connected.json()["connection_required"] is False
    assert connected.json()["account"]["account_hint"] == "a***@gmail.com"
    assert raw_handle not in connected.text
    assert "google-subject-private" not in connected.text
    assert "credential_handle" not in connected.text

    checked = client.post("/api/v1/integrations/gmail/test")
    assert checked.status_code == 200, checked.text
    assert checked.json()["account"]["status"] == "active"

    revoked = client.post("/api/v1/integrations/gmail/revoke")
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["connection_required"] is True
    assert revoked.json()["account"]["status"] == "revoked"
    assert adapter.revoke_calls == 1
    assert raw_handle not in revoked.text


def test_gmail_test_is_explicit_when_no_real_adapter_is_configured(api_context):
    client, db, user, adapter, app, _dispatched = api_context
    asyncio.run(
        bind_verified_grant(
            db,
            user_pk=user.id,
            credential_handle="gch_zyxwvutsrqponmlkjihgfedc",
            adapter=adapter,
        )
    )
    db.commit()
    app.dependency_overrides.pop(gmail_integration.get_gmail_provider_adapter)

    response = client.post("/api/v1/integrations/gmail/test")
    assert response.status_code == 503
    assert response.json()["detail"] == "gmail_adapter_unavailable"
