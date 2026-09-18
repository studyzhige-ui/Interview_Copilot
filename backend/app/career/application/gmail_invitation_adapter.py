"""Gmail observations -> shared low-authority candidate -> explicit user review.

This adapter performs no provider I/O, adds no permission and never calls the
confirmation operation. The caller has validated account/task/trigger scope.
Replayed source versions reuse the same candidate, including a terminal one.
"""

from __future__ import annotations

import hashlib
import json

from sqlalchemy.orm import Session

from app.models.gmail_observation import GmailObservation, GmailObservationSnapshot
from app.models.interview_invitation import (
    InterviewInvitationCandidate,
    InterviewInvitationObservation,
    InterviewInvitationSourceSnapshot,
)
from app.schemas.interview_invitation import (
    IntakeInterviewInvitationObservation,
    InterviewInvitationCandidateFacts,
    InvitationFieldEvidence,
    InvitationSourceReference,
    RegisterInterviewInvitationCandidate,
)
from .interview_invitation_operations import (
    InvitationOwnershipError,
    intake_interview_invitation_observation,
    register_interview_invitation_candidate,
)
from .invitation_review_service import (
    create_waiting_review_turn,
    pending_interaction_for_candidate,
)


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode()
    ).hexdigest()


def _source_identity(observation: GmailObservation) -> str:
    # A valid 256-char provider ID plus account prefix need not fit our source
    # identity field. Hash that component; exact provider IDs stay in the snapshot.
    return f"gmail:{observation.gmail_account_id}:{hashlib.sha256(observation.provider_message_id.encode()).hexdigest()}"


def read_invitation_handoff(
    db: Session, *, observation: GmailObservation
) -> dict | None:
    """Rebuild status from its canonical owner; never re-run provider work."""
    candidate = (
        db.query(InterviewInvitationCandidate)
        .join(
            InterviewInvitationObservation,
            InterviewInvitationCandidate.observation_id
            == InterviewInvitationObservation.id,
        )
        .join(
            InterviewInvitationSourceSnapshot,
            InterviewInvitationObservation.source_snapshot_id
            == InterviewInvitationSourceSnapshot.id,
        )
        .filter(
            InterviewInvitationCandidate.user_id == observation.user_id,
            InterviewInvitationSourceSnapshot.user_id == observation.user_id,
            InterviewInvitationSourceSnapshot.source_kind == "gmail",
            InterviewInvitationSourceSnapshot.source_identity
            == _source_identity(observation),
        )
        .order_by(
            InterviewInvitationSourceSnapshot.observed_at.desc(),
            InterviewInvitationCandidate.created_at.desc(),
        )
        .first()
    )
    if candidate is None:
        return None
    pending = (
        pending_interaction_for_candidate(
            db, user_pk=observation.user_id, candidate_id=candidate.id
        )
        if candidate.status in {"needs_clarification", "pending_confirmation"}
        else None
    )
    interaction, turn = pending if pending is not None else (None, None)
    return {
        "candidate_id": candidate.id,
        "candidate_version": candidate.version,
        "candidate_status": candidate.status,
        "conversation_id": turn.conversation_id if turn else None,
        "turn_id": turn.id if turn else None,
        "interaction_id": interaction.id if interaction else None,
        "canonical_write": False,
    }


def route_gmail_invitation(
    db: Session,
    *,
    user_pk: int,
    observation: GmailObservation,
    snapshot: GmailObservationSnapshot,
    facts: InterviewInvitationCandidateFacts | None,
    confidence: float | None,
) -> dict:
    if observation.user_id != user_pk or snapshot.observation_id != observation.id:
        raise InvitationOwnershipError("gmail observation snapshot")
    # IDs are source identities, never instructions. Only the captured fields
    # actually available are retained (a snippet is not a claimed full email).
    source_identity = _source_identity(observation)
    intake = intake_interview_invitation_observation(
        db,
        user_pk=user_pk,
        command=IntakeInterviewInvitationObservation(
            idempotency_key=f"gmail-invitation:{snapshot.id}:intake",
            actor_kind="system_connector",
            source_kind="gmail",
            source_identity=source_identity,
            source_version=snapshot.snapshot_version,
            observed_at=snapshot.observed_at,
            payload={
                "gmail_snapshot_id": snapshot.id,
                "provider_message_id": snapshot.provider_message_id,
                "provider_thread_id": snapshot.provider_thread_id,
                "subject": snapshot.subject,
                "snippet": snapshot.snippet,
                "from_hint": snapshot.from_hint,
                "content_available": snapshot.content_available,
                "coverage": "captured_subject_and_snippet_only",
            },
        ),
    )
    candidate = (
        db.query(InterviewInvitationCandidate)
        .filter_by(user_id=user_pk, observation_id=intake.observation.id)
        .order_by(InterviewInvitationCandidate.created_at.desc())
        .first()
    )
    if candidate is None:
        values = facts or InterviewInvitationCandidateFacts()
        source = InvitationSourceReference(
            kind="gmail",
            identity=source_identity,
            version=snapshot.snapshot_version,
            snapshot_id=intake.source_snapshot_id,
        )
        evidence = [
            InvitationFieldEvidence(field_name=k, source=source, value_hash=_digest(v))
            for k, v in values.model_dump(mode="json").items()
            if v is not None
        ]
        registered = register_interview_invitation_candidate(
            db,
            user_pk=user_pk,
            command=RegisterInterviewInvitationCandidate(
                idempotency_key=f"gmail-invitation:{snapshot.id}:candidate",
                actor_kind="system_connector",
                observation_id=intake.observation.id,
                expected_observation_version=intake.observation.version,
                source_kind="observation",
                source_identity=intake.observation.id,
                source_version=str(intake.observation.version),
                facts=values,
                field_provenance=evidence,
                confidence=confidence,
                extractor_version="gmail-invitation-proposal@1",
            ),
        )
        candidate = db.get(InterviewInvitationCandidate, registered.candidate.id)
    if candidate is None:  # pragma: no cover
        raise RuntimeError("invitation candidate disappeared")
    pending = pending_interaction_for_candidate(
        db, user_pk=user_pk, candidate_id=candidate.id
    )
    if pending is not None:
        interaction, turn = pending
    elif candidate.status in {"needs_clarification", "pending_confirmation"}:
        turn, interaction = create_waiting_review_turn(
            db,
            user_pk=user_pk,
            candidate_id=candidate.id,
            candidate_version=candidate.version,
            origin="gmail",
        )
    else:
        interaction, turn = None, None
    return {
        "candidate_id": candidate.id,
        "candidate_version": candidate.version,
        "candidate_status": candidate.status,
        "conversation_id": turn.conversation_id if turn else None,
        "turn_id": turn.id if turn else None,
        "interaction_id": interaction.id if interaction else None,
        "canonical_write": False,
    }
