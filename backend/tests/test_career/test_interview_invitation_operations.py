from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.career.application.catalog import (
    CAREER_OPERATION_CATALOG,
    OperationEffect,
)
from app.career.application.interview_invitation_context import (
    compile_invitation_confirmation_context,
)
from app.career.application.interview_invitation_operations import (
    InvitationIdempotencyConflictError,
    InvitationPolicyDeniedError,
    InvitationVersionConflictError,
    confirm_interview_invitation,
    get_interview_invitation_handoff,
    intake_interview_invitation_observation,
    register_interview_invitation_candidate,
    reject_interview_invitation_candidate,
)
from app.career.application.invitation_interaction import (
    create_invitation_fact_confirmation,
)
from app.models.agent_execution import AgentToolCall
from app.models.agent_interaction import AgentInteraction
from app.models.application_operation import (
    ApplicationOperation,
    CareerDomainEvent,
    OperationVerification,
)
from app.models.chat import Conversation
from app.models.conversation_turn import ConversationTurn
from app.models.interview_invitation import (
    InterviewInvitationCandidate,
    InterviewInvitationEvidenceRef,
    InterviewInvitationObservation,
    InterviewInvitationSourceSnapshot,
)
from app.models.interview_record import InterviewRecord
from app.models.job_opportunity import JobOpportunity, NextAction, ProcessEvent
from app.models.user import User
from app.schemas.agent_interaction import InteractionPayload
from app.schemas.interview_invitation import (
    CandidateConfirmationBasis,
    ConfirmInterviewInvitation,
    CreateOpportunity,
    ExplicitUserAssertionBasis,
    FactConfirmationRequest,
    FactConfirmationResolution,
    IntakeInterviewInvitationObservation,
    InterviewInvitationCandidateFacts,
    InterviewInvitationFacts,
    InvitationFieldEvidence,
    InvitationSourceReference,
    LinkExistingOpportunity,
    RegisterInterviewInvitationCandidate,
    RejectInterviewInvitationCandidate,
)
from app.schemas.job_opportunity import OpportunityCreate
from app.services.career_process_service import create_job_opportunity
from app.services.chat.interaction_service import (
    create_pending_interaction,
    resolve_interaction,
)


NOW = datetime(2026, 8, 26, 9, 0, tzinfo=UTC)
START = NOW + timedelta(days=2, hours=1)


def _user(db_session, label: str = "owner") -> User:
    user = User(
        username=f"vs01-{label}-{uuid.uuid4().hex}",
        hashed_password="test-hash",
    )
    db_session.add(user)
    db_session.flush()
    return user


def _hash(value) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _facts(**changes) -> InterviewInvitationFacts:
    values = {
        "company_name": "Example Corp",
        "job_title": "Backend Engineer",
        "scheduled_start_at": START,
        "scheduled_end_at": START + timedelta(hours=1),
        "original_time_text": "2026-08-28 18:00 Asia/Shanghai",
        "source_timezone": "Asia/Shanghai",
        "stage_label": "Technical Interview",
        "location": "Remote",
        "meeting_url": "https://meet.example.test/interview",
        "contact_name": "Recruiter",
        "contact_email": "recruiter@example.test",
    }
    values.update(changes)
    return InterviewInvitationFacts(**values)


def _explicit_command(
    *,
    key: str,
    facts: InterviewInvitationFacts | None = None,
    opportunity=None,
) -> ConfirmInterviewInvitation:
    return ConfirmInterviewInvitation(
        idempotency_key=key,
        actor_kind="user",
        asserted_at=NOW,
        confirmation_basis=ExplicitUserAssertionBasis(
            kind="explicit_user_assertion",
            source=InvitationSourceReference(
                kind="manual",
                identity=f"manual-form:{key}",
                version="1",
            ),
        ),
        facts=facts or _facts(),
        opportunity=opportunity or CreateOpportunity(kind="create_new"),
    )


def _existing_opportunity(db_session, user: User) -> JobOpportunity:
    admission = create_job_opportunity(
        db_session,
        user_pk=user.id,
        command=OpportunityCreate(
            company_name="Example Corp",
            job_title="Backend Engineer",
            entry_reason="explicit_tracking",
            occurred_at=NOW - timedelta(days=7),
            source_kind="user_assertion",
            source_identity=f"seed:{uuid.uuid4().hex}",
            source_description="User started tracking this opportunity",
            idempotency_key=f"seed-{uuid.uuid4().hex}",
        ),
    )
    return admission.opportunity


def _source_and_candidate(db_session, user: User):
    intake = intake_interview_invitation_observation(
        db_session,
        user_pk=user.id,
        command=IntakeInterviewInvitationObservation(
            idempotency_key=f"intake-{uuid.uuid4().hex}",
            actor_kind="automation",
            source_kind="fixture",
            source_identity=f"fixture-message-{uuid.uuid4().hex}",
            source_version="history-1",
            observed_at=NOW,
            payload={"subject": "Interview invitation", "snippet": "Friday 18:00"},
        ),
    )
    source = db_session.get(
        InterviewInvitationSourceSnapshot,
        intake.source_snapshot_id,
    )
    facts = _facts().model_dump(mode="json")
    evidence = [
        InvitationFieldEvidence(
            field_name=field,
            source=InvitationSourceReference(
                kind="fixture",
                identity=source.source_identity,
                version=source.source_version,
                snapshot_id=source.id,
            ),
            value_hash=_hash(value),
        )
        for field, value in facts.items()
        if value is not None
    ]
    registered = register_interview_invitation_candidate(
        db_session,
        user_pk=user.id,
        command=RegisterInterviewInvitationCandidate(
            idempotency_key=f"candidate-{uuid.uuid4().hex}",
            actor_kind="automation",
            observation_id=intake.observation.id,
            expected_observation_version=intake.observation.version,
            source_kind="observation",
            source_identity=intake.observation.id,
            source_version=str(intake.observation.version),
            facts=InterviewInvitationCandidateFacts(**facts),
            field_provenance=evidence,
            confidence=0.94,
            extractor_version="fixture-parser.v1",
        ),
    )
    return intake, source, registered.candidate


def _fact_interaction(
    db_session,
    user: User,
    candidate,
    *,
    decision: str,
):
    candidate_row = db_session.get(InterviewInvitationCandidate, candidate.id)
    assert candidate_row is not None
    conversation = Conversation(user_id=user.id, mode="agent")
    db_session.add(conversation)
    db_session.flush()
    turn = ConversationTurn(
        conversation_id=conversation.id,
        user_id=user.id,
        mode="agent",
        message="Review the interview invitation",
        status="waiting",
        waiting_reason="interaction",
    )
    db_session.add(turn)
    db_session.flush()
    evidence = [
        InvitationFieldEvidence.model_validate(item)
        for item in candidate.field_provenance
    ]
    facts = InterviewInvitationCandidateFacts.model_validate(candidate.facts)
    context_package = compile_invitation_confirmation_context(
        db_session,
        user_pk=user.id,
        turn=turn,
        tool_call_id=f"test-review:{candidate.id}",
        candidate=candidate_row,
        facts=facts,
        evidence=evidence,
        opportunity_options=[],
    )
    row = create_pending_interaction(
        db_session,
        turn_id=turn.id,
        user_id=user.id,
        kind="fact_confirmation",
        schema_version=1,
        request=FactConfirmationRequest(
            candidate_reference={
                "kind": "interview_invitation_candidate",
                "id": candidate.id,
                "version": candidate.version,
            },
            expected_candidate_version=candidate.version,
            invitation_facts=facts,
            field_provenance=evidence,
            source_and_evidence_references=[evidence[0].source],
            context_package=context_package,
        ),
    )
    decision_identity = f"decision:{uuid.uuid4().hex}"
    resolved = resolve_interaction(
        db_session,
        interaction_id=row.id,
        user_id=user.id,
        expected_version=row.version,
        status="rejected" if decision == "reject" else "resolved",
        resolution=InteractionPayload(root={"decision": decision}),
        resolution_identity=decision_identity,
    )
    return conversation, turn, resolved, decision_identity


def test_catalog_exposes_shared_confirm_operation() -> None:
    definition = CAREER_OPERATION_CATALOG.get("confirm_interview_invitation", 1)
    assert definition.effect is OperationEffect.CANONICAL_WRITE
    assert definition.allowed_adapters == {"ui", "agent", "automation"}
    assert "interview_invitation_confirmed" in definition.domain_events


def test_operation_boundary_denies_automation_impersonating_user_assertion(
    db_session,
) -> None:
    user = _user(db_session)
    command = _explicit_command(key="automation-impersonation-1").model_copy(
        update={"actor_kind": "automation"}
    )

    with pytest.raises(InvitationPolicyDeniedError, match="cannot promote"):
        confirm_interview_invitation(db_session, user_pk=user.id, command=command)

    assert db_session.query(ApplicationOperation).count() == 0
    assert db_session.query(JobOpportunity).count() == 0


def test_intake_is_immutable_deduplicated_and_non_canonical(db_session) -> None:
    user = _user(db_session)
    command = IntakeInterviewInvitationObservation(
        idempotency_key="fixture-intake-1",
        actor_kind="automation",
        source_kind="fixture",
        source_identity="fixture-message-1",
        source_version="history-10",
        observed_at=NOW,
        payload={"subject": "Interview", "snippet": "Friday at 18:00"},
    )

    first = intake_interview_invitation_observation(
        db_session,
        user_pk=user.id,
        command=command,
    )
    second = intake_interview_invitation_observation(
        db_session,
        user_pk=user.id,
        command=command,
    )

    assert second.replayed is True
    assert first.source_snapshot_id == second.source_snapshot_id
    assert db_session.query(InterviewInvitationSourceSnapshot).count() == 1
    assert db_session.query(InterviewInvitationObservation).count() == 1
    assert db_session.query(JobOpportunity).count() == 0
    assert db_session.query(InterviewRecord).count() == 0
    assert db_session.query(ProcessEvent).count() == 0


def test_candidate_registration_remains_low_authority(db_session) -> None:
    user = _user(db_session)
    intake, _source, candidate = _source_and_candidate(db_session, user)

    assert candidate.status == "pending_confirmation"
    assert candidate.confirmed_operation_id is None
    observation = db_session.get(InterviewInvitationObservation, intake.observation.id)
    assert observation.status == "pending_confirmation"
    assert db_session.query(JobOpportunity).count() == 0
    assert db_session.query(InterviewRecord).count() == 0
    assert db_session.query(ProcessEvent).count() == 0


def test_explicit_confirmation_creates_atomic_verified_domain_state(db_session) -> None:
    user = _user(db_session)
    result = confirm_interview_invitation(
        db_session,
        user_pk=user.id,
        command=_explicit_command(key="confirm-create-1"),
    )

    opportunity = db_session.get(JobOpportunity, result.opportunity.id)
    interview = db_session.get(InterviewRecord, result.interview.id)
    process_event = db_session.get(ProcessEvent, result.process_event.id)
    operation = db_session.get(ApplicationOperation, result.operation_id)

    assert opportunity.phase == "in_process"
    assert opportunity.version >= 2
    assert interview.source == "invitation"
    assert interview.status == "scheduled"
    assert interview.job_opportunity_id == opportunity.id
    assert interview.scheduled_start_at == START
    assert interview.schedule_version == 1
    assert process_event.kind == "interview_scheduled"
    assert process_event.job_opportunity_id == opportunity.id
    assert operation.status == "succeeded"
    assert result.verification.conclusion == "verified"
    assert db_session.query(OperationVerification).count() == 1
    assert db_session.query(InterviewInvitationEvidenceRef).count() == 11
    assert db_session.query(CareerDomainEvent).count() == 5
    assert db_session.query(NextAction).count() == 0

    handoff = get_interview_invitation_handoff(
        db_session,
        user_pk=user.id,
        interview_id=interview.id,
    )
    assert handoff.opportunity.id == opportunity.id
    assert handoff.verification.conclusion == "verified"


def test_confirm_replay_does_not_duplicate_any_domain_record(db_session) -> None:
    user = _user(db_session)
    command = _explicit_command(key="confirm-replay-1")
    first = confirm_interview_invitation(
        db_session,
        user_pk=user.id,
        command=command,
    )
    counts = (
        db_session.query(JobOpportunity).count(),
        db_session.query(InterviewRecord).count(),
        db_session.query(ProcessEvent).count(),
        db_session.query(InterviewInvitationEvidenceRef).count(),
        db_session.query(CareerDomainEvent).count(),
    )

    replay = confirm_interview_invitation(
        db_session,
        user_pk=user.id,
        command=command,
    )

    assert replay.replayed is True
    assert replay.operation_id == first.operation_id
    assert counts == (
        db_session.query(JobOpportunity).count(),
        db_session.query(InterviewRecord).count(),
        db_session.query(ProcessEvent).count(),
        db_session.query(InterviewInvitationEvidenceRef).count(),
        db_session.query(CareerDomainEvent).count(),
    )


def test_idempotency_key_reuse_with_different_facts_is_rejected(db_session) -> None:
    user = _user(db_session)
    confirm_interview_invitation(
        db_session,
        user_pk=user.id,
        command=_explicit_command(key="confirm-conflict-1"),
    )

    with pytest.raises(InvitationIdempotencyConflictError):
        confirm_interview_invitation(
            db_session,
            user_pk=user.id,
            command=_explicit_command(
                key="confirm-conflict-1",
                facts=_facts(location="Different office"),
            ),
        )


def test_link_existing_requires_current_opportunity_version(db_session) -> None:
    user = _user(db_session)
    opportunity = _existing_opportunity(db_session, user)
    stale = LinkExistingOpportunity(
        kind="link_existing",
        opportunity_id=opportunity.id,
        expected_version=max(1, opportunity.version - 1),
    )

    with pytest.raises(InvitationVersionConflictError):
        confirm_interview_invitation(
            db_session,
            user_pk=user.id,
            command=_explicit_command(key="confirm-stale-1", opportunity=stale),
        )


def test_candidate_confirmation_records_decision_and_evidence(db_session) -> None:
    user = _user(db_session)
    intake, source, candidate = _source_and_candidate(db_session, user)
    conversation, turn, interaction, decision_identity = _fact_interaction(
        db_session,
        user,
        candidate,
        decision="correct_and_confirm",
    )
    opportunity = _existing_opportunity(db_session, user)
    command = ConfirmInterviewInvitation(
        idempotency_key="candidate-confirm-1",
        actor_kind="agent_on_behalf",
        asserted_at=NOW,
        confirmation_basis=CandidateConfirmationBasis(
            kind="candidate_confirmation",
            candidate_id=candidate.id,
            expected_candidate_version=candidate.version,
            interaction_id=interaction.id,
            decision_identity=decision_identity,
        ),
        facts=_facts(location="Corrected remote location"),
        opportunity=LinkExistingOpportunity(
            kind="link_existing",
            opportunity_id=opportunity.id,
            expected_version=opportunity.version,
        ),
        causation={
            "conversation_id": conversation.id,
            "turn_id": turn.id,
            "tool_call_id": "test-confirm-invitation",
        },
    )

    result = confirm_interview_invitation(
        db_session,
        user_pk=user.id,
        command=command,
    )

    candidate_row = db_session.get(InterviewInvitationCandidate, candidate.id)
    observation = db_session.get(InterviewInvitationObservation, intake.observation.id)
    interview = db_session.get(InterviewRecord, result.interview.id)
    assert candidate_row.status == "confirmed"
    assert candidate_row.version == 2
    assert candidate_row.resolved_by_interaction_id == interaction.id
    assert observation.status == "confirmed"
    assert interview.invitation_source_identity == decision_identity
    assert interview.scheduled_location == "Corrected remote location"
    assert source.id is not None


def test_reject_candidate_has_zero_canonical_side_effects(db_session) -> None:
    user = _user(db_session)
    intake, _source, candidate = _source_and_candidate(db_session, user)
    conversation, turn, interaction, decision_identity = _fact_interaction(
        db_session,
        user,
        candidate,
        decision="reject",
    )
    result = reject_interview_invitation_candidate(
        db_session,
        user_pk=user.id,
        command=RejectInterviewInvitationCandidate(
            idempotency_key="candidate-reject-1",
            actor_kind="agent_on_behalf",
            candidate_id=candidate.id,
            expected_candidate_version=candidate.version,
            interaction_id=interaction.id,
            decision_identity=decision_identity,
            reason="This invitation belongs to another person",
            causation={
                "conversation_id": conversation.id,
                "turn_id": turn.id,
            },
        ),
    )

    candidate_row = db_session.get(InterviewInvitationCandidate, candidate.id)
    observation = db_session.get(InterviewInvitationObservation, intake.observation.id)
    assert result.verification.conclusion == "verified"
    assert candidate_row.status == "rejected"
    assert observation.status == "rejected"
    assert db_session.query(JobOpportunity).count() == 0
    assert db_session.query(InterviewRecord).count() == 0
    assert db_session.query(ProcessEvent).count() == 0
    assert db_session.query(NextAction).count() == 0


def test_candidate_fact_interaction_is_owner_scoped(db_session) -> None:
    owner = _user(db_session, "owner")
    other = _user(db_session, "other")
    _intake, _source, candidate = _source_and_candidate(db_session, owner)
    _conversation, _turn, interaction, decision_identity = _fact_interaction(
        db_session,
        owner,
        candidate,
        decision="confirm",
    )
    command = ConfirmInterviewInvitation(
        idempotency_key="foreign-confirm-1",
        actor_kind="user",
        asserted_at=NOW,
        confirmation_basis=CandidateConfirmationBasis(
            kind="candidate_confirmation",
            candidate_id=candidate.id,
            expected_candidate_version=candidate.version,
            interaction_id=interaction.id,
            decision_identity=decision_identity,
        ),
        facts=_facts(),
        opportunity=CreateOpportunity(kind="create_new"),
    )

    with pytest.raises(Exception) as exc_info:
        confirm_interview_invitation(
            db_session,
            user_pk=other.id,
            command=command,
        )
    assert "candidate" in str(exc_info.value)
    assert db_session.query(JobOpportunity).count() == 0


def test_fact_confirmation_schema_is_durable(db_session) -> None:
    user = _user(db_session)
    _intake, _source, candidate = _source_and_candidate(db_session, user)
    _conversation, _turn, interaction, decision_identity = _fact_interaction(
        db_session,
        user,
        candidate,
        decision="confirm",
    )

    row = db_session.get(AgentInteraction, interaction.id)
    assert row.kind == "fact_confirmation"
    assert row.schema_version == 1
    assert row.resolution_identity == decision_identity


def test_fact_confirmation_request_contains_candidate_evidence_and_options(
    db_session,
) -> None:
    user = _user(db_session)
    _intake, _source, candidate = _source_and_candidate(db_session, user)
    opportunity = _existing_opportunity(db_session, user)
    conversation = Conversation(user_id=user.id, mode="agent")
    db_session.add(conversation)
    db_session.flush()
    turn = ConversationTurn(
        conversation_id=conversation.id,
        user_id=user.id,
        mode="agent",
        message="Review the invitation candidate",
        status="running",
    )
    db_session.add(turn)
    db_session.flush()
    tool_call = AgentToolCall(
        call_id="call-review-invitation",
        turn_id=turn.id,
        session_id=conversation.id,
        user_id=user.id,
        tool_name="review_interview_invitation_candidate",
        effect="internal_write",
        arguments_json={
            "candidate_id": candidate.id,
            "expected_candidate_version": candidate.version,
        },
        timeout_seconds=30,
        status="running",
        dispatch_generation=1,
        policy_decision="allow",
        policy_reason="task_authorized_internal_write",
    )
    db_session.add(tool_call)
    db_session.flush()

    interaction = create_invitation_fact_confirmation(
        db_session,
        user_pk=user.id,
        turn_id=turn.id,
        tool_call_id=tool_call.call_id,
        candidate_id=candidate.id,
        expected_candidate_version=candidate.version,
    )
    request = FactConfirmationRequest.model_validate(interaction.request_json)

    assert request.candidate_reference.id == candidate.id
    assert request.expected_candidate_version == candidate.version
    assert len(request.field_provenance) == 11
    assert len(request.source_and_evidence_references) == 1
    assert request.opportunity_match_options[0].opportunity_id == opportunity.id
    package = request.context_package
    assert package.user_scope == str(user.id)
    assert package.turn_id == turn.id
    assert [item.model_dump() for item in package.object_scope] == [
        {
            "kind": "interview_invitation_candidate",
            "id": candidate.id,
            "version": candidate.version,
        },
        {
            "kind": "job_opportunity",
            "id": opportunity.id,
            "version": opportunity.version,
        },
    ]
    assert {section.role for section in package.sections} == {
        "observation_candidate",
        "source_evidence",
        "canonical_state",
        "runtime_controls",
    }
    assert package.policy_scope.execution_time_policy_recheck is True
    assert len(package.source_manifest) == 1
    assert len(package.source_manifest[0].content_hash) == 64
    serialized_package = package.model_dump_json()
    assert "raw_payload" not in serialized_package
    assert "payload_json" not in serialized_package
    assert db_session.query(InterviewRecord).count() == 0
    assert db_session.query(ProcessEvent).count() == 1  # opportunity admission only


def test_fact_confirmation_resolution_rejects_hidden_or_ambiguous_writes() -> None:
    with pytest.raises(ValueError, match="explicit opportunity resolution"):
        FactConfirmationResolution(decision="confirm")
    with pytest.raises(ValueError, match="corrected_facts"):
        FactConfirmationResolution(
            decision="correct_and_confirm",
            opportunity={"kind": "create_new"},
        )
    with pytest.raises(ValueError, match="canonical write inputs"):
        FactConfirmationResolution(
            decision="reject",
            opportunity={"kind": "create_new"},
        )
