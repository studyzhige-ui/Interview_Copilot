from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import capabilities
from app.core.security import get_current_user
from app.db.database import get_db
from app.models.user import User
from app.models.chat import Conversation


SKILL = """---
name: api-skill
description: Skill created through the API
---
Use the configured workflow.
"""


@pytest.fixture
def client(db_session, monkeypatch):
    user = User(username="cap-api", hashed_password="x")
    db_session.add(user)
    db_session.commit()

    async def current_user():
        return user

    def current_db():
        yield db_session

    app = FastAPI()
    app.include_router(capabilities.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = current_user
    app.dependency_overrides[get_db] = current_db
    return TestClient(app)


def test_skill_api_crud(client):
    created = client.post("/api/v1/capabilities/skills", json={"content": SKILL})
    assert created.status_code == 201
    skill_id = created.json()["id"]
    assert (
        client.get("/api/v1/capabilities/skills").json()["skills"][0]["name"]
        == "api-skill"
    )
    assert (
        client.patch(
            f"/api/v1/capabilities/skills/{skill_id}",
            json={"enabled": False},
        ).json()["enabled"]
        is False
    )
    assert client.delete(f"/api/v1/capabilities/skills/{skill_id}").status_code == 204


def test_edition_policy_api(client, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.APP_EDITION", "cloud")
    monkeypatch.setattr("app.core.config.settings.MCP_ALLOW_STDIO", True)

    response = client.get("/api/v1/capabilities/edition")

    assert response.status_code == 200
    assert response.json()["edition"] == "cloud"
    assert response.json()["mcp_transports"] == ["streamable_http"]


def test_cloud_rejects_stdio_mcp(client, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.APP_EDITION", "cloud")
    monkeypatch.setattr("app.core.config.settings.MCP_ALLOW_STDIO", True)

    response = client.post(
        "/api/v1/capabilities/mcp-servers",
        json={
            "name": "local",
            "transport": "stdio",
            "command": "npx",
        },
    )

    assert response.status_code == 400
    assert "not available" in response.json()["detail"]


def test_mcp_api_crud_and_connection_test(client, monkeypatch):
    created = client.post(
        "/api/v1/capabilities/mcp-servers",
        json={
            "name": "demo",
            "transport": "streamable_http",
            "url": "https://example.com/mcp",
            "headers": {"Authorization": "Bearer secret"},
        },
    )
    assert created.status_code == 201
    server_id = created.json()["id"]

    tool = type("Tool", (), {"name": "mcp__demo__add", "description": "Add"})()
    monkeypatch.setattr(
        capabilities.manager, "list_tools", AsyncMock(return_value=[tool])
    )
    tested = client.post(f"/api/v1/capabilities/mcp-servers/{server_id}/test")
    assert tested.status_code == 200
    assert tested.json()["server"]["last_status"] == "connected"
    assert tested.json()["tools"][0]["name"] == "mcp__demo__add"

    assert (
        client.patch(
            f"/api/v1/capabilities/mcp-servers/{server_id}/enabled",
            json={"enabled": False},
        ).json()["enabled"]
        is False
    )
    assert (
        client.delete(f"/api/v1/capabilities/mcp-servers/{server_id}").status_code
        == 204
    )


def test_session_permission_api_is_user_scoped(client, db_session):
    user = db_session.query(User).filter(User.username == "cap-api").one()
    conversation = Conversation(user_id=user.id, title="permissions")
    db_session.add(conversation)
    db_session.commit()

    initial = client.get(f"/api/v1/capabilities/sessions/{conversation.id}")
    assert initial.status_code == 200
    assert initial.json()["permissions"] == {}

    changed = client.put(
        f"/api/v1/capabilities/sessions/{conversation.id}/permissions",
        json={"capability": "task_get", "decision": "deny"},
    )
    assert changed.status_code == 200
    assert changed.json()["permissions"] == {"task_get": "deny"}
