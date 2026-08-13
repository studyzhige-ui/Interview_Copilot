from __future__ import annotations

import uuid

import pytest
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError

from app.models.agent_execution import AgentToolCall
from app.models.agent_interaction import AgentInteraction
from app.models.chat import Conversation
from app.models.conversation_turn import ConversationTurn
from app.models.user import User
from app.schemas.agent_interaction import AgentInteractionView, InteractionPayload
from app.services.chat.interaction_service import (
    InteractionConflictError,
    InteractionOwnershipError,
    create_pending_interaction,
    get_pending_interaction,
    resolve_interaction,
)


class ApprovalRequest(BaseModel):
    action: str
    arguments: dict


class ApprovalResolution(BaseModel):
    decision: str
    metadata: dict


def _seed_turn(db_session, *, status: str = "waiting"):
    suffix = uuid.uuid4().hex
    user = User(username=f"interaction-{suffix}", hashed_password="test-hash")
    db_session.add(user)
    db_session.flush()
    conversation = Conversation(user_id=user.id, mode="agent")
    db_session.add(conversation)
    db_session.flush()
    turn = ConversationTurn(
        conversation_id=conversation.id,
        user_id=user.id,
        mode="agent",
        message="perform the requested action",
        status=status,
    )
    db_session.add(turn)
    db_session.flush()
    return user, conversation, turn


def _seed_tool_call(db_session, *, user, conversation, turn, call_id="call-1"):
    call = AgentToolCall(
        call_id=call_id,
        turn_id=turn.id,
        session_id=conversation.id,
        user_id=user.id,
        tool_name="test.action",
        arguments_json={},
        timeout_seconds=10,
        status="waiting",
    )
    db_session.add(call)
    db_session.flush()
    return call


def test_create_persists_redacted_typed_request_and_original_call_identity(
    db_session,
):
    user, conversation, turn = _seed_turn(db_session)
    _seed_tool_call(
        db_session,
        user=user,
        conversation=conversation,
        turn=turn,
        call_id="provider-call-42",
    )

    row = create_pending_interaction(
        db_session,
        turn_id=turn.id,
        user_id=user.id,
        tool_call_id="provider-call-42",
        kind="approval",
        request=ApprovalRequest(
            action="send_message",
            arguments={
                "recipient": "candidate@example.test",
                "client_secret": "must-never-be-persisted",
            },
        ),
    )

    assert row.status == "pending"
    assert row.version == 1
    assert row.tool_call_id == "provider-call-42"
    assert row.request_json == {
        "action": "send_message",
        "arguments": {
            "recipient": "candidate@example.test",
            "client_secret": "[REDACTED]",
        },
    }
    assert "must-never-be-persisted" not in str(row.request_json)
    assert get_pending_interaction(db_session, turn_id=turn.id, user_id=user.id) is row

    view = AgentInteractionView.model_validate(row)
    assert view.kind == "approval"
    assert view.request == row.request_json


def test_optional_tool_call_must_belong_to_same_owned_turn(db_session):
    user, _conversation, turn = _seed_turn(db_session)

    with pytest.raises(ValueError, match="same Turn"):
        create_pending_interaction(
            db_session,
            turn_id=turn.id,
            user_id=user.id,
            tool_call_id="not-this-turn",
            kind="connection",
            request=InteractionPayload(root={"provider": "example"}),
        )

    assert get_pending_interaction(db_session, turn_id=turn.id, user_id=user.id) is None


def test_database_allows_only_one_pending_interaction_per_turn(db_session):
    user, _conversation, turn = _seed_turn(db_session)
    create_pending_interaction(
        db_session,
        turn_id=turn.id,
        user_id=user.id,
        kind="clarification",
        request=InteractionPayload(root={"question": "Which role?"}),
    )

    duplicate = AgentInteraction(
        turn_id=turn.id,
        kind="client_readiness",
        status="pending",
        request_json={"requirement": "active client"},
        version=1,
    )
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.add(duplicate)
            db_session.flush()


@pytest.mark.parametrize("terminal_status", ["resolved", "rejected", "cancelled"])
def test_resolve_is_owner_checked_cas_and_does_not_mutate_turn(
    db_session,
    terminal_status,
):
    owner, _conversation, turn = _seed_turn(db_session)
    other = User(
        username=f"other-{uuid.uuid4().hex}",
        hashed_password="test-hash",
    )
    db_session.add(other)
    db_session.flush()
    row = create_pending_interaction(
        db_session,
        turn_id=turn.id,
        user_id=owner.id,
        kind="approval",
        request=ApprovalRequest(action="send_message", arguments={}),
    )

    with pytest.raises(InteractionOwnershipError):
        resolve_interaction(
            db_session,
            interaction_id=row.id,
            user_id=other.id,
            expected_version=1,
            status=terminal_status,
            resolution=ApprovalResolution(decision="foreign", metadata={}),
        )

    resolved = resolve_interaction(
        db_session,
        interaction_id=row.id,
        user_id=owner.id,
        expected_version=1,
        status=terminal_status,
        resolution=ApprovalResolution(
            decision=terminal_status,
            metadata={"authorization": "Bearer must-never-be-persisted"},
        ),
    )

    assert resolved.status == terminal_status
    assert resolved.version == 2
    assert resolved.resolved_at is not None
    assert resolved.resolution_json["decision"] == terminal_status
    assert resolved.resolution_json["metadata"]["authorization"] == "[REDACTED]"
    assert turn.status == "waiting"

    with pytest.raises(InteractionConflictError, match="version=1"):
        resolve_interaction(
            db_session,
            interaction_id=row.id,
            user_id=owner.id,
            expected_version=1,
            status=terminal_status,
            resolution=ApprovalResolution(decision="replay", metadata={}),
        )


def test_resolved_interaction_releases_the_pending_unique_slot(db_session):
    user, _conversation, turn = _seed_turn(db_session)
    first = create_pending_interaction(
        db_session,
        turn_id=turn.id,
        user_id=user.id,
        kind="clarification",
        request=InteractionPayload(root={"question": "First?"}),
    )
    resolve_interaction(
        db_session,
        interaction_id=first.id,
        user_id=user.id,
        expected_version=1,
        status="resolved",
        resolution=InteractionPayload(root={"answer": "yes"}),
    )

    second = create_pending_interaction(
        db_session,
        turn_id=turn.id,
        user_id=user.id,
        kind="client_readiness",
        request=InteractionPayload(root={"requirement": "active client"}),
    )

    assert second.id != first.id
    assert second.status == "pending"
    assert (
        get_pending_interaction(db_session, turn_id=turn.id, user_id=user.id).id
        == second.id
    )
