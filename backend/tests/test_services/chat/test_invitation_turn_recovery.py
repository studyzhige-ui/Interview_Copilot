"""The production controller resumes only the original local invitation command.

The full strategy tests fake the final model response/catalog discovery only;
resume selection, policy, tool executor, and canonical domain writes are real.
"""

from datetime import timedelta
from types import SimpleNamespace

import pytest

from app.agent_runtime import tool_call_executor
from app.agent_runtime.tool_registry import registry
from app.agent_runtime.turn_tool_catalog import TurnToolCatalog
from app.agent_runtime.tools import interview_invitation as invitation_tool
from app.conversation import agent_strategy, context_store
from app.conversation.events import HarnessEvent
from app.conversation.strategy import StrategyContext, StrategyResult
from app.db.types import utc_now
from app.models.agent_execution import AgentToolCall
from app.models.agent_interaction import AgentInteraction
from app.models.conversation_turn import ConversationTurn
from app.models.interview_invitation import InterviewInvitationCandidate
from app.models.interview_record import InterviewRecord
from app.models.job_opportunity import NextAction, ProcessEvent
from app.models.model_dispatch import AgentModelDispatch
from app.schemas.interview_invitation import FactConfirmationResolution
from app.services.chat import turn_executor
from app.services.chat.interaction_service import resolve_interaction
from app.services.chat.invitation_turn_recovery import recover_invitation_turn
from tests.conftest import patch_session_locals
from tests.test_career.test_gmail_invitation_cutover import _proposal, _facts


def saved_decision(db, decision="correct_and_confirm"):
    user, observation, snapshot, proposal = _proposal(db)
    handoff = proposal.invitation_handoff
    interaction = db.get(AgentInteraction, handoff["interaction_id"])
    resolution = FactConfirmationResolution(
        decision=decision,
        opportunity={"kind": "create_new"} if decision != "reject" else None,
        corrected_facts=_facts() if decision == "correct_and_confirm" else None,
        reason="Not my interview" if decision == "reject" else None,
    )
    resolve_interaction(
        db,
        interaction_id=interaction.id,
        user_id=user.id,
        expected_version=interaction.version,
        status="rejected" if decision == "reject" else "resolved",
        resolution=resolution,
        resolution_identity="saved-exact-user-decision",
    )
    turn = db.get(ConversationTurn, handoff["turn_id"])
    turn.status = "running"
    turn.owner_id = "dead-worker"
    turn.waiting_reason = None
    turn.dispatch_generation = 2
    turn.heartbeat_at = utc_now() - timedelta(minutes=5)
    call = db.query(AgentToolCall).filter_by(turn_id=turn.id).one()
    call.status = "running"
    call.dispatch_generation = 2
    db.commit()
    return user, turn, call, interaction, handoff


def recover(db, turn):
    return recover_invitation_turn(
        db, turn_id=turn.id, stale_before=utc_now() - timedelta(minutes=1)
    )


@pytest.mark.parametrize("status", ["running", "unknown", "waiting", "completed"])
def test_recovers_exact_identity_without_writing_facts(db_session, status):
    user, turn, call, interaction, _ = saved_decision(db_session)
    call.status = status
    db_session.commit()
    before = (
        turn.id,
        call.call_id,
        call.arguments_json.copy(),
        interaction.resolution_identity,
    )
    assert recover(db_session, turn) == "pending"
    assert (
        turn.id,
        call.call_id,
        call.arguments_json,
        interaction.resolution_identity,
    ) == before
    assert turn.dispatch_generation == 3 and turn.owner_id is None
    assert turn.recovery_attempts == 1 and call.status == "waiting"
    assert db_session.query(InterviewRecord).count() == 0
    assert recover(db_session, turn) is None  # new dispatch age, not original input age


@pytest.mark.parametrize("model_status", ["running", "unknown", "cancelled"])
def test_unknown_model_cannot_be_resampled_by_invitation_repair(
    db_session, model_status
):
    user, turn, call, _, _ = saved_decision(db_session)
    db_session.add(
        AgentModelDispatch(
            call_id="unsettled",
            turn_id=turn.id,
            user_id=user.id,
            dispatch_generation=2,
            provider="test",
            model="test",
            request_fingerprint="a" * 64,
            status=model_status,
            started_at=call.started_at - timedelta(seconds=1),
        )
    )
    db_session.commit()
    assert recover(db_session, turn) is None
    assert turn.dispatch_generation == 2 and call.status == "running"


def test_does_not_resample_a_completed_answer_after_the_tool(db_session):
    user, turn, call, _, _ = saved_decision(db_session)
    call.status = "completed"
    db_session.add(
        AgentModelDispatch(
            call_id="completed-answer",
            turn_id=turn.id,
            user_id=user.id,
            dispatch_generation=2,
            provider="test",
            model="test",
            request_fingerprint="b" * 64,
            status="completed",
            started_at=call.started_at + timedelta(seconds=1),
        )
    )
    db_session.commit()
    assert recover(db_session, turn) is None


@pytest.mark.parametrize(
    "unsafe",
    ["external", "provider", "tail", "decision", "limit", "fresh", "transcript"],
)
def test_unsafe_recovery_does_not_clear_a_fence(db_session, unsafe, monkeypatch):
    _, turn, call, interaction, _ = saved_decision(db_session)
    if unsafe == "external":
        call.effect = "external_write"
    if unsafe == "provider":
        call.provider_identity = "remote"
    if unsafe == "tail":
        db_session.add(
            AgentToolCall(
                call_id="tail",
                turn_id=turn.id,
                session_id=turn.conversation_id,
                user_id=turn.user_id,
                tool_name="gmail_send",
                effect="external_write",
                status="deferred",
                timeout_seconds=30,
            )
        )
    if unsafe == "decision":
        interaction.resolution_identity = None
    if unsafe == "limit":
        turn.recovery_attempts = 3
    if unsafe == "fresh":
        turn.heartbeat_at = utc_now()
    if unsafe == "transcript":
        turn.assistant_message_seq = 1
    db_session.commit()
    assert recover(db_session, turn) is None
    assert turn.dispatch_generation == 2 and call.status == "running"


def test_pending_confirmation_restores_wait_without_inventing_decision(db_session):
    _, turn, call, interaction, _ = saved_decision(db_session)
    interaction.status = "pending"
    interaction.resolution_json = None
    interaction.resolution_identity = None
    interaction.resolved_at = None
    db_session.commit()
    assert recover(db_session, turn) == "waiting"
    assert turn.waiting_reason == "interaction"
    assert interaction.status == "pending" and call.status == "waiting"
    assert db_session.query(InterviewRecord).count() == 0


def test_stale_worker_cannot_heartbeat_wait_finish_or_write_transcript(
    db_session, monkeypatch
):
    from app.services.chat import chat_history_service
    from app.services.chat.chat_history_service import transcript_service

    user, turn, _, _, _ = saved_decision(db_session)
    patch_session_locals(monkeypatch, db_session, turn_executor, chat_history_service)
    turn.owner_id = turn_executor._WORKER_ID
    db_session.commit()
    assert recover(db_session, turn) == "pending"
    turn.status = "running"
    turn.owner_id = turn_executor._WORKER_ID  # even same prefork owner must be fenced
    db_session.commit()
    assert not turn_executor._heartbeat(turn.id, 2)
    assert not turn_executor._wait(turn.id, expected_generation=2)
    assert not turn_executor._finish(turn.id, "completed", expected_generation=2)
    with pytest.raises(ValueError, match="stale_turn_transcript_generation"):
        transcript_service.complete_background_turn(
            turn_id=turn.id,
            ai_msg="stale",
            expected_generation=2,
        )
    assert turn.status == "running" and turn.assistant_message_seq is None
    assert turn_executor._heartbeat(turn.id, 3)


async def execute_real_resume(db, monkeypatch, user, turn):
    patch_session_locals(
        monkeypatch,
        db,
        agent_strategy,
        invitation_tool,
        tool_call_executor,
        context_store,
    )
    catalog = TurnToolCatalog(
        builtins=registry.snapshot(),
        excluded=frozenset(),
        user_id=user.username,
        user_pk=user.id,
        session_id=turn.conversation_id,
        turn_id=turn.id,
        skills=(),
        mcp_tools=(),
        mcp_configs={},
        dispatch_generation=turn.dispatch_generation,
    )

    async def create(*args, **kwargs):
        return catalog

    monkeypatch.setattr(agent_strategy.TurnToolCatalog, "create", create)
    profile = SimpleNamespace(
        model="stub",
        max_output_tokens=4096,
        context_window=128000,
        supports_function_calling=True,
    )
    monkeypatch.setattr(
        agent_strategy,
        "build_async_openai_client_for_role",
        lambda *a, **k: (object(), profile),
    )

    async def final_text(self, **kwargs):
        yield HarnessEvent.text(
            "The canonical decision receipt has been recorded.", step=1, elapsed_ms=0
        )

    monkeypatch.setattr(agent_strategy.AgentLoopStrategy, "_loop", final_text)
    ctx = StrategyContext(
        user_id=user.username,
        user_pk=user.id,
        session_id=turn.conversation_id,
        turn_id=turn.id,
        user_message=turn.message,
        dispatch_generation=turn.dispatch_generation,
    )
    result = StrategyResult()
    events = [
        event async for event in agent_strategy.AgentLoopStrategy().execute(ctx, result)
    ]
    return result, events


@pytest.mark.asyncio
@pytest.mark.parametrize("decision", ["correct_and_confirm", "reject"])
async def test_full_strategy_applies_fact_rejection_and_replays_committed_receipt(
    db_session, monkeypatch, decision
):
    user, turn, call, interaction, handoff = saved_decision(db_session, decision)
    assert recover(db_session, turn) == "pending"
    turn.status = "running"
    db_session.commit()
    before_events = db_session.query(ProcessEvent).count()
    result, events = await execute_real_resume(db_session, monkeypatch, user, turn)
    db_session.expire_all()
    candidate = db_session.get(InterviewInvitationCandidate, handoff["candidate_id"])
    assert candidate.status == ("rejected" if decision == "reject" else "confirmed"), (
        call.result_json
    )
    assert call.status == "completed", call.result_json
    assert db_session.query(InterviewRecord).count() == (
        0 if decision == "reject" else 1
    )
    assert db_session.query(ProcessEvent).count() == before_events + (
        0 if decision == "reject" else 1
    )
    assert db_session.query(NextAction).count() == 0
    # Simulate worker loss AFTER commit/ToolCall completion but BEFORE transcript.
    turn.heartbeat_at = utc_now() - timedelta(minutes=5)
    db_session.commit()
    assert recover(db_session, turn) == "pending"
    turn.status = "running"
    db_session.commit()
    await execute_real_resume(db_session, monkeypatch, user, turn)
    assert db_session.query(InterviewRecord).count() == (
        0 if decision == "reject" else 1
    )
    assert db_session.query(ProcessEvent).count() == before_events + (
        0 if decision == "reject" else 1
    )
    assert interaction.resolution_identity == "saved-exact-user-decision"
