"""Gmail concrete read Tool and existing connection Interaction seam."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

from app.agent_runtime.tool_call_executor import execute_tool_call
from app.agent_runtime.tool_registry import AgentToolContext
from app.agent_runtime.tools.gmail import build_gmail_search_messages_tool
from app.models.agent_execution import AgentToolCall
from app.models.agent_interaction import AgentInteraction
from app.models.chat import Conversation
from app.models.conversation_turn import ConversationTurn
from app.models.gmail_integration import GmailIntegrationAccount
from app.models.user import User
from app.schemas.gmail_integration import GmailMessageSummary, GmailSearchMessagesArgs
from app.services.gmail_integration_service import (
    GMAIL_READONLY_SCOPE,
    GmailGrantInspection,
    bind_verified_grant,
)

from tests.conftest import patch_session_locals


HANDLE = "gch_" + "tool_handle_sentinel_123456789012"
NOW = datetime(2026, 8, 13, 8, 0, tzinfo=timezone.utc)


class FakeAdapter:
    async def inspect_grant(
        self,
        _credential_handle: str,
        *,
        user_pk: int,
    ) -> GmailGrantInspection:
        assert user_pk > 0
        return GmailGrantInspection(
            google_subject="subject-tool",
            account_email="alice.private@gmail.com",
            granted_scopes=frozenset({GMAIL_READONLY_SCOPE}),
        )

    async def revoke_grant(
        self,
        _credential_handle: str,
        *,
        user_pk: int,
    ) -> None:
        assert user_pk > 0
        return None

    async def search_messages(
        self,
        credential_handle: str,
        *,
        user_pk: int,
        query: str,
        limit: int,
    ) -> list[GmailMessageSummary]:
        assert credential_handle == HANDLE
        assert user_pk > 0
        assert query == "newer_than:30d interview"
        assert limit == 3
        return [
            GmailMessageSummary(
                message_id="message-1",
                thread_id="thread-1",
                received_at=NOW,
                from_hint="recruiter@example.com",
                subject="Interview",
                snippet="Choose a time.",
            )
        ]


def _turn(db_session):
    user = User(username="gmail-tool-user", hashed_password="x")
    db_session.add(user)
    db_session.flush()
    conversation = Conversation(user_id=user.id, title="gmail tool")
    db_session.add(conversation)
    db_session.flush()
    turn = ConversationTurn(
        conversation_id=conversation.id,
        user_id=user.id,
        mode="agent",
        message="Find my interview email",
    )
    db_session.add(turn)
    db_session.commit()
    return user, conversation, turn


def test_missing_gmail_connection_uses_existing_same_call_interaction(
    db_session,
    monkeypatch,
):
    import app.agent_runtime.tool_call_executor as executor_module
    import app.agent_runtime.tools.gmail as gmail_tool_module

    patch_session_locals(
        monkeypatch,
        db_session,
        executor_module,
        gmail_tool_module,
    )
    user, conversation, turn = _turn(db_session)
    definition = build_gmail_search_messages_tool(FakeAdapter)
    args = GmailSearchMessagesArgs(query="newer_than:30d interview", limit=3)
    context = AgentToolContext(user_id=user.username, session_id=conversation.id)

    async def dispatch():
        return await definition.handler(args, context)

    result = asyncio.run(
        execute_tool_call(
            call_id="gmail-call-1",
            turn_id=turn.id,
            session_id=conversation.id,
            user_id=user.id,
            tool_name=definition.name,
            arguments=args.model_dump(mode="json"),
            timeout_seconds=1,
            dispatch=dispatch,
            effect=definition.effect,
        )
    )

    assert result["error"] == "connection_required"
    assert result["provider"] == "gmail"
    assert result["required_scope"] == GMAIL_READONLY_SCOPE
    db_session.expire_all()
    call = db_session.query(AgentToolCall).one()
    interaction = db_session.query(AgentInteraction).one()
    assert call.call_id == "gmail-call-1"
    assert call.status == "waiting"
    assert interaction.tool_call_id == "gmail-call-1"
    assert interaction.kind == "connection"
    assert interaction.request_json["reason"] == "gmail_account_not_found"


def test_connected_gmail_tool_returns_typed_read_without_handle(
    db_session,
    monkeypatch,
):
    import app.agent_runtime.tools.gmail as gmail_tool_module

    patch_session_locals(monkeypatch, db_session, gmail_tool_module)
    user, conversation, _turn_row = _turn(db_session)
    adapter = FakeAdapter()
    asyncio.run(
        bind_verified_grant(
            db_session,
            user_pk=user.id,
            credential_handle=HANDLE,
            adapter=adapter,
        )
    )
    db_session.commit()
    definition = build_gmail_search_messages_tool(lambda: adapter)
    args = GmailSearchMessagesArgs(query="newer_than:30d interview", limit=3)
    result = asyncio.run(
        definition.handler(
            args,
            AgentToolContext(user_id=user.username, session_id=conversation.id),
        )
    )

    encoded = json.dumps(result, ensure_ascii=False)
    assert result["provider"] == "gmail"
    assert result["account_hint"] == "a***@gmail.com"
    assert result["messages"][0]["message_id"] == "message-1"
    assert "untrusted data" in result["external_content_notice"]
    assert HANDLE not in encoded
    assert db_session.query(GmailIntegrationAccount).one().status == "active"


def test_gmail_tool_is_not_self_registered_without_real_adapter():
    import app.agent_runtime.tools.gmail as gmail_tool_module
    from app.agent_runtime.tool_registry import registry

    assert gmail_tool_module.build_gmail_search_messages_tool
    assert "gmail_search_messages" not in registry.tool_names
