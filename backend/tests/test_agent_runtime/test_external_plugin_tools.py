from __future__ import annotations

import asyncio

from app.agent_runtime.tool_registry import AgentToolContext
from app.agent_runtime.tools import external_plugins
from app.core.secrets import encrypt_secret
from app.models.external_plugin_connection import ExternalPluginAccount
from app.models.user import User
from app.schemas.external_plugin_connection import (
    CanvaSearchDesignsArgs,
    NotionSearchPagesArgs,
)
from tests.conftest import NoCloseSession


class FakeConnector:
    async def search_canva_designs(self, handle, **kwargs):
        assert handle == "pch_owned_canva"
        return {"provider": "canva", "designs": [{"id": "d1", "title": "Portfolio"}]}

    async def search_notion_pages(self, handle, **kwargs):
        assert handle == "pch_owned_notion"
        return {"provider": "notion", "pages": [{"id": "p1", "title": "Tracker"}]}


def _account(db_session, provider: str) -> User:
    user = User(
        username=f"{provider}-tool-user",
        email=f"{provider}@example.com",
        hashed_password="x",
    )
    db_session.add(user)
    db_session.flush()
    db_session.add(
        ExternalPluginAccount(
            user_id=user.id,
            provider=provider,
            external_account_id=f"{provider}-external",
            account_hint=f"{provider} account",
            scopes_json=["design:meta:read"]
            if provider == "canva"
            else ["content:read"],
            credential_handle_ciphertext=encrypt_secret(f"pch_owned_{provider}"),
            status="active",
        )
    )
    db_session.commit()
    return user


def test_canva_tool_is_read_only_owned_and_bounded(db_session, monkeypatch):
    user = _account(db_session, "canva")
    monkeypatch.setattr(
        external_plugins, "SessionLocal", lambda: NoCloseSession(db_session)
    )
    definition = external_plugins.build_canva_search_designs_tool(FakeConnector())
    context = AgentToolContext(
        user_id=str(user.id), session_id="session", user_pk=user.id
    )
    preflight = definition.preflight(
        CanvaSearchDesignsArgs(query="portfolio", limit=2), context
    )
    assert preflight.connection_ready is True
    assert preflight.provider_identity == "canva"
    result = asyncio.run(
        definition.handler(CanvaSearchDesignsArgs(query="portfolio", limit=2), context)
    )
    assert result["designs"][0]["title"] == "Portfolio"


def test_notion_tool_reads_only_connected_owner(db_session, monkeypatch):
    user = _account(db_session, "notion")
    monkeypatch.setattr(
        external_plugins, "SessionLocal", lambda: NoCloseSession(db_session)
    )
    definition = external_plugins.build_notion_search_pages_tool(FakeConnector())
    context = AgentToolContext(
        user_id=str(user.id), session_id="session", user_pk=user.id
    )
    result = asyncio.run(
        definition.handler(NotionSearchPagesArgs(query="tracker", limit=3), context)
    )
    assert result["pages"] == [{"id": "p1", "title": "Tracker"}]
