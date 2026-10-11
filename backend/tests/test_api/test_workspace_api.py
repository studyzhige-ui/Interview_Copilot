from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import usage, workspace
from app.api.chat import sessions
from app.core.security import get_current_user
from app.db.database import get_db
from app.models.artifact import Artifact
from app.models.chat import Conversation
from app.models.conversation_turn import ConversationTurn
from app.models.user import User
from app.models.model_budget import ModelBudgetWindow, UsageAccount


@pytest.fixture
def workspace_api(db_session):
    owner = User(username="workspace-owner", hashed_password="x")
    other = User(username="workspace-other", hashed_password="x")
    db_session.add_all([owner, other])
    db_session.commit()
    principal = {"user": owner}
    app = FastAPI()
    app.include_router(workspace.router, prefix="/api/v1")
    app.include_router(usage.router, prefix="/api/v1")
    app.include_router(sessions.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = lambda: principal["user"]
    app.dependency_overrides[get_db] = lambda: db_session
    return TestClient(app), principal, owner, other


def test_workspace_scopes_data_and_distinguishes_latest_turn(workspace_api, db_session):
    client, _, owner, other = workspace_api
    empty = client.get("/api/v1/workspace")
    assert empty.status_code == 200
    assert empty.json() == {
        "has_resume": False,
        "active_opportunities": 0,
        "open_actions": 0,
        "recent_work": [],
    }
    conversation = Conversation(user_id=owner.id, title="准备技术面试", type="general")
    private = Conversation(user_id=other.id, title="其他用户的资料", type="general")
    db_session.add_all(
        [
            conversation,
            private,
            Artifact(user_id=other.id, kind="resume", creation_key="private"),
        ]
    )
    db_session.flush()
    now = datetime.now(UTC)
    db_session.add_all(
        [
            ConversationTurn(
                conversation_id=conversation.id,
                user_id=owner.id,
                mode="agent",
                message="first",
                status="failed",
                created_at=now,
            ),
            ConversationTurn(
                conversation_id=conversation.id,
                user_id=owner.id,
                mode="agent",
                message="second",
                status="waiting",
                created_at=now + timedelta(seconds=1),
            ),
        ]
    )
    db_session.commit()
    data = client.get("/api/v1/workspace").json()
    assert not data["has_resume"]
    assert len(data["recent_work"]) == 1
    assert data["recent_work"][0]["session_id"] == conversation.id
    assert data["recent_work"][0]["status"] == "waiting"
    db_session.add(Artifact(user_id=owner.id, kind="resume", creation_key="mine"))
    db_session.commit()
    assert client.get("/api/v1/workspace").json()["has_resume"]


def test_create_retry_returns_same_conversation_and_is_user_scoped(
    workspace_api, db_session
):
    client, principal, _, other = workspace_api
    payload = {
        "type": "general",
        "title": "一起改好简历",
        "client_request_id": str(uuid4()),
    }
    first = client.post("/api/v1/chat/sessions", json=payload)
    retry = client.post("/api/v1/chat/sessions", json=payload)
    assert first.status_code == retry.status_code == 200
    assert first.json()["session_id"] == retry.json()["session_id"]
    assert db_session.query(Conversation).count() == 1
    principal["user"] = other
    second_user = client.post("/api/v1/chat/sessions", json=payload)
    assert second_user.status_code == 200
    assert second_user.json()["session_id"] != first.json()["session_id"]


def test_invalid_creation_identity_is_rejected(workspace_api):
    client, *_ = workspace_api
    assert (
        client.post(
            "/api/v1/chat/sessions", json={"client_request_id": "invalid"}
        ).status_code
        == 422
    )


def test_existing_usage_address_preserves_wire_contract_and_owner(
    workspace_api, db_session
):
    client, principal, owner, other = workspace_api
    db_session.add_all([UsageAccount(user_id=owner.id), UsageAccount(user_id=other.id)])
    db_session.flush()
    for user, tokens in ((owner, 17), (other, 83)):
        db_session.add(
            ModelBudgetWindow(
                user_id=user.id,
                window_date=datetime.now(UTC).date(),
                call_limit=100,
                token_limit=1000,
                tokens_used=tokens,
                cost_used_micros=tokens,
            )
        )
    db_session.commit()
    for user, tokens in ((owner, 17), (other, 83)):
        principal["user"] = user
        old = client.get("/api/v1/workspace/model-usage")
        current = client.get("/api/v1/usage")
        assert old.status_code == current.status_code == 200
        assert old.json()["tokens_used"] == current.json()["tokens_used"] == tokens
        assert old.json()["rated_cost_used_micros"] == tokens
        assert current.json()["rated_cost_used_micros"] == str(tokens)
