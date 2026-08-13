from __future__ import annotations

from datetime import timedelta

import pytest

from app.db.types import utc_now
from app.models.agent_execution import AgentToolCall
from app.models.chat import Conversation, ConversationMessage
from app.models.conversation_deletion_receipt import ConversationDeletionReceipt
from app.models.conversation_turn import ConversationTurn
from app.models.pending_submission import PendingSubmission
from app.models.user import User
from app.services.chat.conversation_deletion_service import (
    ConversationDeletionConflictError,
    delete_conversation,
    purge_expired_conversation_deletion_receipts,
    preview_conversation_deletion,
    settle_deleted_conversation_receipt,
)


def _user(db_session) -> User:
    row = User(username="conversation-delete-owner", hashed_password="x")
    db_session.add(row)
    db_session.flush()
    return row


def test_delete_fences_active_turn_and_preserves_only_receipt_correlation(db_session):
    user = _user(db_session)
    conversation = Conversation(
        id="delete-with-unknown",
        user_id=user.id,
        title="有未结算调用",
        type="general",
        mode="agent",
        active_turn_id="delete-turn",
    )
    turn = ConversationTurn(
        id="delete-turn",
        conversation_id=conversation.id,
        user_id=user.id,
        mode="agent",
        message="发送申请",
        status="running",
        owner_id="worker-1",
    )
    call = AgentToolCall(
        call_id="external-call-1",
        turn_id=turn.id,
        session_id=conversation.id,
        user_id=user.id,
        tool_name="submit_application",
        effect="external_write",
        arguments_json={"secret": "must-not-survive", "content": "private"},
        timeout_seconds=30,
        status="running",
        dispatch_generation=1,
        policy_decision="allow",
        policy_reason="confirmed",
        result_json={
            "request_id": "provider-request-1",
            "receipt": {"receipt_id": "receipt-1", "body": "private"},
            "raw_response": "must-not-survive",
        },
    )
    db_session.add_all(
        [
            conversation,
            turn,
            call,
            ConversationMessage(
                conversation_id=conversation.id,
                seq=1,
                role="User",
                content="发送申请",
            ),
        ]
    )
    db_session.flush()
    impact = preview_conversation_deletion(
        db_session,
        user_pk=user.id,
        conversation_id=conversation.id,
    )

    execution = delete_conversation(
        db_session,
        user_pk=user.id,
        conversation_id=conversation.id,
        confirmation_token=impact.confirmation_token,
        confirm_conversation_id=conversation.id,
    )
    db_session.commit()

    assert execution.cancelled_turn_id == turn.id
    assert execution.result.receipt_tombstones == 1
    assert db_session.get(Conversation, conversation.id) is None
    assert db_session.get(ConversationTurn, turn.id) is None
    assert db_session.query(AgentToolCall).count() == 0
    tombstone = db_session.query(ConversationDeletionReceipt).one()
    assert tombstone.status == "unknown"
    assert tombstone.correlation_json == {
        "request_id": "provider-request-1",
        "receipt": {"receipt_id": "receipt-1"},
    }
    serialized = str(tombstone.correlation_json)
    assert "must-not-survive" not in serialized
    assert "private" not in serialized

    assert settle_deleted_conversation_receipt(
        db_session,
        user_pk=user.id,
        deleted_conversation_id=conversation.id,
        turn_id=turn.id,
        call_id=call.call_id,
        status="completed",
        correlation={
            "provider_receipt_id": "final-receipt",
            "raw_response": "must-not-survive",
        },
    )
    db_session.commit()
    db_session.refresh(tombstone)
    assert tombstone.status == "completed"
    assert tombstone.correlation_json == {"provider_receipt_id": "final-receipt"}
    assert tombstone.retain_until == tombstone.resolved_at
    assert db_session.get(Conversation, conversation.id) is None
    assert db_session.query(AgentToolCall).count() == 0


def test_delete_requires_fresh_impact_after_queue_changes(db_session):
    user = _user(db_session)
    conversation = Conversation(
        id="stale-impact",
        user_id=user.id,
        title="stale",
        type="general",
    )
    db_session.add(conversation)
    db_session.flush()
    impact = preview_conversation_deletion(
        db_session,
        user_pk=user.id,
        conversation_id=conversation.id,
    )
    db_session.add(
        PendingSubmission(
            id="queued-after-preview",
            conversation_id=conversation.id,
            user_id=user.id,
            position=1,
            message="new input",
            mode="chat",
        )
    )
    db_session.flush()

    with pytest.raises(ConversationDeletionConflictError):
        delete_conversation(
            db_session,
            user_pk=user.id,
            conversation_id=conversation.id,
            confirmation_token=impact.confirmation_token,
            confirm_conversation_id=conversation.id,
        )

    assert db_session.get(Conversation, conversation.id) is conversation


def test_receipt_purge_removes_expired_only_and_is_idempotent(db_session):
    user = _user(db_session)
    now = utc_now()
    expired = ConversationDeletionReceipt(
        id="cdr-expired",
        user_id=user.id,
        deleted_conversation_id="deleted-expired",
        turn_id="turn-expired",
        call_id="call-expired",
        tool_name="send_email",
        effect="external_write",
        dispatch_generation=1,
        status="completed",
        correlation_json={"receipt_id": "expired"},
        resolved_at=now - timedelta(minutes=1),
        retain_until=now - timedelta(seconds=1),
    )
    unknown_retained = ConversationDeletionReceipt(
        id="cdr-unknown-retained",
        user_id=user.id,
        deleted_conversation_id="deleted-unknown",
        turn_id="turn-unknown",
        call_id="call-unknown",
        tool_name="submit_application",
        effect="external_write",
        dispatch_generation=1,
        status="unknown",
        correlation_json={"request_id": "still-reconciling"},
        retain_until=now + timedelta(days=30),
    )
    db_session.add_all([expired, unknown_retained])
    db_session.flush()

    assert (
        purge_expired_conversation_deletion_receipts(
            db_session,
            due_at=now,
            limit=100,
        )
        == 1
    )
    db_session.commit()
    assert db_session.get(ConversationDeletionReceipt, expired.id) is None
    assert db_session.get(ConversationDeletionReceipt, unknown_retained.id) is not None

    assert (
        purge_expired_conversation_deletion_receipts(
            db_session,
            due_at=now,
            limit=100,
        )
        == 0
    )
