"""The real Gmail proposal owner cannot bypass typed invitation confirmation."""

from datetime import timedelta

import pytest

from app.career.application import gmail_invitation_adapter as adapter
from app.career.application.interview_invitation_operations import (
    InvitationOwnershipError,
    InvitationPolicyDeniedError,
    confirm_interview_invitation,
)
from app.models.agent_interaction import AgentInteraction
from app.models.interview_invitation import InterviewInvitationCandidate
from app.models.interview_record import InterviewRecord
from app.models.job_opportunity import NextAction, ProcessEvent
from app.schemas.interview_invitation import (
    CandidateConfirmationBasis,
    ConfirmInterviewInvitation,
    CreateOpportunity,
    FactConfirmationRequest,
    FactConfirmationResolution,
    InterviewInvitationFacts,
)
from app.schemas.gmail_observation import GmailObservationProposal
from app.integrations.gmail import observations as gmail
from app.conversation.application.interaction_service import InteractionConflictError
from app.conversation.application.interaction_service import resolve_interaction
from tests.test_services.test_gmail_observation_service import (
    NOW,
    _user,
    _account,
    _task,
    _opportunity,
    _intake,
    _bind_trigger,
)


def _proposal(db):
    user = _user(db)
    account = _account(db, user)
    task = _task(db, user, auto_apply=True)
    opportunity = _opportunity(db, user)
    batch = _intake(db, user, account)
    observation, snapshot = batch.observations[0], batch.snapshots[0]
    _bind_trigger(db, task, observation, "gmail-cutover-turn")
    before_events = db.query(ProcessEvent).count()
    result = gmail.propose_observation(
        db,
        user_pk=user.id,
        task_id=task.id,
        automation_turn_id="gmail-cutover-turn",
        proposal=GmailObservationProposal(
            observation_id=observation.id,
            expected_version=observation.version,
            disposition="auto_apply",
            event_kind="interview_scheduled",
            opportunity_id=opportunity.id,
            occurred_at=NOW,
            confidence=0.999,
            unique_match=True,
            description="High-confidence invitation but no source timezone.",
            rationale="A source observation is not a user decision.",
            invitation_facts={
                "company_name": "Example Corp",
                "job_title": "Backend Engineer",
            },
        ),
    )
    assert db.query(ProcessEvent).count() == before_events
    return user, observation, snapshot, result


def _facts():
    return InterviewInvitationFacts(
        company_name="Example Corp",
        job_title="Backend Engineer",
        scheduled_start_at=NOW + timedelta(days=2),
        source_timezone="UTC",
        original_time_text="August 15, 2026 08:00 UTC",
        stage_label="Technical interview",
        location="Video call",
    )


def test_high_confidence_and_auto_scope_only_create_a_waiting_candidate(db_session):
    user, observation, snapshot, result = _proposal(db_session)
    assert result.process_event_id is None and result.card is None
    handoff = result.invitation_handoff
    assert handoff["canonical_write"] is False
    row = db_session.get(AgentInteraction, handoff["interaction_id"])
    request = FactConfirmationRequest.model_validate(row.request_json)
    assert row.status == "pending"
    assert request.invitation_facts.scheduled_start_at is None
    assert request.invitation_facts.source_timezone is None
    assert request.missing_or_uncertain_fields
    assert request.source_and_evidence_references
    assert db_session.query(InterviewRecord).count() == 0
    assert db_session.query(NextAction).count() == 0
    again = adapter.route_gmail_invitation(
        db_session,
        user_pk=user.id,
        observation=observation,
        snapshot=snapshot,
        facts=None,
        confidence=0.5,
    )
    assert again["candidate_id"] == handoff["candidate_id"]
    assert again["interaction_id"] == handoff["interaction_id"]
    assert db_session.query(InterviewInvitationCandidate).count() == 1
    assert db_session.query(AgentInteraction).count() == 1


def test_missing_fields_reject_bare_confirm_but_accept_explicit_complete_correction(
    db_session,
):
    user, observation, snapshot, result = _proposal(db_session)
    handoff = result.invitation_handoff
    row = db_session.get(AgentInteraction, handoff["interaction_id"])
    bare = FactConfirmationResolution(
        decision="confirm", opportunity=CreateOpportunity(kind="create_new")
    )
    with pytest.raises(InteractionConflictError):
        resolve_interaction(
            db_session,
            interaction_id=row.id,
            user_id=user.id,
            expected_version=row.version,
            status="resolved",
            resolution=bare,
            resolution_identity="gmail-bare-confirm",
        )
    assert row.status == "pending"
    correction = FactConfirmationResolution(
        decision="correct_and_confirm",
        opportunity=CreateOpportunity(kind="create_new"),
        corrected_facts=_facts(),
    )
    version = row.version
    resolve_interaction(
        db_session,
        interaction_id=row.id,
        user_id=user.id,
        expected_version=version,
        status="resolved",
        resolution=correction,
        resolution_identity="gmail-explicit-correction",
    )
    command = ConfirmInterviewInvitation(
        idempotency_key="gmail-fact-confirm",
        actor_kind="agent_on_behalf",
        asserted_at=row.resolved_at,
        facts=_facts(),
        opportunity=CreateOpportunity(kind="create_new"),
        confirmation_basis=CandidateConfirmationBasis(
            kind="candidate_confirmation",
            candidate_id=handoff["candidate_id"],
            expected_candidate_version=handoff["candidate_version"],
            interaction_id=row.id,
            decision_identity=row.resolution_identity,
        ),
        causation={
            "conversation_id": handoff["conversation_id"],
            "turn_id": row.turn_id,
            "tool_call_id": row.request_json["context_package"]["tool_call_id"]
            if "tool_call_id" in row.request_json["context_package"]
            else "gmail-confirm-call",
        },
    )
    confirmed = confirm_interview_invitation(
        db_session, user_pk=user.id, command=command
    )
    assert confirmed.verification.conclusion == "verified"
    assert db_session.query(InterviewRecord).count() == 1
    assert db_session.query(NextAction).count() == 0
    again = adapter.route_gmail_invitation(
        db_session,
        user_pk=user.id,
        observation=observation,
        snapshot=snapshot,
        facts=None,
        confidence=1,
    )
    assert (
        gmail.get_observation(
            db_session, user_pk=user.id, observation_id=observation.id
        )["status"]
        == "applied"
    )
    assert again["candidate_status"] == "confirmed"
    assert again["interaction_id"] is None
    assert db_session.query(AgentInteraction).count() == 1


def test_saved_decision_cannot_authorize_different_invitation_facts(db_session):
    from tests.test_career.test_interview_invitation_operations import (
        _user as user_fixture,
        _source_and_candidate,
        _fact_interaction,
        _facts as full_facts,
    )

    user = user_fixture(db_session)
    _, _, candidate = _source_and_candidate(db_session, user)
    conversation, turn, interaction, decision = _fact_interaction(
        db_session, user, candidate, decision="confirm"
    )
    command = ConfirmInterviewInvitation(
        idempotency_key="tampered-confirm",
        actor_kind="agent_on_behalf",
        asserted_at=interaction.resolved_at,
        facts=full_facts(company_name="Not what user confirmed"),
        opportunity=CreateOpportunity(kind="create_new"),
        confirmation_basis=CandidateConfirmationBasis(
            kind="candidate_confirmation",
            candidate_id=candidate.id,
            expected_candidate_version=candidate.version,
            interaction_id=interaction.id,
            decision_identity=decision,
        ),
        causation={
            "conversation_id": conversation.id,
            "turn_id": turn.id,
            "tool_call_id": "tampered",
        },
    )
    with pytest.raises(InvitationPolicyDeniedError):
        confirm_interview_invitation(db_session, user_pk=user.id, command=command)
    assert db_session.query(InterviewRecord).count() == 0


def test_another_account_cannot_route_a_snapshot(db_session):
    user, observation, snapshot, _ = _proposal(db_session)
    from app.models.user import User

    other = User(username="another-owner", hashed_password="x")
    db_session.add(other)
    db_session.flush()
    with pytest.raises(InvitationOwnershipError):
        adapter.route_gmail_invitation(
            db_session,
            user_pk=other.id,
            observation=observation,
            snapshot=snapshot,
            facts=None,
            confidence=1,
        )


def test_retired_mutator_refuses_interview_scheduled(db_session):
    user, observation, snapshot, _ = _proposal(db_session)
    with pytest.raises(
        gmail.GmailObservationConflictError, match="requires_shared_operation"
    ):
        gmail._apply_candidate(
            db_session,
            user_pk=user.id,
            observation=observation,
            snapshot=snapshot,
            event_kind="interview_scheduled",
            opportunity_id=None,
            new_opportunity=None,
            occurred_at=NOW,
            description="must not write",
            step_summary=None,
        )
    assert db_session.query(InterviewRecord).count() == 0


def test_invitation_proposal_accepts_missing_business_match_without_invention():
    proposal = GmailObservationProposal(
        observation_id="source",
        expected_version=1,
        disposition="needs_confirmation",
        event_kind="interview_scheduled",
        rationale="Only an ambiguous mail snippet is available",
    )
    assert proposal.opportunity_id is None and proposal.new_opportunity is None
    assert proposal.occurred_at is None and proposal.invitation_facts is None
    with pytest.raises(ValueError):
        GmailObservationProposal(
            observation_id="source",
            expected_version=1,
            disposition="auto_apply",
            event_kind="assessment_invited",
            rationale="still needs a proper legacy event",
        )


@pytest.mark.parametrize("decision", ["correct_and_confirm", "reject"])
def test_source_replay_after_saved_decision_does_not_open_another_review(
    db_session, decision
):
    from app.models.conversation_turn import ConversationTurn

    user, observation, snapshot, result = _proposal(db_session)
    first = result.invitation_handoff
    interaction = db_session.get(AgentInteraction, first["interaction_id"])
    resolve_interaction(
        db_session,
        interaction_id=interaction.id,
        user_id=user.id,
        expected_version=interaction.version,
        status="rejected" if decision == "reject" else "resolved",
        resolution=FactConfirmationResolution(
            decision=decision,
            corrected_facts=_facts() if decision != "reject" else None,
            opportunity={"kind": "create_new"} if decision != "reject" else None,
        ),
        resolution_identity="retained-decision",
    )
    db_session.get(ConversationTurn, first["turn_id"]).status = "pending"
    db_session.commit()
    replay = adapter.route_gmail_invitation(
        db_session,
        user_pk=user.id,
        observation=observation,
        snapshot=snapshot,
        facts=None,
        confidence=None,
    )
    assert replay["interaction_id"] == first["interaction_id"]
    assert replay["turn_id"] == first["turn_id"]
    assert db_session.query(AgentInteraction).count() == 1
    assert (
        adapter.read_invitation_handoff(db_session, observation=observation)[
            "interaction_id"
        ]
        == first["interaction_id"]
    )
