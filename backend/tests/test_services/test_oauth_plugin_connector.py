from __future__ import annotations

import asyncio
from urllib.parse import parse_qs, urlsplit

import httpx

from app.core.config import Settings
from app.core.secrets import decrypt_secret
from app.models.external_plugin_connection import ExternalPluginOAuthState
from app.models.user import User
from app.services.oauth_plugin_connector import (
    bind_external_plugin_account,
    configured_external_plugin_connectors,
)
from app.services.plugin_credential_store import (
    InMemoryPluginCredentialStore,
    PluginCredentialNotFoundError,
)
from tests.conftest import NoCloseSession


def _user(db_session, name: str = "plugin-user") -> User:
    row = User(username=name, email=f"{name}@example.com", hashed_password="x")
    db_session.add(row)
    db_session.commit()
    return row


def _settings(provider: str) -> Settings:
    values = {
        "SECRET_KEY": "plugin-test-secret-key-which-is-long-enough",
        "PLUGIN_OAUTH_PRODUCT_RETURN_URI": "https://copilot.example/plugins",
        "PLUGIN_OAUTH_STATE_TTL_SECONDS": 600,
        "PLUGIN_PROVIDER_TIMEOUT_SECONDS": 5,
    }
    if provider == "canva":
        values.update(
            {
                "CANVA_OAUTH_CLIENT_ID": "canva-client",
                "CANVA_OAUTH_CLIENT_SECRET": "canva-secret",
                "CANVA_OAUTH_REDIRECT_URI": "https://copilot.example/api/v1/integrations/plugins/canva/callback",
            }
        )
    else:
        values.update(
            {
                "NOTION_OAUTH_CLIENT_ID": "notion-client",
                "NOTION_OAUTH_CLIENT_SECRET": "notion-secret",
                "NOTION_OAUTH_REDIRECT_URI": "https://copilot.example/api/v1/integrations/plugins/notion/callback",
            }
        )
    return Settings(**values)


def _connectors(db_session, provider: str, handler, store=None):
    transport = httpx.MockTransport(handler)
    return configured_external_plugin_connectors(
        _settings(provider),
        credential_store=store or InMemoryPluginCredentialStore(),
        session_factory=lambda: NoCloseSession(db_session),
        http_client_factory=lambda: httpx.AsyncClient(
            transport=transport,
            timeout=5,
            trust_env=False,
            follow_redirects=False,
        ),
    )


def test_canva_pkce_binding_and_real_bounded_design_search(db_session):
    user = _user(db_session, "canva-user")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/oauth/token"):
            form = parse_qs(request.content.decode())
            assert form["grant_type"] == ["authorization_code"]
            assert 43 <= len(form["code_verifier"][0]) <= 128
            return httpx.Response(
                200,
                json={
                    "access_token": "canva-access",
                    "refresh_token": "canva-refresh",
                    "expires_in": 14_400,
                    "scope": "design:meta:read",
                },
            )
        if request.url.path.endswith("/users/me"):
            return httpx.Response(
                200,
                json={"team_user": {"user_id": "canva-user-id", "team_id": "team-id"}},
            )
        if request.url.path.endswith("/designs"):
            assert request.url.params["query"] == "portfolio"
            assert request.url.params["limit"] == "2"
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "design-1",
                            "title": "AI Portfolio",
                            "urls": {"edit_url": "https://canva.example/edit"},
                        },
                    ],
                },
            )
        raise AssertionError(request.url)

    connector = _connectors(db_session, "canva", handler)["canva"]
    authorization = connector.begin_authorization(user_pk=user.id)
    params = parse_qs(urlsplit(authorization.authorization_url).query)
    assert params["code_challenge_method"] == ["S256"]
    assert params["scope"] == ["design:meta:read"]
    state_row = db_session.query(ExternalPluginOAuthState).one()
    assert state_row.state_digest != params["state"][0]
    assert decrypt_secret(state_row.code_verifier_ciphertext)

    completion = asyncio.run(
        connector.complete_authorization(state=params["state"][0], code="canva-code")
    )
    row = bind_external_plugin_account(db_session, completion)
    result = asyncio.run(
        connector.search_canva_designs(
            completion.credential_handle,
            user_pk=user.id,
            query="portfolio",
            limit=2,
        )
    )
    assert row.account_hint == "Canva 用户 · ser-id"
    assert result["designs"][0]["title"] == "AI Portfolio"
    assert "access" not in str(result).lower()


def test_notion_oauth_searches_only_shared_page_titles(db_session):
    user = _user(db_session, "notion-user")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/oauth/token"):
            assert request.headers["authorization"].startswith("Basic ")
            return httpx.Response(
                200,
                json={
                    "access_token": "notion-access",
                    "refresh_token": "notion-refresh",
                    "workspace_id": "workspace-123",
                    "workspace_name": "Career Workspace",
                },
            )
        if request.url.path.endswith("/search"):
            payload = __import__("json").loads(request.content)
            assert payload["filter"] == {"property": "object", "value": "page"}
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "id": "page-1",
                            "url": "https://notion.so/page-1",
                            "last_edited_time": "2026-08-14T00:00:00Z",
                            "properties": {
                                "Name": {
                                    "type": "title",
                                    "title": [{"plain_text": "Application tracker"}],
                                },
                            },
                        },
                    ],
                    "has_more": False,
                },
            )
        raise AssertionError(request.url)

    connector = _connectors(db_session, "notion", handler)["notion"]
    authorization = connector.begin_authorization(user_pk=user.id)
    params = parse_qs(urlsplit(authorization.authorization_url).query)
    assert params["owner"] == ["user"]
    assert "code_challenge" not in params
    completion = asyncio.run(
        connector.complete_authorization(state=params["state"][0], code="notion-code")
    )
    row = bind_external_plugin_account(db_session, completion)
    result = asyncio.run(
        connector.search_notion_pages(
            completion.credential_handle,
            user_pk=user.id,
            query="application",
            limit=5,
        )
    )
    assert row.account_hint == "Career Workspace"
    assert result["pages"] == [
        {
            "id": "page-1",
            "title": "Application tracker",
            "url": "https://notion.so/page-1",
            "last_edited_time": "2026-08-14T00:00:00Z",
        }
    ]


def test_credential_store_enforces_user_and_provider_ownership():
    store = InMemoryPluginCredentialStore()
    grant = store.put_grant(
        user_pk=1,
        provider="canva",
        external_account_id="account",
        scopes=frozenset({"design:meta:read"}),
        access_token="secret-access",
        refresh_token="secret-refresh",
        access_token_expires_at=None,
    )
    assert "secret" not in repr(grant)
    for user_pk, provider in ((2, "canva"), (1, "notion")):
        try:
            store.get_grant(grant.handle, user_pk=user_pk, provider=provider)
        except PluginCredentialNotFoundError:
            pass
        else:
            raise AssertionError("cross-owner credential read must fail")


def test_incomplete_provider_configuration_registers_nothing():
    configured = Settings(
        SECRET_KEY="plugin-test-secret-key-which-is-long-enough",
        PLUGIN_OAUTH_PRODUCT_RETURN_URI="https://copilot.example/plugins",
    )
    assert (
        configured_external_plugin_connectors(
            configured,
            credential_store=InMemoryPluginCredentialStore(),
        )
        == {}
    )
