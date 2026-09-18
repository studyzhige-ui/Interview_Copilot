from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta

from app.agent_runtime.tool_policy import ToolEffect
from app.agent_runtime.tool_registry import AgentToolContext, registry
from app.agent_runtime.tools import interview_invitation as tool_module
from app.agent_runtime.tools.interview_invitation import (
    ConfirmAssertedInterviewInvitationArgs,
    OpenInterviewPreparationArgs,
    ReviewInterviewInvitationCandidateArgs,
)
from app.models.agent_execution import AgentToolCall
from app.models.agent_interaction import AgentInteraction
from app.models.chat import Conversation, ConversationMessage
from app.models.conversation_turn import ConversationTurn
from app.models.interview_invitation import InterviewInvitationCandidate
from app.models.interview_record import InterviewRecord
from app.models.job_opportunity import NextAction, ProcessEvent
from app.models.pending_submission import PendingSubmission
from app.models.user import User
from app.schemas.agent_interaction import InteractionPayload
from app.schemas.client_action import MockClientActionResultRequest
from app.schemas.interview_invitation import InterviewInvitationFacts
from app.services.chat.interaction_service import resolve_interaction
from app.services.chat.client_action_service import resolve_pending_action


NOW = datetime(2026, 8, 26, 9, 0, tzinfo=UTC)


class _NoCloseSession:
    def __init__(self, inner):
        self._inner = inner

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def close(self):
        pass


def _seed_turn(db_session, message: str):
    user = User(
        username=f"invitation-tool-{uuid.uuid4().hex}",
        hashed_password="x",
    )
    db_session.add(user)
    db_session.flush()
    conversation = Conversation(user_id=user.id, mode="agent")
    db_session.add(conversation)
    db_session.flush()
    submission = PendingSubmission(
        id=f"submission-{uuid.uuid4().hex}",
        conversation_id=conversation.id,
        user_id=user.id,
        position=1,
        status="claimed",
        message=message,
        mode="agent",
        source_client_id="client-vs01",
    )
    db_session.add(submission)
    db_session.flush()
    user_message = ConversationMessage(
        conversation_id=conversation.id,
        seq=1,
        role="user",
        content=message,
    )
    db_session.add(user_message)
    db_session.flush()
    turn = ConversationTurn(
        conversation_id=conversation.id,
        user_id=user.id,
        submission_id=submission.id,
        mode="agent",
        message=message,
        user_message_seq=1,
        status="running",
    )
    db_session.add(turn)
    db_session.flush()
    return user, conversation, user_message, turn


def _facts() -> InterviewInvitationFacts:
    start = NOW + timedelta(days=2)
    return InterviewInvitationFacts(
        company_name="Example Corp",
        job_title="Backend Engineer",
        scheduled_start_at=start,
        scheduled_end_at=start + timedelta(hours=1),
        original_time_text="2026-08-28 17:00 Asia/Shanghai",
        source_timezone="Asia/Shanghai",
        stage_label="Technical Interview",
        location="Remote",
    )


def _hash(value) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def test_explicit_agent_tool_is_a_thin_verified_operation_adapter(
    db_session,
    monkeypatch,
) -> None:
    user, conversation, message, turn = _seed_turn(
        db_session,
        "我收到 Example Corp 后端工程师面试邀请，已安排在周五 17:00，请记录。",
    )
    monkeypatch.setattr(
        tool_module,
        "SessionLocal",
        lambda: _NoCloseSession(db_session),
    )
    ctx = AgentToolContext(
        user_id=user.username,
        user_pk=user.id,
        session_id=conversation.id,
        turn_id=turn.id,
        tool_call_id="call-confirm-invitation",
    )

    result = asyncio.run(
        tool_module._confirm_asserted_handler(
            ConfirmAssertedInterviewInvitationArgs(
                source_message_id=message.id,
                facts=_facts(),
                opportunity={"kind": "create_new"},
            ),
            ctx,
        )
    )

    assert result["verified"] is True
    assert db_session.query(InterviewRecord).count() == 1
    assert db_session.query(ProcessEvent).count() == 1
    assert db_session.query(NextAction).count() == 0
    definition = registry.get("confirm_interview_invitation")
    assert definition.effect is ToolEffect.INTERNAL_WRITE
    assert definition.task_authorizer(
        {}, ctx, "我收到面试邀请，时间已经安排，请确认记录"
    )


def test_candidate_tool_waits_for_typed_decision_then_resumes_same_call(
    db_session,
    monkeypatch,
) -> None:
    user, conversation, _message, turn = _seed_turn(
        db_session,
        "请核对这条面试邀请候选事实",
    )
    facts = _facts().model_dump(mode="json")
    source = {
        "kind": "user_message",
        "identity": f"conversation:{conversation.id}:message:1",
        "version": "1",
        "snapshot_id": None,
    }
    candidate = InterviewInvitationCandidate(
        user_id=user.id,
        source_kind="user_message",
        source_identity=source["identity"],
        source_version="1",
        status="pending_confirmation",
        version=1,
        facts_json=facts,
        field_provenance_json=[
            {
                "field_name": field,
                "source": source,
                "value_hash": _hash(value),
            }
            for field, value in facts.items()
            if value is not None
        ],
        missing_fields_json=[],
        conflicts_json=[],
        extractor_version="test.v1",
    )
    db_session.add(candidate)
    db_session.flush()
    call = AgentToolCall(
        call_id="call-review-candidate",
        turn_id=turn.id,
        session_id=conversation.id,
        user_id=user.id,
        tool_name="review_interview_invitation_candidate",
        effect="internal_write",
        arguments_json={
            "candidate_id": candidate.id,
            "expected_candidate_version": 1,
        },
        timeout_seconds=30,
        status="running",
        dispatch_generation=1,
        policy_decision="allow",
        policy_reason="task_authorized_internal_write",
    )
    db_session.add(call)
    db_session.flush()
    monkeypatch.setattr(
        tool_module,
        "SessionLocal",
        lambda: _NoCloseSession(db_session),
    )
    ctx = AgentToolContext(
        user_id=user.username,
        user_pk=user.id,
        session_id=conversation.id,
        turn_id=turn.id,
        tool_call_id=call.call_id,
    )
    args = ReviewInterviewInvitationCandidateArgs(
        candidate_id=candidate.id,
        expected_candidate_version=1,
    )

    waiting = asyncio.run(tool_module._review_candidate_handler(args, ctx))
    assert waiting["error"] == "interaction_required"
    interaction = db_session.query(AgentInteraction).one()
    assert db_session.query(InterviewRecord).count() == 0

    decision_identity = "decision:test-confirm"
    resolve_interaction(
        db_session,
        interaction_id=interaction.id,
        user_id=user.id,
        expected_version=interaction.version,
        status="resolved",
        resolution=InteractionPayload(
            root={
                "protocol": "interview_invitation.fact_confirmation.v1",
                "decision": "confirm",
                "opportunity": {"kind": "create_new"},
                "interview": {"kind": "create"},
            }
        ),
        resolution_identity=decision_identity,
    )
    # Simulate a worker/process boundary: only committed durable state may be
    # used by the resumed invocation, not Python objects from the first call.
    db_session.commit()
    db_session.expunge_all()
    resumed = asyncio.run(tool_module._review_candidate_handler(args, ctx))

    assert resumed["verified"] is True
    assert resumed["decision"] == "confirm"
    assert db_session.query(InterviewRecord).count() == 1
    assert db_session.query(NextAction).count() == 0
    replayed_resume = asyncio.run(tool_module._review_candidate_handler(args, ctx))
    assert (
        replayed_resume["operation"]["operation_id"]
        == resumed["operation"]["operation_id"]
    )
    assert db_session.query(InterviewRecord).count() == 1


def test_verified_invitation_handoff_uses_durable_client_action_without_domain_write(
    db_session,
    monkeypatch,
) -> None:
    user, conversation, message, turn = _seed_turn(
        db_session,
        "请记录这场面试，然后打开面试准备。",
    )
    monkeypatch.setattr(
        tool_module,
        "SessionLocal",
        lambda: _NoCloseSession(db_session),
    )
    confirm_context = AgentToolContext(
        user_id=user.username,
        user_pk=user.id,
        session_id=conversation.id,
        turn_id=turn.id,
        tool_call_id="call-confirm-before-open",
    )
    confirmed = asyncio.run(
        tool_module._confirm_asserted_handler(
            ConfirmAssertedInterviewInvitationArgs(
                source_message_id=message.id,
                facts=_facts(),
                opportunity={"kind": "create_new"},
            ),
            confirm_context,
        )
    )
    interview_ref = confirmed["operation"]["interview"]
    opportunity_ref = confirmed["operation"]["opportunity"]
    call = AgentToolCall(
        call_id="call-open-preparation",
        turn_id=turn.id,
        session_id=conversation.id,
        user_id=user.id,
        tool_name="open_interview_preparation",
        effect="client_action",
        arguments_json={
            "interview_id": interview_ref["id"],
            "expected_interview_version": interview_ref["version"],
        },
        timeout_seconds=30,
        status="running",
        dispatch_generation=1,
        policy_decision="allow",
        policy_reason="task_authorized_reversible_client_action",
    )
    db_session.add(call)
    db_session.flush()
    open_context = AgentToolContext(
        user_id=user.username,
        user_pk=user.id,
        session_id=conversation.id,
        turn_id=turn.id,
        tool_call_id=call.call_id,
    )
    args = OpenInterviewPreparationArgs(
        interview_id=interview_ref["id"],
        expected_interview_version=interview_ref["version"],
    )
    domain_counts = (
        db_session.query(InterviewRecord).count(),
        db_session.query(ProcessEvent).count(),
        db_session.query(NextAction).count(),
    )

    waiting = asyncio.run(tool_module._open_preparation_handler(args, open_context))

    assert waiting["error"] == "interaction_required"
    interaction = db_session.query(AgentInteraction).one()
    request = interaction.request_json
    assert request["protocol"] == "client_action.v1"
    assert request["action"] == "interview.preparation.open"
    assert request["payload"]["interview_id"] == interview_ref["id"]
    assert request["payload"]["opportunity_id"] == opportunity_ref["id"]

    resolve_pending_action(
        db_session,
        session_id=conversation.id,
        turn_id=turn.id,
        interaction_id=interaction.id,
        user_id=user.id,
        result=MockClientActionResultRequest(
            action_id=request["action_id"],
            client_id="client-vs01",
            expected_version=interaction.version,
            outcome="acknowledged",
        ),
    )
    resumed = asyncio.run(tool_module._open_preparation_handler(args, open_context))

    assert resumed["client_action_status"] == "acknowledged"
    assert resumed["opened"] is True
    assert domain_counts == (
        db_session.query(InterviewRecord).count(),
        db_session.query(ProcessEvent).count(),
        db_session.query(NextAction).count(),
    )
    definition = registry.get("open_interview_preparation")
    assert definition.effect is ToolEffect.CLIENT_ACTION
    assert definition.reversible is True
