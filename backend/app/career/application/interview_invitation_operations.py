"""Shared VS-01 Application Operations.

UI, Agent, and Automation adapters call this module.  It is the only new
write owner for provider-neutral invitation state and deliberately reuses the
existing Career Process state machine instead of copying it.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.career.application.catalog import CAREER_OPERATION_CATALOG
from app.career.domain.interview_invitation import (
    INTERVIEW_INVITATION_FACT_FIELDS,
    REQUIRED_INTERVIEW_INVITATION_FACT_FIELDS,
)
from app.db.types import as_utc, utc_now
from app.models.agent_interaction import AgentInteraction
from app.models.application_operation import (
    ApplicationOperation,
    CareerDomainEvent,
    OperationVerification,
)
from app.models.conversation_turn import ConversationTurn
from app.models.interview_invitation import (
    InterviewInvitationCandidate,
    InterviewInvitationEvidenceRef,
    InterviewInvitationObservation,
    InterviewInvitationSourceSnapshot,
)
from app.models.interview_record import InterviewRecord
from app.models.job_opportunity import JobOpportunity, NextAction, ProcessEvent
from app.schemas.interview_invitation import (
    CandidateConfirmationBasis,
    ConfirmInterviewInvitation,
    ConfirmInterviewInvitationResult,
    ExplicitUserAssertionBasis,
    FactConfirmationRequest,
    FactConfirmationResolution,
    InterviewInvitationFacts,
    IntakeInterviewInvitationObservation,
    IntakeInterviewInvitationResult,
    InterviewInvitationCandidateView,
    InterviewInvitationHandoffView,
    InvitationFieldEvidence,
    InvitationObservationView,
    InvitationSourceReference,
    LinkExistingOpportunity,
    ObjectReference,
    RegisterInterviewInvitationCandidate,
    RegisterInterviewInvitationCandidateResult,
    RejectInterviewInvitationCandidate,
    RejectInterviewInvitationCandidateResult,
    UpdateExistingInterview,
    VerificationView,
)
from app.schemas.job_opportunity import OpportunityCreate, ProcessEventAppend
from app.services.career_process_service import (
    CareerIdempotencyConflictError,
    CareerProcessError,
    OpportunityAdmission,
    append_confirmed_process_event,
    create_job_opportunity,
)


class InterviewInvitationOperationError(ValueError):
    """Base typed rejection for a VS-01 Application Operation."""

    code = "operation_error"


class InvitationObjectNotFoundError(InterviewInvitationOperationError):
    code = "object_not_found"


class InvitationOwnershipError(InterviewInvitationOperationError):
    code = "ownership_denied"


class InvitationPolicyDeniedError(InterviewInvitationOperationError):
    code = "policy_denied"


class InvitationVersionConflictError(InterviewInvitationOperationError):
    code = "stale_version"


class InvitationIdempotencyConflictError(InterviewInvitationOperationError):
    code = "idempotency_conflict"


class InvitationStateConflictError(InterviewInvitationOperationError):
    code = "state_conflict"


class InvitationVerificationError(InterviewInvitationOperationError):
    code = "verification_failed"


@dataclass(frozen=True, slots=True)
class _OperationStart:
    operation: ApplicationOperation
    replayed: bool


def _json(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(mode="json")


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _fact_hash(value: Any) -> str:
    return _fingerprint(value)


def _adapter_for_actor(actor_kind: str, *, source_kind: str | None = None) -> str:
    if actor_kind == "user":
        return "ui"
    if actor_kind == "agent_on_behalf":
        return "agent"
    if actor_kind == "automation":
        return "fixture" if source_kind == "fixture" else "automation"
    if actor_kind == "system_connector":
        return "fixture" if source_kind == "fixture" else "integration"
    raise InvitationStateConflictError(f"unsupported actor kind: {actor_kind}")


def _authorize_confirm_invocation(command: ConfirmInterviewInvitation) -> None:
    """Recheck actor, evidence authority, and execution scope at the owner."""

    basis = command.confirmation_basis
    causation = command.causation
    if isinstance(basis, ExplicitUserAssertionBasis):
        if command.actor_kind == "user":
            return
        if command.actor_kind == "agent_on_behalf":
            if (
                basis.source.kind == "user_message"
                and causation.conversation_id
                and causation.turn_id
                and causation.tool_call_id
            ):
                return
            raise InvitationPolicyDeniedError(
                "Agent assertion requires the current Conversation, Turn, Tool Call, "
                "and user_message source"
            )
        raise InvitationPolicyDeniedError(
            "Automation cannot promote an explicit_user_assertion"
        )

    if command.actor_kind == "agent_on_behalf" and not (
        causation.conversation_id and causation.turn_id and causation.tool_call_id
    ):
        raise InvitationPolicyDeniedError(
            "Agent candidate confirmation requires Conversation, Turn, and Tool Call"
        )
    if command.actor_kind == "automation" and not causation.task_id:
        raise InvitationPolicyDeniedError(
            "Automation candidate confirmation requires a scoped task"
        )
    if command.actor_kind not in {"user", "agent_on_behalf", "automation"}:
        raise InvitationPolicyDeniedError(
            f"{command.actor_kind} cannot confirm invitation facts"
        )


def _begin_operation(
    db: Session,
    *,
    user_pk: int,
    operation_name: str,
    schema_version: int,
    idempotency_key: str,
    actor_kind: str,
    request_json: dict[str, Any],
    adapter: str,
    conversation_id: str | None = None,
    turn_id: str | None = None,
    task_id: str | None = None,
    tool_call_id: str | None = None,
    interaction_id: str | None = None,
) -> _OperationStart:
    definition = CAREER_OPERATION_CATALOG.get(operation_name, schema_version)
    if adapter not in definition.allowed_adapters:
        raise InvitationOwnershipError(
            f"{adapter} cannot invoke {operation_name}@{schema_version}"
        )
    request_fingerprint = _fingerprint(request_json)
    existing = (
        db.query(ApplicationOperation)
        .filter(
            ApplicationOperation.user_id == user_pk,
            ApplicationOperation.operation_name == operation_name,
            ApplicationOperation.idempotency_key == idempotency_key,
        )
        .one_or_none()
    )
    if existing is not None:
        if existing.request_fingerprint != request_fingerprint:
            raise InvitationIdempotencyConflictError(idempotency_key)
        if existing.status != "succeeded" or not isinstance(existing.result_json, dict):
            raise InvitationStateConflictError(
                f"operation {existing.id} is {existing.status}; reconciliation required"
            )
        return _OperationStart(existing, True)

    operation = ApplicationOperation(
        user_id=user_pk,
        operation_name=operation_name,
        schema_version=schema_version,
        idempotency_key=idempotency_key,
        request_fingerprint=request_fingerprint,
        actor_kind=actor_kind,
        status="started",
        conversation_id=conversation_id,
        turn_id=turn_id,
        task_id=task_id,
        tool_call_id=tool_call_id,
        interaction_id=interaction_id,
        request_json=request_json,
    )
    db.add(operation)
    db.flush()
    return _OperationStart(operation, False)


def _verification(
    db: Session,
    *,
    operation: ApplicationOperation,
    expected: list[dict[str, Any]],
    observed: list[dict[str, Any]],
    conclusion: str = "verified",
    failure_reason: str | None = None,
) -> OperationVerification:
    row = OperationVerification(
        operation_id=operation.id,
        schema_version=1,
        conclusion=conclusion,
        method="local_read_back",
        expected_postconditions_json=expected,
        observed_evidence_json=observed,
        failure_reason=failure_reason,
        attempt=1,
        completed_at=utc_now() if conclusion != "pending" else None,
    )
    db.add(row)
    db.flush()
    return row


def _domain_events(
    db: Session,
    *,
    user_pk: int,
    operation: ApplicationOperation,
    specs: Iterable[dict[str, Any]],
) -> list[CareerDomainEvent]:
    rows: list[CareerDomainEvent] = []
    for sequence, spec in enumerate(specs, start=1):
        kind = str(spec["event_kind"])
        row = CareerDomainEvent(
            user_id=user_pk,
            operation_id=operation.id,
            event_kind=kind,
            event_category="domain",
            schema_version=1,
            sequence=sequence,
            idempotency_key=f"{operation.id}:{kind}:{sequence}",
            aggregate_type=str(spec["aggregate_type"]),
            aggregate_id=str(spec["aggregate_id"]),
            aggregate_version=spec.get("aggregate_version"),
            object_references_json=list(spec.get("object_references", [])),
            payload_json=dict(spec.get("payload", {})),
            replayable=True,
            occurred_at=utc_now(),
        )
        db.add(row)
        rows.append(row)
    db.flush()
    return rows


def _complete(
    db: Session,
    *,
    operation: ApplicationOperation,
    result: BaseModel,
) -> None:
    operation.status = "succeeded"
    operation.result_json = result.model_dump(mode="json")
    operation.completed_at = utc_now()
    operation.updated_at = operation.completed_at
    db.add(operation)
    db.flush()


def intake_interview_invitation_observation(
    db: Session,
    *,
    user_pk: int,
    command: IntakeInterviewInvitationObservation,
) -> IntakeInterviewInvitationResult:
    request = _json(command)
    started = _begin_operation(
        db,
        user_pk=user_pk,
        operation_name="intake_interview_invitation_observation",
        schema_version=1,
        idempotency_key=command.idempotency_key,
        actor_kind=command.actor_kind,
        request_json=request,
        adapter=_adapter_for_actor(
            command.actor_kind,
            source_kind=command.source_kind,
        ),
    )
    if started.replayed:
        return IntakeInterviewInvitationResult.model_validate(
            started.operation.result_json
        ).model_copy(update={"replayed": True})

    payload_hash = _fingerprint(request["payload"])
    if command.content_sha256 is not None and command.content_sha256 != payload_hash:
        raise InterviewInvitationOperationError(
            "content_sha256 does not match the canonical payload"
        )

    existing_source = (
        db.query(InterviewInvitationSourceSnapshot)
        .filter(
            InterviewInvitationSourceSnapshot.user_id == user_pk,
            InterviewInvitationSourceSnapshot.source_kind == command.source_kind,
            InterviewInvitationSourceSnapshot.source_identity
            == command.source_identity.strip(),
            InterviewInvitationSourceSnapshot.source_version
            == command.source_version.strip(),
        )
        .one_or_none()
    )
    deduplicated = existing_source is not None
    if existing_source is not None:
        if existing_source.content_sha256 != payload_hash:
            raise InvitationIdempotencyConflictError(
                f"source:{command.source_kind}:{command.source_identity}:"
                f"{command.source_version}"
            )
        source = existing_source
        observation = (
            db.query(InterviewInvitationObservation)
            .filter(
                InterviewInvitationObservation.user_id == user_pk,
                InterviewInvitationObservation.source_snapshot_id == source.id,
            )
            .one()
        )
    else:
        source = InterviewInvitationSourceSnapshot(
            user_id=user_pk,
            source_kind=command.source_kind,
            source_identity=command.source_identity.strip(),
            source_version=command.source_version.strip(),
            content_sha256=payload_hash,
            payload_json=request["payload"],
            observed_at=command.observed_at,
        )
        db.add(source)
        db.flush()
        observation = InterviewInvitationObservation(
            user_id=user_pk,
            source_snapshot_id=source.id,
            status="received",
            version=1,
        )
        db.add(observation)
        db.flush()
        _domain_events(
            db,
            user_pk=user_pk,
            operation=started.operation,
            specs=(
                {
                    "event_kind": "interview_invitation_observation_received",
                    "aggregate_type": "interview_invitation_observation",
                    "aggregate_id": observation.id,
                    "aggregate_version": observation.version,
                    "object_references": [
                        {"kind": "source_snapshot", "id": source.id},
                        {
                            "kind": "interview_invitation_observation",
                            "id": observation.id,
                            "version": observation.version,
                        },
                    ],
                    "payload": {"source_kind": source.source_kind},
                },
            ),
        )

    verification = _verification(
        db,
        operation=started.operation,
        expected=[{"postcondition": "source_snapshot_and_observation_exist"}],
        observed=[
            {"kind": "source_snapshot", "id": source.id},
            {
                "kind": "interview_invitation_observation",
                "id": observation.id,
                "version": observation.version,
            },
        ],
    )
    result = IntakeInterviewInvitationResult(
        operation_id=started.operation.id,
        verification_id=verification.id,
        source_snapshot_id=source.id,
        observation=InvitationObservationView.model_validate(observation),
        deduplicated=deduplicated,
    )
    _complete(db, operation=started.operation, result=result)
    return result


def register_interview_invitation_candidate(
    db: Session,
    *,
    user_pk: int,
    command: RegisterInterviewInvitationCandidate,
) -> RegisterInterviewInvitationCandidateResult:
    request = _json(command)
    started = _begin_operation(
        db,
        user_pk=user_pk,
        operation_name="register_interview_invitation_candidate",
        schema_version=1,
        idempotency_key=command.idempotency_key,
        actor_kind=command.actor_kind,
        request_json=request,
        adapter=_adapter_for_actor(command.actor_kind),
    )
    if started.replayed:
        return RegisterInterviewInvitationCandidateResult.model_validate(
            started.operation.result_json
        ).model_copy(update={"replayed": True})

    observation = None
    if command.observation_id is not None:
        observation = (
            db.query(InterviewInvitationObservation)
            .filter(
                InterviewInvitationObservation.id == command.observation_id,
                InterviewInvitationObservation.user_id == user_pk,
            )
            .with_for_update()
            .one_or_none()
        )
        if observation is None:
            raise InvitationObjectNotFoundError("invitation observation")
        if observation.version != command.expected_observation_version:
            raise InvitationVersionConflictError(
                f"observation version is {observation.version}"
            )
        if observation.status not in {"received", "candidate_registered"}:
            raise InvitationStateConflictError(
                f"observation cannot register a candidate from {observation.status}"
            )

    for evidence in command.field_provenance:
        evidence.to_domain()
    facts_json = command.facts.model_dump(mode="json")
    missing = set(command.missing_fields)
    missing.update(
        field
        for field in REQUIRED_INTERVIEW_INVITATION_FACT_FIELDS
        if not facts_json.get(field)
    )
    status = (
        "needs_clarification"
        if missing or command.conflicts
        else "pending_confirmation"
    )
    candidate = InterviewInvitationCandidate(
        user_id=user_pk,
        observation_id=observation.id if observation is not None else None,
        source_kind=command.source_kind,
        source_identity=command.source_identity.strip(),
        source_version=command.source_version.strip(),
        status=status,
        version=1,
        facts_json=facts_json,
        field_provenance_json=[
            item.model_dump(mode="json") for item in command.field_provenance
        ],
        missing_fields_json=sorted(missing),
        conflicts_json=list(command.conflicts),
        confidence=command.confidence,
        extractor_version=command.extractor_version.strip(),
    )
    db.add(candidate)
    db.flush()
    if observation is not None:
        observation.status = (
            "pending_confirmation"
            if status == "pending_confirmation"
            else "candidate_registered"
        )
        observation.version += 1
        observation.updated_at = utc_now()
        db.add(observation)

    events = _domain_events(
        db,
        user_pk=user_pk,
        operation=started.operation,
        specs=(
            {
                "event_kind": "interview_invitation_candidate_registered",
                "aggregate_type": "interview_invitation_candidate",
                "aggregate_id": candidate.id,
                "aggregate_version": candidate.version,
                "object_references": [
                    {
                        "kind": "interview_invitation_candidate",
                        "id": candidate.id,
                        "version": candidate.version,
                    }
                ],
                "payload": {"status": candidate.status},
            },
        ),
    )
    verification = _verification(
        db,
        operation=started.operation,
        expected=[{"postcondition": "candidate_is_low_authority"}],
        observed=[
            {
                "kind": "interview_invitation_candidate",
                "id": candidate.id,
                "version": candidate.version,
                "status": candidate.status,
            },
            {"kind": "domain_event", "id": events[0].id},
        ],
    )
    result = RegisterInterviewInvitationCandidateResult(
        operation_id=started.operation.id,
        verification_id=verification.id,
        candidate=InterviewInvitationCandidateView.model_validate(candidate),
    )
    _complete(db, operation=started.operation, result=result)
    return result


def _owned_interaction(
    db: Session,
    *,
    user_pk: int,
    interaction_id: str,
) -> AgentInteraction:
    row = (
        db.query(AgentInteraction)
        .join(ConversationTurn, ConversationTurn.id == AgentInteraction.turn_id)
        .filter(
            AgentInteraction.id == interaction_id,
            ConversationTurn.user_id == user_pk,
        )
        .one_or_none()
    )
    if row is None:
        raise InvitationObjectNotFoundError("fact confirmation Interaction")
    if row.kind != "fact_confirmation":
        raise InvitationStateConflictError("Interaction is not fact_confirmation")
    return row


def _validate_confirmation_interaction(
    db: Session,
    *,
    user_pk: int,
    basis: CandidateConfirmationBasis,
    expected_decisions: set[str],
) -> AgentInteraction:
    row = _owned_interaction(db, user_pk=user_pk, interaction_id=basis.interaction_id)
    if row.status not in {"resolved", "rejected"}:
        raise InvitationStateConflictError("fact confirmation is still pending")
    if row.resolution_identity != basis.decision_identity:
        raise InvitationVersionConflictError("fact confirmation decision changed")
    resolution = row.resolution_json if isinstance(row.resolution_json, dict) else {}
    if resolution.get("decision") not in expected_decisions:
        raise InvitationStateConflictError("fact confirmation decision is incompatible")
    return row


def _candidate_for_confirmation(
    db: Session,
    *,
    user_pk: int,
    basis: CandidateConfirmationBasis,
) -> tuple[InterviewInvitationCandidate, AgentInteraction]:
    candidate = (
        db.query(InterviewInvitationCandidate)
        .filter(
            InterviewInvitationCandidate.id == basis.candidate_id,
            InterviewInvitationCandidate.user_id == user_pk,
        )
        .with_for_update()
        .one_or_none()
    )
    if candidate is None:
        raise InvitationObjectNotFoundError("interview invitation candidate")
    if candidate.version != basis.expected_candidate_version:
        raise InvitationVersionConflictError(
            f"candidate version is {candidate.version}"
        )
    if candidate.status not in {"pending_confirmation", "needs_clarification"}:
        raise InvitationStateConflictError(
            f"candidate cannot be confirmed from {candidate.status}"
        )
    interaction = _validate_confirmation_interaction(
        db,
        user_pk=user_pk,
        basis=basis,
        expected_decisions={"confirm", "correct_and_confirm"},
    )
    request = (
        interaction.request_json if isinstance(interaction.request_json, dict) else {}
    )
    candidate_reference = request.get("candidate_reference")
    if (
        not isinstance(candidate_reference, dict)
        or candidate_reference.get("kind") != "interview_invitation_candidate"
        or candidate_reference.get("id") != candidate.id
    ):
        raise InvitationStateConflictError(
            "fact confirmation does not target this candidate"
        )
    if request.get("expected_candidate_version") != candidate.version:
        raise InvitationVersionConflictError(
            "fact confirmation targets a stale candidate version"
        )
    return candidate, interaction


def _source_for_confirmation(
    db: Session,
    *,
    user_pk: int,
    command: ConfirmInterviewInvitation,
) -> tuple[
    InvitationSourceReference, str, str | None, InterviewInvitationCandidate | None
]:
    basis = command.confirmation_basis
    if isinstance(basis, ExplicitUserAssertionBasis):
        source = basis.source
        if source.snapshot_id is not None:
            owned = (
                db.query(InterviewInvitationSourceSnapshot.id)
                .filter(
                    InterviewInvitationSourceSnapshot.id == source.snapshot_id,
                    InterviewInvitationSourceSnapshot.user_id == user_pk,
                    InterviewInvitationSourceSnapshot.source_kind == source.kind,
                    InterviewInvitationSourceSnapshot.source_identity
                    == source.identity.strip(),
                )
                .scalar()
            )
            if owned is None:
                raise InvitationObjectNotFoundError("invitation source snapshot")
        return source, source.identity.strip(), source.version, None

    candidate, interaction = _candidate_for_confirmation(
        db,
        user_pk=user_pk,
        basis=basis,
    )
    request = FactConfirmationRequest.model_validate(interaction.request_json)
    resolution = FactConfirmationResolution.model_validate(interaction.resolution_json)
    if (
        candidate.status == "needs_clarification"
        or request.conflicts
        or request.missing_or_uncertain_fields
    ) and resolution.decision != "correct_and_confirm":
        raise InvitationPolicyDeniedError(
            "candidate requires explicit complete correction"
        )
    expected_facts = (
        resolution.corrected_facts
        if resolution.decision == "correct_and_confirm"
        else InterviewInvitationFacts.model_validate(
            request.invitation_facts.model_dump(mode="json")
        )
    )
    # The shared owner rechecks exact approved inputs, not just an approval ID.
    # This covers adapters that do not use the current thin Agent wrapper.
    if (
        expected_facts is None
        or resolution.opportunity is None
        or _json(expected_facts) != _json(command.facts)
        or _json(resolution.opportunity) != _json(command.opportunity)
        or _json(resolution.interview) != _json(command.interview)
    ):
        raise InvitationPolicyDeniedError(
            "confirmed inputs differ from the user decision"
        )
    source = InvitationSourceReference(
        kind="user_message",
        identity=basis.decision_identity,
        version=str(basis.expected_candidate_version),
    )
    return (
        source,
        basis.decision_identity,
        str(basis.expected_candidate_version),
        candidate,
    )


def _resolve_opportunity(
    db: Session,
    *,
    user_pk: int,
    command: ConfirmInterviewInvitation,
    source_identity: str,
    source_version: str | None,
) -> tuple[JobOpportunity, bool, ProcessEvent | None]:
    resolution = command.opportunity
    if isinstance(resolution, LinkExistingOpportunity):
        opportunity = (
            db.query(JobOpportunity)
            .filter(
                JobOpportunity.id == resolution.opportunity_id,
                JobOpportunity.user_id == user_pk,
            )
            .with_for_update()
            .one_or_none()
        )
        if opportunity is None:
            raise InvitationObjectNotFoundError("job opportunity")
        if opportunity.version != resolution.expected_version:
            raise InvitationVersionConflictError(
                f"opportunity version is {opportunity.version}"
            )
        if opportunity.outcome is not None:
            raise InvitationStateConflictError("job opportunity is archived")
        return opportunity, False, None

    facts = command.facts
    try:
        admission: OpportunityAdmission = create_job_opportunity(
            db,
            user_pk=user_pk,
            command=OpportunityCreate(
                company_name=facts.company_name,
                job_title=facts.job_title,
                entry_reason="confirmed_interview_invitation",
                occurred_at=command.asserted_at,
                source_kind="user_assertion",
                source_identity=source_identity,
                source_version=source_version,
                source_description=(
                    f"Confirmed interview invitation for {facts.company_name} "
                    f"{facts.job_title}"
                ),
                location=command.opportunity.location,
                team=command.opportunity.team,
                source_url=command.opportunity.source_url,
                source_provider=command.opportunity.source_provider,
                external_job_id=command.opportunity.external_job_id,
                idempotency_key=f"{command.idempotency_key}:opportunity"[:200],
            ),
        )
    except CareerIdempotencyConflictError as exc:
        raise InvitationIdempotencyConflictError(str(exc)) from exc
    except CareerProcessError as exc:
        raise InvitationStateConflictError(str(exc)) from exc
    return admission.opportunity, admission.created, admission.initial_event


def _create_or_update_interview(
    db: Session,
    *,
    user_pk: int,
    operation: ApplicationOperation,
    command: ConfirmInterviewInvitation,
    opportunity: JobOpportunity,
    source: InvitationSourceReference,
    candidate: InterviewInvitationCandidate | None,
) -> tuple[InterviewRecord, bool]:
    facts = command.facts
    resolution = command.interview
    if isinstance(resolution, UpdateExistingInterview):
        interview = (
            db.query(InterviewRecord)
            .filter(
                InterviewRecord.id == resolution.interview_id,
                InterviewRecord.user_id == user_pk,
            )
            .with_for_update()
            .one_or_none()
        )
        if interview is None:
            raise InvitationObjectNotFoundError("interview")
        if interview.source != "invitation" or interview.status != "scheduled":
            raise InvitationStateConflictError(
                "only a scheduled invitation Interview can be updated"
            )
        if interview.job_opportunity_id != opportunity.id:
            raise InvitationStateConflictError(
                "Interview belongs to another job opportunity"
            )
        if interview.schedule_version != resolution.expected_schedule_version:
            raise InvitationVersionConflictError(
                f"interview schedule version is {interview.schedule_version}"
            )
        created = False
    else:
        interview = InterviewRecord(
            user_id=user_pk,
            source="invitation",
            job_opportunity_id=opportunity.id,
            title=(f"{facts.company_name} {facts.stage_label or 'Interview'}"),
            status="scheduled",
            analyzed_qa_count=0,
            analysis_schema_version=3,
            schedule_version=0,
        )
        db.add(interview)
        created = True

    interview.schedule_version = int(interview.schedule_version or 0) + 1
    interview.scheduled_start_at = facts.scheduled_start_at
    interview.scheduled_end_at = facts.scheduled_end_at
    interview.original_time_text = facts.original_time_text.strip()
    interview.source_timezone = facts.source_timezone.strip()
    interview.stage_label = facts.stage_label
    interview.scheduled_location = facts.location
    interview.meeting_url = facts.meeting_url
    interview.contact_json = {
        key: value
        for key, value in {
            "name": facts.contact_name,
            "email": facts.contact_email,
        }.items()
        if value is not None
    } or None
    interview.invitation_source_kind = source.kind
    interview.invitation_source_identity = source.identity
    interview.invitation_source_version = source.version
    interview.invitation_candidate_id = candidate.id if candidate is not None else None
    interview.invitation_operation_id = operation.id
    interview.updated_at = utc_now()
    db.add(interview)
    db.flush()
    return interview, created


def _append_invitation_event(
    db: Session,
    *,
    user_pk: int,
    operation: ApplicationOperation,
    command: ConfirmInterviewInvitation,
    opportunity: JobOpportunity,
    source_identity: str,
    source_version: str | None,
    existing_event: ProcessEvent | None,
) -> ProcessEvent:
    if existing_event is not None:
        return existing_event
    try:
        return append_confirmed_process_event(
            db,
            user_pk=user_pk,
            opportunity_id=opportunity.id,
            command=ProcessEventAppend(
                kind="interview_scheduled",
                occurred_at=command.asserted_at,
                source_kind="user_assertion",
                source_identity=source_identity,
                source_version=source_version,
                description=(
                    f"Confirmed interview scheduled for "
                    f"{command.facts.original_time_text.strip()}"
                ),
                step_summary=(
                    command.facts.stage_label.strip()
                    if command.facts.stage_label
                    else "Interview scheduled"
                ),
                idempotency_key=f"{operation.id}:interview_scheduled",
            ),
        )
    except CareerIdempotencyConflictError as exc:
        raise InvitationIdempotencyConflictError(str(exc)) from exc
    except CareerProcessError as exc:
        raise InvitationStateConflictError(str(exc)) from exc


def _effective_evidence(
    command: ConfirmInterviewInvitation,
    *,
    fallback_source: InvitationSourceReference,
) -> list[InvitationFieldEvidence]:
    facts = command.facts.model_dump(mode="json")
    evidence_by_field: dict[str, list[InvitationFieldEvidence]] = {}
    seen: set[tuple[str, str, str, str | None]] = set()
    for item in command.evidence:
        item.to_domain()
        expected_hash = _fact_hash(facts[item.field_name])
        if item.value_hash.lower() != expected_hash:
            raise InterviewInvitationOperationError(
                f"evidence hash does not match confirmed {item.field_name}"
            )
        key = (
            item.field_name,
            item.source.kind,
            item.source.identity,
            item.source.version,
        )
        if key not in seen:
            evidence_by_field.setdefault(item.field_name, []).append(item)
            seen.add(key)

    for field in INTERVIEW_INVITATION_FACT_FIELDS:
        if facts[field] is None or field in evidence_by_field:
            continue
        generated = InvitationFieldEvidence(
            field_name=field,
            source=fallback_source,
            value_hash=_fact_hash(facts[field]),
        )
        evidence_by_field.setdefault(field, []).append(generated)

    missing_required = set(REQUIRED_INTERVIEW_INVITATION_FACT_FIELDS) - set(
        evidence_by_field
    )
    if missing_required:
        raise InterviewInvitationOperationError(
            f"confirmed facts lack evidence: {sorted(missing_required)}"
        )
    return [
        item
        for field in INTERVIEW_INVITATION_FACT_FIELDS
        for item in evidence_by_field.get(field, [])
    ]


def _bind_evidence(
    db: Session,
    *,
    user_pk: int,
    operation: ApplicationOperation,
    candidate: InterviewInvitationCandidate | None,
    interview: InterviewRecord,
    process_event: ProcessEvent,
    evidence: list[InvitationFieldEvidence],
) -> list[InterviewInvitationEvidenceRef]:
    rows: list[InterviewInvitationEvidenceRef] = []
    for item in evidence:
        snapshot_id = item.source.snapshot_id
        if snapshot_id is not None:
            owned = (
                db.query(InterviewInvitationSourceSnapshot.id)
                .filter(
                    InterviewInvitationSourceSnapshot.id == snapshot_id,
                    InterviewInvitationSourceSnapshot.user_id == user_pk,
                    InterviewInvitationSourceSnapshot.source_kind == item.source.kind,
                    InterviewInvitationSourceSnapshot.source_identity
                    == item.source.identity,
                )
                .scalar()
            )
            if owned is None:
                raise InvitationObjectNotFoundError("invitation evidence snapshot")
        row = InterviewInvitationEvidenceRef(
            user_id=user_pk,
            operation_id=operation.id,
            candidate_id=candidate.id if candidate is not None else None,
            source_snapshot_id=snapshot_id,
            interview_record_id=interview.id,
            process_event_id=process_event.id,
            field_name=item.field_name,
            source_kind=item.source.kind,
            source_identity=item.source.identity.strip(),
            source_version=item.source.version,
            value_hash=item.value_hash.lower(),
        )
        db.add(row)
        rows.append(row)
    db.flush()
    return rows


def _object_ref(kind: str, identity: str, version: int | None = None) -> dict[str, Any]:
    return {"kind": kind, "id": identity, "version": version}


def confirm_interview_invitation(
    db: Session,
    *,
    user_pk: int,
    command: ConfirmInterviewInvitation,
) -> ConfirmInterviewInvitationResult:
    command.facts.to_domain()
    _authorize_confirm_invocation(command)
    request = _json(command)
    causation = command.causation
    interaction_id = (
        command.confirmation_basis.interaction_id
        if isinstance(command.confirmation_basis, CandidateConfirmationBasis)
        else None
    )
    started = _begin_operation(
        db,
        user_pk=user_pk,
        operation_name="confirm_interview_invitation",
        schema_version=command.schema_version,
        idempotency_key=command.idempotency_key,
        actor_kind=command.actor_kind,
        request_json=request,
        adapter=_adapter_for_actor(command.actor_kind),
        conversation_id=causation.conversation_id,
        turn_id=causation.turn_id,
        task_id=causation.task_id,
        tool_call_id=causation.tool_call_id,
        interaction_id=interaction_id,
    )
    if started.replayed:
        return ConfirmInterviewInvitationResult.model_validate(
            started.operation.result_json
        ).model_copy(update={"replayed": True})

    next_action_count_before = (
        db.query(NextAction).filter(NextAction.user_id == user_pk).count()
    )
    source, event_source_identity, event_source_version, candidate = (
        _source_for_confirmation(db, user_pk=user_pk, command=command)
    )
    opportunity, opportunity_created, initial_event = _resolve_opportunity(
        db,
        user_pk=user_pk,
        command=command,
        source_identity=event_source_identity,
        source_version=event_source_version,
    )
    interview, interview_created = _create_or_update_interview(
        db,
        user_pk=user_pk,
        operation=started.operation,
        command=command,
        opportunity=opportunity,
        source=source,
        candidate=candidate,
    )
    process_event = _append_invitation_event(
        db,
        user_pk=user_pk,
        operation=started.operation,
        command=command,
        opportunity=opportunity,
        source_identity=event_source_identity,
        source_version=event_source_version,
        existing_event=initial_event,
    )
    # Existing opportunity events increment the replayed projection version.
    db.flush()
    evidence = _bind_evidence(
        db,
        user_pk=user_pk,
        operation=started.operation,
        candidate=candidate,
        interview=interview,
        process_event=process_event,
        evidence=_effective_evidence(command, fallback_source=source),
    )

    if candidate is not None:
        basis = command.confirmation_basis
        if not isinstance(basis, CandidateConfirmationBasis):  # pragma: no cover
            raise InvitationStateConflictError("candidate basis disappeared")
        candidate.status = "confirmed"
        candidate.version += 1
        candidate.resolved_by_interaction_id = basis.interaction_id
        candidate.confirmed_operation_id = started.operation.id
        candidate.resolution_note = "confirmed"
        candidate.resolved_at = utc_now()
        candidate.updated_at = candidate.resolved_at
        db.add(candidate)
        if candidate.observation_id is not None:
            observation = (
                db.query(InterviewInvitationObservation)
                .filter(
                    InterviewInvitationObservation.id == candidate.observation_id,
                    InterviewInvitationObservation.user_id == user_pk,
                )
                .with_for_update()
                .one()
            )
            observation.status = "confirmed"
            observation.version += 1
            observation.updated_at = utc_now()
            db.add(observation)
    db.flush()

    references = [
        _object_ref("job_opportunity", opportunity.id, opportunity.version),
        _object_ref("interview", interview.id, interview.schedule_version),
        _object_ref("process_event", process_event.id, process_event.sequence),
    ]
    event_specs: list[dict[str, Any]] = []
    if opportunity_created:
        event_specs.append(
            {
                "event_kind": "job_opportunity_created",
                "aggregate_type": "job_opportunity",
                "aggregate_id": opportunity.id,
                "aggregate_version": opportunity.version,
                "object_references": references,
                "payload": {},
            }
        )
    event_specs.extend(
        (
            {
                "event_kind": (
                    "interview_created"
                    if interview_created
                    else "interview_schedule_updated"
                ),
                "aggregate_type": "interview",
                "aggregate_id": interview.id,
                "aggregate_version": interview.schedule_version,
                "object_references": references,
                "payload": {
                    "scheduled_start_at": command.facts.scheduled_start_at.isoformat()
                },
            },
            {
                "event_kind": "process_event_appended",
                "aggregate_type": "job_opportunity",
                "aggregate_id": opportunity.id,
                "aggregate_version": opportunity.version,
                "object_references": references,
                "payload": {"process_event_kind": "interview_scheduled"},
            },
            {
                "event_kind": "evidence_bound",
                "aggregate_type": "interview",
                "aggregate_id": interview.id,
                "aggregate_version": interview.schedule_version,
                "object_references": references,
                "payload": {"evidence_count": len(evidence)},
            },
            {
                "event_kind": "interview_invitation_confirmed",
                "aggregate_type": "interview",
                "aggregate_id": interview.id,
                "aggregate_version": interview.schedule_version,
                "object_references": references,
                "payload": {
                    "confirmation_basis": command.confirmation_basis.kind,
                    "opportunity_created": opportunity_created,
                },
            },
        )
    )
    domain_events = _domain_events(
        db,
        user_pk=user_pk,
        operation=started.operation,
        specs=event_specs,
    )
    started.operation.status = "verifying"
    db.add(started.operation)
    db.flush()

    read_opportunity = db.get(JobOpportunity, opportunity.id)
    read_interview = db.get(InterviewRecord, interview.id)
    read_process_event = db.get(ProcessEvent, process_event.id)
    next_action_count_after = (
        db.query(NextAction).filter(NextAction.user_id == user_pk).count()
    )
    if (
        read_opportunity is None
        or read_opportunity.user_id != user_pk
        or read_interview is None
        or read_interview.user_id != user_pk
        or read_interview.job_opportunity_id != read_opportunity.id
        or as_utc(read_interview.scheduled_start_at)
        != as_utc(command.facts.scheduled_start_at)
        or read_process_event is None
        or read_process_event.kind != "interview_scheduled"
        or next_action_count_before != next_action_count_after
    ):
        raise InvitationVerificationError(
            "confirmed invitation failed local read-back verification"
        )

    verification = _verification(
        db,
        operation=started.operation,
        expected=[
            {"postcondition": "opportunity_owned_and_active"},
            {"postcondition": "interview_schedule_matches_confirmed_facts"},
            {"postcondition": "interview_scheduled_event_is_append_only"},
            {"postcondition": "field_evidence_is_bound"},
            {"postcondition": "no_next_action_created"},
        ],
        observed=[
            *references,
            {"kind": "evidence_count", "value": len(evidence)},
            {"kind": "next_action_delta", "value": 0},
        ],
    )
    result = ConfirmInterviewInvitationResult(
        operation_id=started.operation.id,
        opportunity=ObjectReference(
            kind="job_opportunity", id=opportunity.id, version=opportunity.version
        ),
        interview=ObjectReference(
            kind="interview", id=interview.id, version=interview.schedule_version
        ),
        process_event=ObjectReference(
            kind="process_event", id=process_event.id, version=process_event.sequence
        ),
        evidence=[
            ObjectReference(kind="invitation_evidence", id=row.id) for row in evidence
        ],
        domain_events=[
            ObjectReference(kind="domain_event", id=row.id, version=row.sequence)
            for row in domain_events
        ],
        verification=VerificationView.model_validate(verification),
        projection_invalidations=[
            "today",
            "career.opportunities",
            f"career.opportunity:{opportunity.id}",
            "interviews",
            f"interview:{interview.id}",
            "activity",
        ],
    )
    _complete(db, operation=started.operation, result=result)
    return result


def reject_interview_invitation_candidate(
    db: Session,
    *,
    user_pk: int,
    command: RejectInterviewInvitationCandidate,
) -> RejectInterviewInvitationCandidateResult:
    request = _json(command)
    started = _begin_operation(
        db,
        user_pk=user_pk,
        operation_name="reject_interview_invitation_candidate",
        schema_version=command.schema_version,
        idempotency_key=command.idempotency_key,
        actor_kind=command.actor_kind,
        request_json=request,
        adapter=_adapter_for_actor(command.actor_kind),
        conversation_id=command.causation.conversation_id,
        turn_id=command.causation.turn_id,
        task_id=command.causation.task_id,
        tool_call_id=command.causation.tool_call_id,
        interaction_id=command.interaction_id,
    )
    if started.replayed:
        return RejectInterviewInvitationCandidateResult.model_validate(
            started.operation.result_json
        ).model_copy(update={"replayed": True})

    candidate = (
        db.query(InterviewInvitationCandidate)
        .filter(
            InterviewInvitationCandidate.id == command.candidate_id,
            InterviewInvitationCandidate.user_id == user_pk,
        )
        .with_for_update()
        .one_or_none()
    )
    if candidate is None:
        raise InvitationObjectNotFoundError("interview invitation candidate")
    if candidate.version != command.expected_candidate_version:
        raise InvitationVersionConflictError(
            f"candidate version is {candidate.version}"
        )
    if candidate.status != "pending_confirmation":
        raise InvitationStateConflictError(
            f"candidate cannot be rejected from {candidate.status}"
        )
    basis = CandidateConfirmationBasis(
        kind="candidate_confirmation",
        candidate_id=candidate.id,
        expected_candidate_version=candidate.version,
        interaction_id=command.interaction_id,
        decision_identity=command.decision_identity,
    )
    interaction = _validate_confirmation_interaction(
        db,
        user_pk=user_pk,
        basis=basis,
        expected_decisions={"reject"},
    )
    interaction_request = (
        interaction.request_json if isinstance(interaction.request_json, dict) else {}
    )
    candidate_reference = interaction_request.get("candidate_reference")
    if (
        not isinstance(candidate_reference, dict)
        or candidate_reference.get("kind") != "interview_invitation_candidate"
        or candidate_reference.get("id") != candidate.id
    ):
        raise InvitationStateConflictError(
            "fact confirmation does not target this candidate"
        )

    canonical_counts_before = (
        db.query(JobOpportunity).filter(JobOpportunity.user_id == user_pk).count(),
        db.query(InterviewRecord).filter(InterviewRecord.user_id == user_pk).count(),
        db.query(ProcessEvent)
        .join(JobOpportunity, JobOpportunity.id == ProcessEvent.job_opportunity_id)
        .filter(JobOpportunity.user_id == user_pk)
        .count(),
        db.query(NextAction).filter(NextAction.user_id == user_pk).count(),
    )
    candidate.status = "rejected"
    candidate.version += 1
    candidate.resolved_by_interaction_id = interaction.id
    candidate.resolution_note = command.reason or "rejected"
    candidate.resolved_at = utc_now()
    candidate.updated_at = candidate.resolved_at
    db.add(candidate)
    if candidate.observation_id is not None:
        observation = (
            db.query(InterviewInvitationObservation)
            .filter(
                InterviewInvitationObservation.id == candidate.observation_id,
                InterviewInvitationObservation.user_id == user_pk,
            )
            .with_for_update()
            .one()
        )
        observation.status = "rejected"
        observation.version += 1
        observation.updated_at = utc_now()
        db.add(observation)
    db.flush()

    events = _domain_events(
        db,
        user_pk=user_pk,
        operation=started.operation,
        specs=(
            {
                "event_kind": "interview_invitation_candidate_rejected",
                "aggregate_type": "interview_invitation_candidate",
                "aggregate_id": candidate.id,
                "aggregate_version": candidate.version,
                "object_references": [
                    _object_ref(
                        "interview_invitation_candidate",
                        candidate.id,
                        candidate.version,
                    )
                ],
                "payload": {"reason": candidate.resolution_note},
            },
        ),
    )
    canonical_counts_after = (
        db.query(JobOpportunity).filter(JobOpportunity.user_id == user_pk).count(),
        db.query(InterviewRecord).filter(InterviewRecord.user_id == user_pk).count(),
        db.query(ProcessEvent)
        .join(JobOpportunity, JobOpportunity.id == ProcessEvent.job_opportunity_id)
        .filter(JobOpportunity.user_id == user_pk)
        .count(),
        db.query(NextAction).filter(NextAction.user_id == user_pk).count(),
    )
    if canonical_counts_before != canonical_counts_after:
        raise InvitationVerificationError(
            "candidate rejection changed canonical career state"
        )
    verification = _verification(
        db,
        operation=started.operation,
        expected=[
            {"postcondition": "candidate_rejected"},
            {"postcondition": "canonical_state_unchanged"},
        ],
        observed=[
            _object_ref(
                "interview_invitation_candidate", candidate.id, candidate.version
            ),
            {"kind": "canonical_state_delta", "value": [0, 0, 0, 0]},
        ],
    )
    result = RejectInterviewInvitationCandidateResult(
        operation_id=started.operation.id,
        candidate=ObjectReference(
            kind="interview_invitation_candidate",
            id=candidate.id,
            version=candidate.version,
        ),
        domain_events=[
            ObjectReference(kind="domain_event", id=events[0].id, version=1)
        ],
        verification=VerificationView.model_validate(verification),
    )
    _complete(db, operation=started.operation, result=result)
    return result


def get_interview_invitation_candidate(
    db: Session,
    *,
    user_pk: int,
    candidate_id: str,
) -> InterviewInvitationCandidateView:
    row = (
        db.query(InterviewInvitationCandidate)
        .filter(
            InterviewInvitationCandidate.id == candidate_id,
            InterviewInvitationCandidate.user_id == user_pk,
        )
        .one_or_none()
    )
    if row is None:
        raise InvitationObjectNotFoundError("interview invitation candidate")
    return InterviewInvitationCandidateView.model_validate(row)


def get_interview_invitation_handoff(
    db: Session,
    *,
    user_pk: int,
    interview_id: str,
) -> InterviewInvitationHandoffView:
    interview = (
        db.query(InterviewRecord)
        .filter(
            InterviewRecord.id == interview_id,
            InterviewRecord.user_id == user_pk,
            InterviewRecord.source == "invitation",
        )
        .one_or_none()
    )
    if interview is None or interview.invitation_operation_id is None:
        raise InvitationObjectNotFoundError("confirmed invitation interview")
    opportunity = (
        db.query(JobOpportunity)
        .filter(
            JobOpportunity.id == interview.job_opportunity_id,
            JobOpportunity.user_id == user_pk,
        )
        .one_or_none()
    )
    verification = (
        db.query(OperationVerification)
        .join(
            ApplicationOperation,
            ApplicationOperation.id == OperationVerification.operation_id,
        )
        .filter(
            OperationVerification.operation_id == interview.invitation_operation_id,
            ApplicationOperation.user_id == user_pk,
        )
        .one_or_none()
    )
    if (
        opportunity is None
        or verification is None
        or verification.conclusion != "verified"
        or interview.scheduled_start_at is None
        or interview.original_time_text is None
        or interview.source_timezone is None
        or interview.invitation_source_kind is None
        or interview.invitation_source_identity is None
    ):
        raise InvitationVerificationError("invitation handoff is not verified")
    return InterviewInvitationHandoffView(
        opportunity=ObjectReference(
            kind="job_opportunity", id=opportunity.id, version=opportunity.version
        ),
        interview=ObjectReference(
            kind="interview", id=interview.id, version=interview.schedule_version
        ),
        company_name=opportunity.company_name,
        job_title=opportunity.job_title,
        scheduled_start_at=interview.scheduled_start_at,
        scheduled_end_at=interview.scheduled_end_at,
        original_time_text=interview.original_time_text,
        source_timezone=interview.source_timezone,
        stage_label=interview.stage_label,
        location=interview.scheduled_location,
        meeting_url=interview.meeting_url,
        source=InvitationSourceReference(
            kind=interview.invitation_source_kind,
            identity=interview.invitation_source_identity,
            version=interview.invitation_source_version,
        ),
        verification=VerificationView.model_validate(verification),
    )


def list_interview_invitation_handoffs(
    db: Session,
    *,
    user_pk: int,
) -> list[InterviewInvitationHandoffView]:
    """List only verified invitation-owned Interview schedules."""

    interview_ids = (
        db.query(InterviewRecord.id)
        .filter(
            InterviewRecord.user_id == user_pk,
            InterviewRecord.source == "invitation",
            InterviewRecord.invitation_operation_id.is_not(None),
        )
        .order_by(InterviewRecord.scheduled_start_at.asc())
        .limit(100)
        .all()
    )
    return [
        get_interview_invitation_handoff(
            db,
            user_pk=user_pk,
            interview_id=row.id,
        )
        for row in interview_ids
    ]


__all__ = [
    "InvitationIdempotencyConflictError",
    "InvitationObjectNotFoundError",
    "InvitationOwnershipError",
    "InvitationPolicyDeniedError",
    "InvitationStateConflictError",
    "InvitationVerificationError",
    "InvitationVersionConflictError",
    "InterviewInvitationOperationError",
    "confirm_interview_invitation",
    "get_interview_invitation_candidate",
    "get_interview_invitation_handoff",
    "list_interview_invitation_handoffs",
    "intake_interview_invitation_observation",
    "register_interview_invitation_candidate",
    "reject_interview_invitation_candidate",
]
