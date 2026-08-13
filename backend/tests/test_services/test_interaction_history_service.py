from __future__ import annotations

import asyncio

import pytest

from app.agent_runtime.tool_registry import AgentToolContext, registry
from app.db.types import utc_now
from app.models.agent_execution import AgentToolCall
from app.models.chat import Conversation, ConversationMessage
from app.models.conversation_attachment import ConversationAttachmentRef
from app.models.conversation_turn import ConversationTurn
from app.models.file_asset import FileAsset
from app.models.knowledge import KnowledgeDocument
from app.models.user import User
from app.schemas.history_search import HistorySearchQuery
from app.services import interaction_history_service
from tests.conftest import NoCloseSession


def _seed_history(db_session):
    owner = User(username="history-owner", hashed_password="x")
    other = User(username="history-other", hashed_password="x")
    db_session.add_all([owner, other])
    db_session.flush()
    conversation = Conversation(
        id="history-conversation",
        user_id=owner.id,
        title="系统设计复盘",
        type="debrief",
    )
    foreign = Conversation(id="history-foreign", user_id=other.id)
    db_session.add_all([conversation, foreign])
    db_session.flush()
    turn = ConversationTurn(
        id="history-turn",
        conversation_id=conversation.id,
        user_id=owner.id,
        mode="agent",
        message="复盘缓存设计",
        status="completed",
        completed_at=utc_now(),
    )
    db_session.add(turn)
    db_session.flush()
    message = ConversationMessage(
        conversation_id=conversation.id,
        seq=1,
        role="User",
        content="我们当时确认 Prompt Cache 只是性能优化。",
    )
    foreign_message = ConversationMessage(
        conversation_id=foreign.id,
        seq=1,
        role="User",
        content="Prompt Cache foreign secret",
    )
    db_session.add_all([message, foreign_message])
    db_session.flush()
    turn.user_message_seq = message.seq
    db_session.add(
        AgentToolCall(
            call_id="call-1",
            turn_id=turn.id,
            session_id=conversation.id,
            user_id=owner.id,
            tool_name="read_url",
            effect="read",
            arguments_json={"url": "https://example.test/cache", "token": "hidden"},
            result_json={"summary": "Prompt Cache 命中", "api_key": "secret"},
            timeout_seconds=10,
            status="completed",
            policy_decision="allow",
            policy_reason="read_allowed",
            completed_at=utc_now(),
        )
    )
    db_session.flush()
    return owner, other, conversation, turn, message


def test_history_search_returns_exact_owned_records_and_redacted_tool_audit(db_session):
    owner, _other, conversation, turn, _message = _seed_history(db_session)

    view = interaction_history_service.search_interaction_history(
        db_session,
        user_pk=owner.id,
        request=HistorySearchQuery(query="Prompt Cache"),
    )

    assert {item.kind for item in view.results} == {"message", "tool_call"}
    assert all(item.conversation_id == conversation.id for item in view.results)
    tool = next(item for item in view.results if item.kind == "tool_call")
    assert tool.identity == f"agent_tool_call:{turn.id}:call-1"
    assert "secret" not in tool.excerpt
    assert "hidden" not in tool.excerpt
    assert "[REDACTED]" in tool.excerpt


def test_history_search_filters_scope_and_never_crosses_owner(db_session):
    owner, other, conversation, _turn, message = _seed_history(db_session)

    scoped = interaction_history_service.search_interaction_history(
        db_session,
        user_pk=owner.id,
        request=HistorySearchQuery(
            query="Prompt Cache",
            conversation_id=conversation.id,
            kinds=["message"],
            roles=["user"],
        ),
    )
    assert [item.identity for item in scoped.results] == [
        f"conversation_message:{message.id}"
    ]
    with pytest.raises(interaction_history_service.HistorySearchNotFoundError):
        interaction_history_service.search_interaction_history(
            db_session,
            user_pk=other.id,
            request=HistorySearchQuery(
                query="Prompt Cache",
                conversation_id=conversation.id,
            ),
        )


def test_history_exact_fetch_reads_full_redacted_record_and_enforces_owner(db_session):
    owner, other, _conversation, turn, message = _seed_history(db_session)

    exact_message = interaction_history_service.get_interaction_history_record(
        db_session,
        user_pk=owner.id,
        identity=f"conversation_message:{message.id}",
    )
    exact_tool = interaction_history_service.get_interaction_history_record(
        db_session,
        user_pk=owner.id,
        identity=f"agent_tool_call:{turn.id}:call-1",
    )

    assert exact_message.content == "我们当时确认 Prompt Cache 只是性能优化。"
    assert exact_tool.arguments == {
        "url": "https://example.test/cache",
        "token": "[REDACTED]",
    }
    assert exact_tool.result == {
        "summary": "Prompt Cache 命中",
        "api_key": "[REDACTED]",
    }
    with pytest.raises(interaction_history_service.HistorySearchNotFoundError):
        interaction_history_service.get_interaction_history_record(
            db_session,
            user_pk=other.id,
            identity=f"conversation_message:{message.id}",
        )


def test_history_exact_fetch_keeps_removed_attachment_ref_tombstone(db_session):
    owner, _other, conversation, turn, message = _seed_history(db_session)
    asset = FileAsset(
        id="history-file",
        user_id=owner.id,
        purpose="knowledge_document",
        original_filename="old.pdf",
        object_key=f"uploads/{owner.id}/history-file/old.pdf",
        storage_uri=f"s3://bucket/uploads/{owner.id}/history-file/old.pdf",
        upload_status="uploaded",
        validation_status="passed",
    )
    db_session.add(asset)
    db_session.flush()
    document = KnowledgeDocument(
        id="history-document",
        user_id=owner.id,
        conversation_id=conversation.id,
        file_asset_id=asset.id,
        title="old.pdf",
        category="附件",
        source_kind="chat_attachment",
        status="ready",
    )
    db_session.add(document)
    db_session.flush()
    db_session.add(
        ConversationAttachmentRef(
            id="history-attachment-ref",
            draft_id="history-draft",
            user_id=owner.id,
            conversation_id=conversation.id,
            turn_id=turn.id,
            submission_id="history-submission",
            position=0,
            file_asset_id=asset.id,
            source_document_id=document.id,
            file_asset_version="file_asset:history-file",
            display_name="old.pdf",
            removed_at=utc_now(),
        )
    )
    db_session.flush()

    exact = interaction_history_service.get_interaction_history_record(
        db_session,
        user_pk=owner.id,
        identity=f"conversation_message:{message.id}",
    )

    attachment = next(
        block for block in exact.content_blocks if block["type"] == "attachment_ref"
    )
    assert exact.turn_id == turn.id
    assert attachment["attachment_ref_id"] == "history-attachment-ref"
    assert attachment["file_asset_version"] == "file_asset:history-file"
    assert attachment["accessible"] is False
    assert attachment["removed_at"] is not None


def test_history_tool_reads_same_canonical_records(db_session, monkeypatch):
    owner, _other, conversation, turn, _message = _seed_history(db_session)
    from app.agent_runtime.tools import history as history_tool

    monkeypatch.setattr(
        history_tool,
        "SessionLocal",
        lambda: NoCloseSession(db_session),
    )

    result = asyncio.run(
        registry.dispatch(
            "search_interaction_history",
            {"query": "Prompt Cache", "limit": 10},
            AgentToolContext(
                user_id=owner.username,
                user_pk=owner.id,
                session_id=conversation.id,
                turn_id=turn.id,
            ),
        )
    )

    assert result["count"] == 2
    assert {item["kind"] for item in result["results"]} == {"message", "tool_call"}

    exact = asyncio.run(
        registry.dispatch(
            "read_interaction_history",
            {"identity": f"agent_tool_call:{turn.id}:call-1"},
            AgentToolContext(
                user_id=owner.username,
                user_pk=owner.id,
                session_id=conversation.id,
                turn_id=turn.id,
            ),
        )
    )
    assert exact["tool_call_id"] == "call-1"
    assert exact["result"]["api_key"] == "[REDACTED]"
