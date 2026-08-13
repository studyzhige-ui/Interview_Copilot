from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.models.chat import Conversation
from app.models.conversation_turn import ConversationTurn
from app.models.gmail_integration import GmailIntegrationAccount
from app.models.gmail_observation import (
    GmailObservation,
    GmailObservationReviewCard,
    GmailObservationSnapshotImmutableError,
)
from app.models.job_opportunity import JobOpportunity, ProcessEvent
from app.models.persistent_task import PersistentTask, PersistentTaskTrigger
from app.models.user import User
from app.schemas.gmail_observation import (
    GmailIncrementalBatch,
    GmailIncrementalMessage,
    GmailObservationCardResolve,
    GmailObservationProposal,
    GmailObservationRetract,
)
from app.services import gmail_observation_service as service


NOW = datetime(2026, 8, 13, 8, 0, tzinfo=UTC)


def _user(db) -> User:
    user = User(username="gmail-observation-owner", hashed_password="x")
    db.add(user)
    db.flush()
    return user


def _account(db, user: User) -> GmailIntegrationAccount:
    row = GmailIntegrationAccount(
        user_id=user.id,
        google_subject="google-subject",
        account_hint="a***@gmail.com",
        scopes_json=["https://www.googleapis.com/auth/gmail.readonly"],
        credential_handle_ciphertext="encrypted",
        status="active",
        history_cursor="100",
    )
    db.add(row)
    db.flush()
    return row


def _task(db, user: User, *, auto_apply: bool) -> PersistentTask:
    conversation = Conversation(
        user_id=user.id,
        title="自动化 · Gmail",
        type="persistent_task",
        mode="agent",
    )
    db.add(conversation)
    db.flush()
    task = PersistentTask(
        user_id=user.id,
        conversation_id=conversation.id,
        title="Gmail 求职事件",
        instruction="处理新的求职邮件",
        state="active",
        version=1,
        trigger_kind="event",
        trigger_spec_json={
            "kind": "event",
            "connector": "gmail",
            "event_types": ["message_added"],
        },
        read_scope_json=["gmail:job_observations"],
        action_scope_json=([service.AUTO_APPLY_ACTION_SCOPE] if auto_apply else []),
        allowed_tool_names_json=[
            "read_career_context",
            "read_gmail_observations",
            "review_gmail_observation",
        ],
        user_request_identity="message:1",
        idempotency_key=f"task-{int(auto_apply)}",
        creation_fingerprint=f"fingerprint-{int(auto_apply)}",
    )
    db.add(task)
    db.flush()
    return task


def _opportunity(db, user: User, *, outcome: str | None = None) -> JobOpportunity:
    row = JobOpportunity(
        user_id=user.id,
        company_name="Example Corp",
        job_title="Backend Engineer",
        phase="applied",
        current_step="已确认投递",
        outcome=outcome,
    )
    db.add(row)
    db.flush()
    initial = ProcessEvent(
        job_opportunity_id=row.id,
        sequence=1,
        operation="assert",
        kind="application_submitted",
        occurred_at=NOW,
        observed_at=NOW,
        source_kind="user_assertion",
        source_identity="message:application",
        description="用户确认投递",
        idempotency_key="initial",
    )
    db.add(initial)
    db.flush()
    return row


def _intake(db, user: User, account: GmailIntegrationAccount):
    return service.persist_incremental_batch(
        db,
        user_pk=user.id,
        account_id=account.id,
        batch=GmailIncrementalBatch(
            cursor_before="100",
            cursor_after="102",
            messages=[
                GmailIncrementalMessage(
                    message_id="msg-1",
                    thread_id="thread-1",
                    history_id="101",
                    received_at=NOW,
                    from_hint="recruiting@example.com",
                    subject="Interview invitation",
                    snippet="Choose a time for your interview.",
                )
            ],
        ),
    )


def _bind_trigger(
    db, task: PersistentTask, observation: GmailObservation, turn_id: str
):
    turn = ConversationTurn(
        id=turn_id,
        conversation_id=task.conversation_id,
        user_id=task.user_id,
        mode="agent",
        execution_mode="auto",
        message="hidden automation input",
        status="completed",
    )
    db.add(turn)
    db.flush()
    trigger = PersistentTaskTrigger(
        persistent_task_id=task.id,
        kind="event",
        occurred_at=NOW,
        observed_at=NOW,
        source_identity=observation.id,
        source_version="101:v1",
        summary="untrusted Gmail observation",
        occurrence_fingerprint="x" * 64,
        idempotency_key=f"trigger-{task.id}",
        admitted_turn_id=turn_id,
        admitted_at=NOW,
    )
    db.add(trigger)
    db.flush()


def test_incremental_intake_is_deduped_and_cursor_is_atomic(db_session):
    user = _user(db_session)
    account = _account(db_session, user)
    first = _intake(db_session, user, account)
    assert len(first.observations) == 1
    assert len(first.snapshots) == 1
    assert account.history_cursor == "102"
    assert first.observations[0].version == 1

    with pytest.raises(service.GmailObservationConflictError):
        _intake(db_session, user, account)
    assert db_session.query(GmailObservation).count() == 1


def test_source_snapshot_is_append_only(db_session):
    user = _user(db_session)
    account = _account(db_session, user)
    snapshot = _intake(db_session, user, account).snapshots[0]

    snapshot.subject = "rewritten"
    with pytest.raises(GmailObservationSnapshotImmutableError):
        db_session.flush()


def test_ambiguous_observation_creates_task_local_card_not_process_event(db_session):
    user = _user(db_session)
    account = _account(db_session, user)
    task = _task(db_session, user, auto_apply=False)
    opportunity = _opportunity(db_session, user)
    observation = _intake(db_session, user, account).observations[0]
    _bind_trigger(db_session, task, observation, "turn-1")

    result = service.propose_observation(
        db_session,
        user_pk=user.id,
        task_id=task.id,
        automation_turn_id="turn-1",
        proposal=GmailObservationProposal(
            observation_id=observation.id,
            expected_version=1,
            disposition="needs_confirmation",
            event_kind="interview_scheduled",
            opportunity_id=opportunity.id,
            occurred_at=NOW,
            description="邮件看起来像面试邀请，但时间需确认。",
            confidence=0.78,
            unique_match=True,
            rationale="匹配岗位，但具体安排不够明确。",
        ),
    )

    assert result.outcome == "pending_confirmation"
    assert result.card is not None
    assert observation.status == "pending_confirmation"
    assert (
        db_session.query(ProcessEvent)
        .filter(ProcessEvent.kind == "interview_scheduled")
        .count()
        == 0
    )


def test_approved_card_applies_fact_and_retraction_preserves_history(db_session):
    user = _user(db_session)
    account = _account(db_session, user)
    task = _task(db_session, user, auto_apply=False)
    opportunity = _opportunity(db_session, user)
    observation = _intake(db_session, user, account).observations[0]
    _bind_trigger(db_session, task, observation, "turn-1")
    proposal = service.propose_observation(
        db_session,
        user_pk=user.id,
        task_id=task.id,
        automation_turn_id="turn-1",
        proposal=GmailObservationProposal(
            observation_id=observation.id,
            expected_version=1,
            disposition="needs_confirmation",
            event_kind="interview_scheduled",
            opportunity_id=opportunity.id,
            occurred_at=NOW,
            description="面试安排",
            confidence=0.8,
            unique_match=True,
            rationale="需用户确认。",
        ),
    )

    resolved = service.resolve_review_card(
        db_session,
        user_pk=user.id,
        task_id=task.id,
        card_id=proposal.card.id,
        command=GmailObservationCardResolve(
            expected_version=1,
            decision="approve",
            user_request_identity="message:approve",
        ),
    )
    assert resolved.process_event_id
    assert observation.status == "applied"
    assert proposal.card.status == "approved"

    correction = service.retract_applied_observation(
        db_session,
        user_pk=user.id,
        observation_id=observation.id,
        command=GmailObservationRetract(
            expected_version=observation.version,
            occurred_at=NOW,
            reason="用户确认邮件匹配错误",
            user_request_identity="message:retract",
        ),
    )
    assert correction.operation == "retract"
    assert correction.corrects_event_id == resolved.process_event_id
    assert observation.status == "retracted"
    assert (
        db_session.query(ProcessEvent)
        .filter(ProcessEvent.job_opportunity_id == opportunity.id)
        .count()
        == 3
    )


def test_auto_apply_requires_scope_unique_match_and_high_confidence(db_session):
    user = _user(db_session)
    account = _account(db_session, user)
    task = _task(db_session, user, auto_apply=True)
    opportunity = _opportunity(db_session, user)
    observation = _intake(db_session, user, account).observations[0]
    _bind_trigger(db_session, task, observation, "turn-1")

    result = service.propose_observation(
        db_session,
        user_pk=user.id,
        task_id=task.id,
        automation_turn_id="turn-1",
        proposal=GmailObservationProposal(
            observation_id=observation.id,
            expected_version=1,
            disposition="auto_apply",
            event_kind="interview_scheduled",
            opportunity_id=opportunity.id,
            occurred_at=NOW,
            description="招聘方明确安排面试",
            confidence=0.99,
            unique_match=True,
            rationale="申请号和岗位唯一匹配，语义明确。",
        ),
    )
    assert result.outcome == "applied"
    assert result.card is None
    assert observation.notification_summary


def test_auto_apply_to_archived_line_falls_back_to_card(db_session):
    user = _user(db_session)
    account = _account(db_session, user)
    task = _task(db_session, user, auto_apply=True)
    opportunity = _opportunity(db_session, user, outcome="rejected")
    observation = _intake(db_session, user, account).observations[0]
    _bind_trigger(db_session, task, observation, "turn-1")

    result = service.propose_observation(
        db_session,
        user_pk=user.id,
        task_id=task.id,
        automation_turn_id="turn-1",
        proposal=GmailObservationProposal(
            observation_id=observation.id,
            expected_version=1,
            disposition="auto_apply",
            event_kind="interview_scheduled",
            opportunity_id=opportunity.id,
            occurred_at=NOW,
            description="晚到的面试安排",
            confidence=0.99,
            unique_match=True,
            rationale="晚到消息不能自动恢复封存流程。",
        ),
    )
    assert result.outcome == "pending_confirmation"
    assert db_session.query(GmailObservationReviewCard).count() == 1


def test_new_opportunity_candidate_never_bypasses_reversible_review(db_session):
    user = _user(db_session)
    account = _account(db_session, user)
    task = _task(db_session, user, auto_apply=True)
    observation = _intake(db_session, user, account).observations[0]
    _bind_trigger(db_session, task, observation, "turn-1")

    result = service.propose_observation(
        db_session,
        user_pk=user.id,
        task_id=task.id,
        automation_turn_id="turn-1",
        proposal=GmailObservationProposal(
            observation_id=observation.id,
            expected_version=1,
            disposition="auto_apply",
            event_kind="application_submitted",
            new_opportunity={
                "company_name": "Example Corp",
                "job_title": "Backend Engineer",
                "application_provider": "greenhouse",
                "external_application_id": "application-1",
            },
            occurred_at=NOW,
            description="申请提交回执",
            confidence=0.99,
            unique_match=True,
            rationale="来源明确，但创建新岗位必须保留用户确认。",
        ),
    )

    assert result.outcome == "pending_confirmation"
    assert result.card is not None
    assert db_session.query(JobOpportunity).count() == 0
