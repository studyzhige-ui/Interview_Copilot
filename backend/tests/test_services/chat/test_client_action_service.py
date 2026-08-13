from __future__ import annotations

import uuid

import pytest

from app.models.agent_execution import AgentToolCall
from app.models.chat import Conversation
from app.models.conversation_turn import ConversationTurn
from app.models.pending_submission import PendingSubmission
from app.models.user import User
from app.schemas.client_action import (
    MockClientActionResultRequest,
    MockPrefillPayload,
    MockReadinessPayload,
)
from app.services.chat.client_action_service import (
    ClientActionConflictError,
    ClientActionUnavailableError,
    create_mock_client_action,
    latest_handoff_client,
    pending_action_for_client,
    resolve_pending_action,
    sanitized_interaction_request,
    takeover_pending_action,
)


def _seed(db_session, *, source_client_id: str | None = "client-a"):
    suffix = uuid.uuid4().hex
    user = User(username=f"client-action-{suffix}", hashed_password="x")
    db_session.add(user)
    db_session.flush()
    conversation = Conversation(user_id=user.id, mode="agent")
    db_session.add(conversation)
    db_session.flush()
    submission = PendingSubmission(
        id=f"sub-{suffix}",
        conversation_id=conversation.id,
        user_id=user.id,
        version=1,
        position=1,
        status="claimed",
        message="start a mock interview",
        mode="agent",
        source_client_id=source_client_id,
    )
    db_session.add(submission)
    db_session.flush()
    turn = ConversationTurn(
        conversation_id=conversation.id,
        user_id=user.id,
        submission_id=submission.id,
        mode="agent",
        message=submission.message,
        status="waiting",
        waiting_reason="interaction",
    )
    db_session.add(turn)
    db_session.flush()
    conversation.active_turn_id = turn.id
    call = AgentToolCall(
        call_id="call-mock",
        turn_id=turn.id,
        session_id=conversation.id,
        user_id=user.id,
        tool_name="start_mock_interview",
        effect="client_action",
        arguments_json={},
        timeout_seconds=30,
        status="waiting",
    )
    db_session.add(call)
    db_session.flush()
    return user, conversation, turn


def test_action_is_durable_bound_replayable_and_explicitly_taken_over(db_session):
    user, conversation, turn = _seed(db_session)
    row, request = create_mock_client_action(
        db_session,
        turn=turn,
        tool_call_id="call-mock",
        action="mock_interview.prefill",
        payload=MockPrefillPayload(
            resume_id="resume-1",
            jd_text="A sufficiently explicit backend job description.",
            interviewer_style="professional",
            target_question_count=20,
        ),
        original_client_id="client-a",
        bound_client_id="client-a",
    )

    delivered = pending_action_for_client(
        db_session,
        session_id=conversation.id,
        turn_id=turn.id,
        user_id=user.id,
        client_id="client-a",
    )
    assert delivered is not None
    assert delivered.action_id == request.action_id
    assert delivered.payload.kind == "mock_prefill"
    assert (
        pending_action_for_client(
            db_session,
            session_id=conversation.id,
            turn_id=turn.id,
            user_id=user.id,
            client_id="other-tab",
        )
        is None
    )

    taken, replayed = takeover_pending_action(
        db_session,
        session_id=conversation.id,
        turn_id=turn.id,
        interaction_id=row.id,
        user_id=user.id,
        action_id=request.action_id,
        expected_version=1,
        client_id="client-b",
    )
    assert replayed is False
    assert taken.version == 2
    assert taken.request_json["original_client_id"] == "client-a"
    assert taken.request_json["bound_client_id"] == "client-b"
    assert taken.request_json["takeover_generation"] == 1

    same, replayed = takeover_pending_action(
        db_session,
        session_id=conversation.id,
        turn_id=turn.id,
        interaction_id=row.id,
        user_id=user.id,
        action_id=request.action_id,
        expected_version=1,
        client_id="client-b",
    )
    assert replayed is True
    assert same.version == 2
    assert (
        pending_action_for_client(
            db_session,
            session_id=conversation.id,
            turn_id=turn.id,
            user_id=user.id,
            client_id="client-a",
        )
        is None
    )


def test_client_result_is_bound_typed_and_exact_retry_is_idempotent(db_session):
    user, conversation, turn = _seed(db_session)
    row, request = create_mock_client_action(
        db_session,
        turn=turn,
        tool_call_id="call-mock",
        action="mock_interview.check_readiness",
        payload=MockReadinessPayload(),
        original_client_id="client-a",
        bound_client_id="client-a",
    )
    result = MockClientActionResultRequest(
        action_id=request.action_id,
        client_id="client-a",
        expected_version=1,
        outcome="acknowledged",
        readiness="ready",
    )

    accepted = resolve_pending_action(
        db_session,
        session_id=conversation.id,
        turn_id=turn.id,
        interaction_id=row.id,
        user_id=user.id,
        result=result,
    )
    assert accepted.replayed is False
    assert accepted.interaction.status == "resolved"
    assert accepted.interaction.resolution_json["outcome"] == "acknowledged"
    assert accepted.interaction.resolution_json["readiness"] == "ready"

    replay = resolve_pending_action(
        db_session,
        session_id=conversation.id,
        turn_id=turn.id,
        interaction_id=row.id,
        user_id=user.id,
        result=result,
    )
    assert replay.replayed is True
    assert replay.interaction.version == 2

    with pytest.raises(ClientActionConflictError, match="another result"):
        resolve_pending_action(
            db_session,
            session_id=conversation.id,
            turn_id=turn.id,
            interaction_id=row.id,
            user_id=user.id,
            result=MockClientActionResultRequest(
                action_id=request.action_id,
                client_id="client-a",
                expected_version=1,
                outcome="failed",
                reason="microphone disappeared",
            ),
        )


def test_readiness_ack_must_prove_ready_and_wrong_client_cannot_resolve(db_session):
    user, conversation, turn = _seed(db_session)
    row, request = create_mock_client_action(
        db_session,
        turn=turn,
        tool_call_id="call-mock",
        action="mock_interview.check_readiness",
        payload=MockReadinessPayload(),
        original_client_id="client-a",
        bound_client_id="client-a",
    )

    with pytest.raises(ClientActionConflictError, match="explicitly report ready"):
        resolve_pending_action(
            db_session,
            session_id=conversation.id,
            turn_id=turn.id,
            interaction_id=row.id,
            user_id=user.id,
            result=MockClientActionResultRequest(
                action_id=request.action_id,
                client_id="client-a",
                expected_version=1,
                outcome="acknowledged",
            ),
        )

    with pytest.raises(ClientActionConflictError, match="bound client"):
        resolve_pending_action(
            db_session,
            session_id=conversation.id,
            turn_id=turn.id,
            interaction_id=row.id,
            user_id=user.id,
            result=MockClientActionResultRequest(
                action_id=request.action_id,
                client_id="other-tab",
                expected_version=1,
                outcome="acknowledged",
                readiness="ready",
            ),
        )


def test_no_initiating_client_fails_without_creating_or_rebinding_action(db_session):
    _user, _conversation, turn = _seed(db_session, source_client_id=None)
    with pytest.raises(ClientActionUnavailableError, match="not initiated"):
        latest_handoff_client(
            db_session,
            turn=turn,
            tool_call_id="call-mock",
        )


def test_observer_projection_does_not_disclose_bound_payload(db_session):
    _user, _conversation, turn = _seed(db_session)
    row, request = create_mock_client_action(
        db_session,
        turn=turn,
        tool_call_id="call-mock",
        action="mock_interview.prefill",
        payload=MockPrefillPayload(
            resume_id="resume-secret",
            jd_text="A private and sufficiently long job description.",
            interviewer_style="professional",
            target_question_count=20,
        ),
        original_client_id="client-a",
        bound_client_id="client-a",
    )

    projection = sanitized_interaction_request(row)
    assert projection == {
        "protocol": "mock_handoff.v1",
        "action_id": request.action_id,
        "action": "mock_interview.prefill",
        "delivery": "bound_client_only",
    }
    assert "resume-secret" not in str(projection)
