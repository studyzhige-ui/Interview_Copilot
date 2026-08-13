"""Gmail authorize/callback API tests with a real HTTP adapter boundary."""

from __future__ import annotations

from typing import Iterator
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.api import gmail_integration
from app.core.security import get_current_user
from app.db.database import Base, get_db
from app.models.gmail_integration import (
    GmailIntegrationAccount,
    GmailOAuthState,
)
from app.models.user import User
from app.services.gmail_integration_service import GMAIL_READONLY_SCOPE
from app.services.gmail_integration_service import GmailIntegrationError
from app.services.google_gmail_connector import GoogleGmailConnector
from app.services.gmail_credential_store import InMemoryGmailCredentialStore
from tests.conftest import NoCloseSession


ACCESS_TOKEN = "ya29.api-access-token-secret"
REFRESH_TOKEN = "1//api-refresh-token-secret"
CLIENT_SECRET = "api-google-client-secret"


def _provider(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/token":
        form = parse_qs(request.content.decode("utf-8"))
        assert 43 <= len(form["code_verifier"][0]) <= 128
        return httpx.Response(
            200,
            json={
                "access_token": ACCESS_TOKEN,
                "refresh_token": REFRESH_TOKEN,
                "expires_in": 3600,
                "scope": f"openid email {GMAIL_READONLY_SCOPE}",
                "token_type": "Bearer",
            },
        )
    if request.url.host == "openidconnect.googleapis.com":
        return httpx.Response(
            200,
            json={
                "sub": "private-google-subject",
                "email": "alice.private@gmail.com",
                "email_verified": True,
            },
        )
    if request.url.path == "/revoke":
        return httpx.Response(200)
    raise AssertionError(f"unexpected provider request: {request.url}")


@pytest.fixture
def api_context() -> Iterator[tuple[TestClient, Session, FastAPI]]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    user = User(username="gmail-oauth-api", hashed_password="x")
    db.add(user)
    db.commit()
    transport = httpx.MockTransport(_provider)
    credential_store = InMemoryGmailCredentialStore()
    connector = GoogleGmailConnector(
        client_id="api-client.apps.googleusercontent.com",
        client_secret=CLIENT_SECRET,
        redirect_uri=("https://copilot.example/api/v1/integrations/gmail/callback"),
        product_return_uri=(
            "https://copilot.example/settings/connections?tab=integrations"
        ),
        state_ttl_seconds=600,
        timeout_seconds=5,
        credential_store=credential_store,
        session_factory=lambda: NoCloseSession(db),
        http_client_factory=lambda: httpx.AsyncClient(
            transport=transport,
            trust_env=False,
            follow_redirects=False,
            timeout=5,
        ),
    )

    def fake_db():
        yield db

    app = FastAPI()
    app.state.gmail_credential_store = credential_store
    app.include_router(gmail_integration.router, prefix="/api/v1")
    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[gmail_integration.get_gmail_oauth_connector] = lambda: (
        connector
    )
    app.dependency_overrides[gmail_integration.get_gmail_provider_adapter] = lambda: (
        connector
    )
    with TestClient(app, base_url="https://copilot.example") as client:
        yield client, db, app
    db.close()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def test_authorize_callback_returns_only_safe_account_view(api_context):
    client, db, app = api_context
    authorization = client.post("/api/v1/integrations/gmail/authorize")
    assert authorization.status_code == 200, authorization.text
    payload = authorization.json()
    url = payload["authorization_url"]
    query = parse_qs(urlsplit(url).query)
    state = query["state"][0]
    assert payload["provider"] == "gmail"
    assert payload["expires_in_seconds"] == 600
    assert query["code_challenge_method"] == ["S256"]
    assert len(query["code_challenge"][0]) == 43
    assert authorization.headers["cache-control"] == "no-store"
    assert authorization.headers["referrer-policy"] == "no-referrer"
    state_cookie = authorization.headers["set-cookie"]
    assert "gmail_oauth_state_binding=" in state_cookie
    assert "HttpOnly" in state_cookie
    assert "SameSite=lax" in state_cookie
    assert "Secure" in state_cookie
    assert "Path=/api/v1/integrations/gmail/callback" in state_cookie
    assert CLIENT_SECRET not in authorization.text
    assert ACCESS_TOKEN not in authorization.text
    assert REFRESH_TOKEN not in authorization.text

    callback = client.get(
        "/api/v1/integrations/gmail/callback",
        params={"state": state, "code": "oauth-code-never-persisted"},
        follow_redirects=False,
    )
    assert callback.status_code == 303, callback.text
    assert callback.headers["cache-control"] == "no-store"
    assert 'gmail_oauth_state_binding=""' in callback.headers["set-cookie"]
    location = urlsplit(callback.headers["location"])
    location_query = parse_qs(location.query)
    assert (location.scheme, location.netloc, location.path) == (
        "https",
        "copilot.example",
        "/settings/connections",
    )
    assert location_query == {
        "tab": ["integrations"],
        "gmail_oauth_outcome": ["connected"],
    }
    status = client.get("/api/v1/integrations/gmail")
    result = status.json()
    assert result["provider"] == "gmail"
    assert result["adapter_available"] is True
    assert result["connection_required"] is False
    assert result["account"]["account_hint"] == "a***@gmail.com"
    assert result["account"]["scopes"] == sorted(
        ["email", GMAIL_READONLY_SCOPE, "openid"]
    )
    forbidden = (
        ACCESS_TOKEN,
        REFRESH_TOKEN,
        CLIENT_SECRET,
        "oauth-code-never-persisted",
        "private-google-subject",
        "credential_handle",
    )
    assert all(value not in callback.headers["location"] for value in forbidden)

    account = db.query(GmailIntegrationAccount).one()
    credential = app.state.gmail_credential_store.snapshot_for_test()[0]
    assert account.credential_handle_ciphertext != credential.handle
    assert credential.access_token == ACCESS_TOKEN
    assert credential.refresh_token == REFRESH_TOKEN
    assert "gmail_oauth_credentials" not in Base.metadata.tables
    assert db.query(GmailOAuthState).count() == 0

    replay = client.get(
        "/api/v1/integrations/gmail/callback",
        params={"state": state, "code": "replayed-code"},
        follow_redirects=False,
    )
    assert replay.status_code == 303
    replay_query = parse_qs(urlsplit(replay.headers["location"]).query)
    assert replay_query["gmail_oauth_outcome"] == ["failed"]
    assert replay_query["gmail_oauth_error"] == ["oauth_state_invalid"]
    assert "replayed-code" not in replay.headers["location"]

    checked = client.post("/api/v1/integrations/gmail/test")
    assert checked.status_code == 200
    assert checked.json()["account"]["status"] == "active"
    revoked = client.post("/api/v1/integrations/gmail/revoke")
    assert revoked.status_code == 200
    assert revoked.json()["connection_required"] is True
    assert revoked.json()["account"]["status"] == "revoked"
    assert app.state.gmail_credential_store.snapshot_for_test() == ()
    assert all(value not in revoked.text for value in forbidden)


def test_denied_callback_consumes_state_and_folds_provider_error(api_context):
    client, _db, _app = api_context
    authorization = client.post("/api/v1/integrations/gmail/authorize").json()
    state = parse_qs(urlsplit(authorization["authorization_url"]).query)["state"][0]

    denied = client.get(
        "/api/v1/integrations/gmail/callback",
        params={
            "state": state,
            "error": "access_denied: provider-detail-must-not-reflect",
        },
        follow_redirects=False,
    )
    assert denied.status_code == 303
    denied_query = parse_qs(urlsplit(denied.headers["location"]).query)
    assert denied_query["gmail_oauth_outcome"] == ["failed"]
    assert denied_query["gmail_oauth_error"] == ["oauth_authorization_denied"]
    assert "provider-detail" not in denied.headers["location"]

    replay = client.get(
        "/api/v1/integrations/gmail/callback",
        params={"state": state, "code": "later-code"},
        follow_redirects=False,
    )
    assert replay.status_code == 303
    assert parse_qs(urlsplit(replay.headers["location"]).query)[
        "gmail_oauth_error"
    ] == ["oauth_state_invalid"]


def test_callback_requires_the_originating_browser_state_cookie(api_context):
    client, db, app = api_context
    authorization = client.post("/api/v1/integrations/gmail/authorize").json()
    state = parse_qs(urlsplit(authorization["authorization_url"]).query)["state"][0]

    with TestClient(app, base_url="https://copilot.example") as other_browser:
        missing = other_browser.get(
            "/api/v1/integrations/gmail/callback",
            params={"state": state, "code": "other-browser-code"},
            follow_redirects=False,
        )
        assert parse_qs(urlsplit(missing.headers["location"]).query)[
            "gmail_oauth_error"
        ] == ["oauth_state_invalid"]
        assert db.query(GmailOAuthState).count() == 1

        other_browser.cookies.set(
            "gmail_oauth_state_binding",
            "wrong-browser-state-binding-value",
        )
        mismatched = other_browser.get(
            "/api/v1/integrations/gmail/callback",
            params={"state": state, "code": "login-csrf-code"},
            follow_redirects=False,
        )
        assert parse_qs(urlsplit(mismatched.headers["location"]).query)[
            "gmail_oauth_error"
        ] == ["oauth_state_invalid"]
        assert db.query(GmailOAuthState).count() == 1
        assert app.state.gmail_credential_store.snapshot_for_test() == ()

    accepted = client.get(
        "/api/v1/integrations/gmail/callback",
        params={"state": state, "code": "owner-code"},
        follow_redirects=False,
    )
    assert accepted.status_code == 303
    assert parse_qs(urlsplit(accepted.headers["location"]).query)[
        "gmail_oauth_outcome"
    ] == ["connected"]


def test_failed_rebind_never_leaves_superseded_account_advertised_active(
    api_context,
    monkeypatch,
):
    client, _db, app = api_context

    first = client.post("/api/v1/integrations/gmail/authorize").json()
    first_state = parse_qs(urlsplit(first["authorization_url"]).query)["state"][0]
    connected = client.get(
        "/api/v1/integrations/gmail/callback",
        params={"state": first_state, "code": "oauth-code-never-persisted"},
        follow_redirects=False,
    )
    assert connected.status_code == 303

    async def fail_public_binding(*_args, **_kwargs):
        raise GmailIntegrationError("safe_binding_failure")

    monkeypatch.setattr(
        gmail_integration.gmail_integration_service,
        "bind_verified_grant",
        fail_public_binding,
    )
    second = client.post("/api/v1/integrations/gmail/authorize").json()
    second_state = parse_qs(urlsplit(second["authorization_url"]).query)["state"][0]
    failed = client.get(
        "/api/v1/integrations/gmail/callback",
        params={"state": second_state, "code": "oauth-code-never-persisted"},
        follow_redirects=False,
    )

    assert failed.status_code == 303
    assert parse_qs(urlsplit(failed.headers["location"]).query)[
        "gmail_oauth_error"
    ] == ["provider_error"]
    status = client.get("/api/v1/integrations/gmail").json()
    assert status["connection_required"] is True
    assert status["account"]["status"] == "invalid"
    assert app.state.gmail_credential_store.snapshot_for_test() == ()

    # Local revoke remains recoverable when callback cleanup already removed
    # the broker row after Google confirmed revocation.
    revoked = client.post("/api/v1/integrations/gmail/revoke")
    assert revoked.status_code == 200
    assert revoked.json()["account"]["status"] == "revoked"


def test_unexpected_callback_failure_returns_safely_and_clears_browser_binding(
    api_context,
    monkeypatch,
):
    client, _db, app = api_context

    async def crash_public_binding(*_args, **_kwargs):
        raise RuntimeError("internal details must not reach the browser")

    monkeypatch.setattr(
        gmail_integration.gmail_integration_service,
        "bind_verified_grant",
        crash_public_binding,
    )
    authorization = client.post("/api/v1/integrations/gmail/authorize").json()
    state = parse_qs(urlsplit(authorization["authorization_url"]).query)["state"][0]

    callback = client.get(
        "/api/v1/integrations/gmail/callback",
        params={"state": state, "code": "unexpected-failure-code"},
        follow_redirects=False,
    )

    assert callback.status_code == 303
    query = parse_qs(urlsplit(callback.headers["location"]).query)
    assert query["gmail_oauth_error"] == ["provider_error"]
    assert 'gmail_oauth_state_binding=""' in callback.headers["set-cookie"]
    assert "internal details" not in callback.headers["location"]
    assert app.state.gmail_credential_store.snapshot_for_test() == ()


def test_authorize_fails_closed_when_connector_configuration_is_absent(api_context):
    client, _db, app = api_context
    app.dependency_overrides[gmail_integration.get_gmail_oauth_connector] = lambda: None
    status = client.get("/api/v1/integrations/gmail")
    assert status.status_code == 200
    assert status.json()["adapter_available"] is False
    response = client.post("/api/v1/integrations/gmail/authorize")
    assert response.status_code == 503
    assert response.json() == {"detail": "gmail_adapter_unavailable"}

    # No configured product-return URI exists, so the protocol callback also
    # fails closed instead of constructing an attacker-controlled redirect.
    callback = client.get(
        "/api/v1/integrations/gmail/callback",
        params={"state": "state-secret-with-sufficient-length", "code": "code-secret"},
        follow_redirects=False,
    )
    assert callback.status_code == 503
    assert callback.json() == {"detail": "gmail_adapter_unavailable"}
    assert "state-secret" not in callback.text
    assert "code-secret" not in callback.text


def test_callback_validation_never_echoes_sensitive_query_values(api_context):
    client, _db, _app = api_context
    oversized_code = "secret-oauth-code-" + ("x" * 5000)
    missing_state = client.get(
        "/api/v1/integrations/gmail/callback",
        params={"code": "secret-code-without-state"},
        follow_redirects=False,
    )
    assert missing_state.status_code == 303
    missing_query = parse_qs(urlsplit(missing_state.headers["location"]).query)
    assert missing_query["gmail_oauth_error"] == ["oauth_state_invalid"]
    assert "secret-code-without-state" not in missing_state.headers["location"]

    response = client.get(
        "/api/v1/integrations/gmail/callback",
        params={"state": "short", "code": oversized_code},
        follow_redirects=False,
    )
    assert response.status_code == 303
    query = parse_qs(urlsplit(response.headers["location"]).query)
    assert query["gmail_oauth_error"] == ["oauth_state_invalid"]
    assert oversized_code not in response.headers["location"]

    authorization = client.post("/api/v1/integrations/gmail/authorize").json()
    state = parse_qs(urlsplit(authorization["authorization_url"]).query)["state"][0]
    response = client.get(
        "/api/v1/integrations/gmail/callback",
        params={"state": state, "code": oversized_code},
        follow_redirects=False,
    )
    assert response.status_code == 303
    query = parse_qs(urlsplit(response.headers["location"]).query)
    assert query["gmail_oauth_error"] == ["oauth_code_invalid"]
    assert oversized_code not in response.headers["location"]
