from __future__ import annotations

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import external_plugins
from app.core.config import Settings
from app.core.security import get_current_user
from app.db.database import get_db
from app.models.user import User
from app.services.oauth_plugin_connector import configured_external_plugin_connectors
from app.services.plugin_credential_store import InMemoryPluginCredentialStore
from tests.conftest import NoCloseSession


def _user(db_session) -> User:
    row = User(
        username="plugin-api-user", email="plugin-api@example.com", hashed_password="x"
    )
    db_session.add(row)
    db_session.commit()
    return row


def _app(db_session, user: User, connectors):
    app = FastAPI()
    app.include_router(external_plugins.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[external_plugins.get_external_plugin_connectors] = lambda: (
        connectors
    )
    return app


def _canva_connector(db_session):
    configured = Settings(
        SECRET_KEY="plugin-api-secret-key-which-is-long-enough",
        PLUGIN_OAUTH_PRODUCT_RETURN_URI="https://copilot.example/plugins",
        CANVA_OAUTH_CLIENT_ID="canva-client",
        CANVA_OAUTH_CLIENT_SECRET="canva-secret",
        CANVA_OAUTH_REDIRECT_URI="https://copilot.example/api/v1/integrations/plugins/canva/callback",
    )
    return configured_external_plugin_connectors(
        configured,
        credential_store=InMemoryPluginCredentialStore(),
        session_factory=lambda: NoCloseSession(db_session),
        http_client_factory=lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(500))
        ),
    )["canva"]


def test_status_honestly_reports_missing_provider_adapter(db_session):
    user = _user(db_session)
    client = TestClient(_app(db_session, user, {}))
    response = client.get("/api/v1/integrations/plugins/notion")
    assert response.status_code == 200
    assert response.json() == {
        "provider": "notion",
        "adapter_available": False,
        "connection_required": True,
        "account": None,
    }


def test_authorize_sets_browser_binding_and_returns_only_safe_handoff(db_session):
    user = _user(db_session)
    connector = _canva_connector(db_session)
    client = TestClient(_app(db_session, user, {"canva": connector}))
    response = client.post("/api/v1/integrations/plugins/canva/authorize")
    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "canva"
    assert payload["authorization_url"].startswith(
        "https://www.canva.com/api/oauth/authorize?"
    )
    assert "access_token" not in response.text
    assert "plugin_oauth_state_canva" in response.headers["set-cookie"]
    assert "HttpOnly" in response.headers["set-cookie"]
