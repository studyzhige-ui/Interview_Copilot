from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.agent_runtime.tool_registry import AgentToolContext
from app.agent_runtime.tools import mock_interview as tool_mod
from app.models.agent_execution import AgentToolCall
from app.models.chat import Conversation
from app.models.conversation_turn import ConversationTurn
from app.models.interview_record import InterviewRecord
from app.models.mock_interview_runtime import MockInterviewRuntime
from app.models.pending_submission import PendingSubmission
from app.models.user import User
from app.schemas.client_action import MockClientActionResultRequest
from app.services.chat.client_action_service import (
    find_mock_client_action,
    resolve_pending_action,
)
from tests.conftest import NoCloseSession


@pytest.mark.parametrize(
    ("task_text", "authorized"),
    [
        ("现在开始模拟面试", True),
        ("Please start a mock interview now", True),
        ("不要开始模拟面试", False),
        ("Do not start a mock interview", False),
        ("暂不进入模拟面试", False),
    ],
)
def test_mock_start_task_authorizer_fails_closed_on_refusal(task_text, authorized):
    assert (
        tool_mod._task_authorizes_mock_start({}, AgentToolContext("u", "s"), task_text)
        is authorized
    )


def _seed(db_session, *, client_id: str | None = "client-a"):
    suffix = uuid.uuid4().hex
    user = User(username=f"mock-tool-{suffix}", hashed_password="x")
    db_session.add(user)
    db_session.flush()
    conversation = Conversation(user_id=user.id, mode="agent", type="general")
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
        source_client_id=client_id,
    )
    db_session.add(submission)
    db_session.flush()
    turn = ConversationTurn(
        conversation_id=conversation.id,
        user_id=user.id,
        submission_id=submission.id,
        mode="agent",
        message=submission.message,
        status="running",
    )
    db_session.add(turn)
    db_session.flush()
    conversation.active_turn_id = turn.id
    db_session.add(
        AgentToolCall(
            call_id="call-mock",
            turn_id=turn.id,
            session_id=conversation.id,
            user_id=user.id,
            tool_name="start_mock_interview",
            effect="client_action",
            arguments_json={},
            timeout_seconds=30,
            status="running",
        )
    )
    db_session.flush()
    ctx = AgentToolContext(
        user_id=user.username,
        user_pk=user.id,
        session_id=conversation.id,
        turn_id=turn.id,
        tool_call_id="call-mock",
    )
    args = tool_mod.StartMockInterviewArgs(
        resume_id="resume-1",
        jd_text="A sufficiently explicit backend engineering job description.",
        interviewer_style="professional",
        target_question_count=20,
    )
    return user, conversation, turn, ctx, args


def _resolve_phase(
    db_session,
    *,
    turn,
    conversation,
    action,
    outcome="acknowledged",
    readiness=None,
    reason=None,
):
    found = find_mock_client_action(
        db_session,
        turn_id=turn.id,
        tool_call_id="call-mock",
        action=action,
    )
    assert found is not None
    row, request = found
    return resolve_pending_action(
        db_session,
        session_id=conversation.id,
        turn_id=turn.id,
        interaction_id=row.id,
        user_id=turn.user_id,
        result=MockClientActionResultRequest(
            action_id=request.action_id,
            client_id=request.bound_client_id,
            expected_version=row.version,
            outcome=outcome,
            readiness=readiness,
            reason=reason,
        ),
    )


def test_mock_tool_separates_three_client_results_from_runtime_proof(
    db_session, monkeypatch
):
    user, conversation, turn, ctx, args = _seed(db_session)
    monkeypatch.setattr(tool_mod, "SessionLocal", lambda: NoCloseSession(db_session))
    monkeypatch.setattr(
        tool_mod.mock_flow,
        "resolve_resume_context",
        lambda *_args, **_kwargs: "validated resume snapshot",
    )

    def fake_start_mock(db, **_kwargs):
        record = InterviewRecord(
            id=f"ir_{uuid.uuid4().hex[:12]}",
            user_id=user.id,
            source="mock",
            title="模拟面试",
            status="mock_in_progress",
        )
        live_conversation = Conversation(
            user_id=user.id,
            type="mock_interview",
            mode="chat",
            title="模拟面试",
            subject_type="interview_record",
            subject_id=record.id,
        )
        db.add_all([record, live_conversation])
        db.flush()
        runtime = MockInterviewRuntime(
            interview_record_id=record.id,
            user_id=user.id,
            conversation_id=live_conversation.id,
            current_stage_key="self_intro",
            current_question_message_id=1,
            plan_json=[],
            interviewer_style="professional",
            target_question_count=20,
        )
        db.add(runtime)
        db.flush()
        return SimpleNamespace(
            record=record,
            conversation=live_conversation,
            runtime=runtime,
        )

    monkeypatch.setattr(tool_mod.mock_flow, "start_mock", fake_start_mock)

    prefill_wait = tool_mod._run_start_mock(args, ctx)
    assert prefill_wait["error"] == "interaction_required"
    assert prefill_wait["action"] == "mock_interview.prefill"
    assert "runtime" not in prefill_wait

    _resolve_phase(
        db_session,
        turn=turn,
        conversation=conversation,
        action="mock_interview.prefill",
    )
    readiness_wait = tool_mod._run_start_mock(args, ctx)
    assert readiness_wait["action"] == "mock_interview.check_readiness"
    assert mock_runtime_count(db_session, user.id) == 0

    _resolve_phase(
        db_session,
        turn=turn,
        conversation=conversation,
        action="mock_interview.check_readiness",
        readiness="ready",
    )
    enter_wait = tool_mod._run_start_mock(args, ctx)
    assert enter_wait["action"] == "mock_interview.enter_live"
    assert enter_wait["runtime"]["status"] == "mock_in_progress"
    assert mock_runtime_count(db_session, user.id) == 1

    _resolve_phase(
        db_session,
        turn=turn,
        conversation=conversation,
        action="mock_interview.enter_live",
    )
    completed = tool_mod._run_start_mock(args, ctx)
    assert completed["handoff"] == "completed"
    assert completed["ui_entered"] is True
    assert completed["runtime"]["status"] == "mock_in_progress"
    assert mock_runtime_count(db_session, user.id) == 1


def mock_runtime_count(db_session, user_id: int) -> int:
    return (
        db_session.query(MockInterviewRuntime)
        .filter(MockInterviewRuntime.user_id == user_id)
        .count()
    )


def test_prefill_refusal_is_not_reported_as_runtime_success(db_session, monkeypatch):
    user, conversation, turn, ctx, args = _seed(db_session)
    monkeypatch.setattr(tool_mod, "SessionLocal", lambda: NoCloseSession(db_session))
    monkeypatch.setattr(
        tool_mod.mock_flow,
        "resolve_resume_context",
        lambda *_args, **_kwargs: "validated resume snapshot",
    )
    tool_mod._run_start_mock(args, ctx)
    _resolve_phase(
        db_session,
        turn=turn,
        conversation=conversation,
        action="mock_interview.prefill",
        outcome="refused",
        reason="keep this page open",
    )

    result = tool_mod._run_start_mock(args, ctx)
    assert result["error"] == "client_action_refused"
    assert result["phase"] == "prefill"
    assert "runtime" not in result
    assert mock_runtime_count(db_session, user.id) == 0


def test_mock_tool_rejects_unowned_job_before_client_action(db_session, monkeypatch):
    _user, conversation, turn, ctx, args = _seed(db_session)
    args = args.model_copy(update={"job_opportunity_id": "jo_unowned"})
    monkeypatch.setattr(tool_mod, "SessionLocal", lambda: NoCloseSession(db_session))
    monkeypatch.setattr(
        tool_mod.mock_flow,
        "resolve_resume_context",
        lambda *_args, **_kwargs: "validated resume snapshot",
    )

    def reject_job(*_args, **_kwargs):
        raise tool_mod.InterviewOpportunityNotFoundError("jo_unowned")

    monkeypatch.setattr(
        tool_mod.interview_record_service,
        "require_owned_job_opportunity",
        reject_job,
    )

    result = tool_mod._run_start_mock(args, ctx)

    assert result["error"] == "job_opportunity_not_found"
    assert (
        find_mock_client_action(
            db_session,
            turn_id=turn.id,
            tool_call_id="call-mock",
            action="mock_interview.prefill",
        )
        is None
    )
    assert conversation.active_turn_id == turn.id


def test_mock_tool_without_initiating_client_fails_honestly(db_session, monkeypatch):
    _user, _conversation, _turn, ctx, args = _seed(db_session, client_id=None)
    monkeypatch.setattr(tool_mod, "SessionLocal", lambda: NoCloseSession(db_session))

    result = tool_mod._run_start_mock(args, ctx)

    assert result["error"] == "client_action_unavailable"
    assert "not initiated" in result["reason"]
