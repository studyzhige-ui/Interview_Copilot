"""Typed fact-confirmation boundary for VS-01 invitation candidates."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.agent_interaction import AgentInteraction
from app.models.conversation_turn import ConversationTurn
from app.models.interview_invitation import InterviewInvitationCandidate
from app.models.job_opportunity import JobOpportunity
from app.schemas.interview_invitation import (
    FactConfirmationRequest,
    FactConfirmationResolution,
    InterviewInvitationCandidateFacts,
    InvitationFieldEvidence,
    InvitationSourceReference,
    ObjectReference,
    OpportunityMatchOption,
)
from app.services.chat.interaction_service import create_pending_interaction

from .interview_invitation_context import compile_invitation_confirmation_context
from .interview_invitation_operations import (
    InvitationObjectNotFoundError,
    InvitationOwnershipError,
    InvitationStateConflictError,
    InvitationVersionConflictError,
)


def _owned_candidate(
    db: Session,
    *,
    user_pk: int,
    candidate_id: str,
) -> InterviewInvitationCandidate:
    candidate = (
        db.query(InterviewInvitationCandidate)
        .filter(
            InterviewInvitationCandidate.id == candidate_id,
            InterviewInvitationCandidate.user_id == user_pk,
        )
        .one_or_none()
    )
    if candidate is None:
        raise InvitationObjectNotFoundError("interview invitation candidate")
    return candidate


def _opportunity_options(
    db: Session,
    *,
    user_pk: int,
    facts: InterviewInvitationCandidateFacts,
) -> list[OpportunityMatchOption]:
    if not facts.company_name or not facts.job_title:
        return []
    company = facts.company_name.casefold().strip()
    title = facts.job_title.casefold().strip()
    candidates = (
        db.query(JobOpportunity)
        .filter(
            JobOpportunity.user_id == user_pk,
            JobOpportunity.archived_at.is_(None),
        )
        .order_by(JobOpportunity.updated_at.desc())
        .limit(100)
        .all()
    )
    return [
        OpportunityMatchOption(
            opportunity_id=row.id,
            expected_version=row.version,
            company_name=row.company_name,
            job_title=row.job_title,
            current_step=row.current_step,
        )
        for row in candidates
        if row.company_name.casefold().strip() == company
        and row.job_title.casefold().strip() == title
    ][:20]


def _source_references(
    evidence: list[InvitationFieldEvidence],
) -> list[InvitationSourceReference]:
    unique: dict[
        tuple[str, str, str | None, str | None], InvitationSourceReference
    ] = {}
    for item in evidence:
        source = item.source
        unique[(source.kind, source.identity, source.version, source.snapshot_id)] = (
            source
        )
    return list(unique.values())


def create_invitation_fact_confirmation(
    db: Session,
    *,
    user_pk: int,
    turn_id: str,
    tool_call_id: str,
    candidate_id: str,
    expected_candidate_version: int,
) -> AgentInteraction:
    """Create the owning Turn's one durable ``fact_confirmation@1`` request."""

    turn = db.get(ConversationTurn, turn_id)
    if turn is None:
        raise InvitationObjectNotFoundError("conversation turn")
    if turn.user_id != user_pk:
        raise InvitationOwnershipError("conversation turn")
    candidate = _owned_candidate(db, user_pk=user_pk, candidate_id=candidate_id)
    if candidate.version != expected_candidate_version:
        raise InvitationVersionConflictError(
            f"candidate version is {candidate.version}"
        )
    if candidate.status == "needs_clarification":
        raise InvitationStateConflictError(
            "candidate requires clarification before fact confirmation"
        )
    if candidate.status != "pending_confirmation":
        raise InvitationStateConflictError(
            f"candidate cannot be confirmed from {candidate.status}"
        )

    facts = InterviewInvitationCandidateFacts.model_validate(candidate.facts_json)
    evidence = [
        InvitationFieldEvidence.model_validate(item)
        for item in candidate.field_provenance_json
    ]
    opportunity_options = _opportunity_options(
        db,
        user_pk=user_pk,
        facts=facts,
    )
    context_package = compile_invitation_confirmation_context(
        db,
        user_pk=user_pk,
        turn=turn,
        tool_call_id=tool_call_id,
        candidate=candidate,
        facts=facts,
        evidence=evidence,
        opportunity_options=opportunity_options,
    )
    request = FactConfirmationRequest(
        candidate_reference=ObjectReference(
            kind="interview_invitation_candidate",
            id=candidate.id,
            version=candidate.version,
        ),
        expected_candidate_version=candidate.version,
        invitation_facts=facts,
        field_provenance=evidence,
        missing_or_uncertain_fields=list(candidate.missing_fields_json or []),
        conflicts=list(candidate.conflicts_json or []),
        source_and_evidence_references=_source_references(evidence),
        opportunity_match_options=opportunity_options,
        context_package=context_package,
    )
    return create_pending_interaction(
        db,
        turn_id=turn_id,
        user_id=user_pk,
        kind="fact_confirmation",
        schema_version=1,
        request=request,
        tool_call_id=tool_call_id,
    )


def fact_confirmation_for_tool_call(
    db: Session,
    *,
    user_pk: int,
    turn_id: str,
    tool_call_id: str,
) -> (
    tuple[AgentInteraction, FactConfirmationRequest, FactConfirmationResolution | None]
    | None
):
    row = (
        db.query(AgentInteraction)
        .join(ConversationTurn, ConversationTurn.id == AgentInteraction.turn_id)
        .filter(
            AgentInteraction.turn_id == turn_id,
            AgentInteraction.tool_call_id == tool_call_id,
            AgentInteraction.kind == "fact_confirmation",
            ConversationTurn.user_id == user_pk,
        )
        .order_by(AgentInteraction.created_at.desc())
        .one_or_none()
    )
    if row is None:
        return None
    request = FactConfirmationRequest.model_validate(row.request_json)
    resolution = (
        FactConfirmationResolution.model_validate(row.resolution_json)
        if row.status in {"resolved", "rejected"}
        and isinstance(row.resolution_json, dict)
        else None
    )
    return row, request, resolution


__all__ = [
    "create_invitation_fact_confirmation",
    "fact_confirmation_for_tool_call",
]
