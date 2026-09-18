"""Fixture-only proactive Career Loop adapter for VS-01.

The adapter deliberately stops at a durable fact-confirmation Interaction.
It cannot auto-apply canonical state and never claims a real connector ran.
"""

from __future__ import annotations

import hashlib
import json

from sqlalchemy.orm import Session
from .invitation_review_service import (
    pending_interaction_for_candidate,
    create_waiting_review_turn,
)

from app.career.application.interview_invitation_operations import (
    intake_interview_invitation_observation,
    get_interview_invitation_candidate,
    register_interview_invitation_candidate,
)
from app.schemas.interview_invitation import (
    FixtureInterviewInvitationInput,
    FixtureInterviewInvitationResult,
    IntakeInterviewInvitationObservation,
    InvitationFieldEvidence,
    InvitationSourceReference,
    ObjectReference,
    RegisterInterviewInvitationCandidate,
)


def _value_hash(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def ingest_fixture_interview_invitation(
    db: Session,
    *,
    user_pk: int,
    command: FixtureInterviewInvitationInput,
) -> FixtureInterviewInvitationResult:
    """Ingest one deterministic fixture and stop before canonical state."""

    intake = intake_interview_invitation_observation(
        db,
        user_pk=user_pk,
        command=IntakeInterviewInvitationObservation(
            idempotency_key=f"{command.idempotency_key}:intake",
            actor_kind="automation",
            source_kind="fixture",
            source_identity=command.source_identity,
            source_version=command.source_version,
            observed_at=command.observed_at,
            payload=command.raw_payload,
        ),
    )
    facts = command.extracted_facts.model_dump(mode="json")
    source = InvitationSourceReference(
        kind="fixture",
        identity=command.source_identity,
        version=command.source_version,
        snapshot_id=intake.source_snapshot_id,
    )
    evidence = [
        InvitationFieldEvidence(
            field_name=field,
            source=source,
            value_hash=_value_hash(value),
        )
        for field, value in facts.items()
        if value is not None
    ]
    registered = register_interview_invitation_candidate(
        db,
        user_pk=user_pk,
        command=RegisterInterviewInvitationCandidate(
            idempotency_key=f"{command.idempotency_key}:candidate",
            actor_kind="automation",
            observation_id=intake.observation.id,
            expected_observation_version=intake.observation.version,
            source_kind="observation",
            source_identity=intake.observation.id,
            source_version=str(intake.observation.version),
            facts=command.extracted_facts,
            field_provenance=evidence,
            missing_fields=command.missing_fields,
            conflicts=command.conflicts,
            confidence=command.confidence,
            extractor_version=command.extractor_version,
        ),
    )
    # The idempotent registration receipt may predate a user decision. Read
    # the live owner so replay cannot recreate a stale confirmation window.
    candidate = get_interview_invitation_candidate(
        db, user_pk=user_pk, candidate_id=registered.candidate.id
    )
    pending = pending_interaction_for_candidate(
        db,
        user_pk=user_pk,
        candidate_id=candidate.id,
    )
    if pending is None and candidate.status in {
        "pending_confirmation",
        "needs_clarification",
    }:
        turn, interaction = create_waiting_review_turn(
            db,
            user_pk=user_pk,
            candidate_id=candidate.id,
            candidate_version=candidate.version,
        )
    elif pending is not None:
        interaction, turn = pending
    else:
        interaction = None
        turn = None

    return FixtureInterviewInvitationResult(
        source_snapshot_id=intake.source_snapshot_id,
        observation=ObjectReference(
            kind="interview_invitation_observation",
            id=intake.observation.id,
            version=intake.observation.version,
        ),
        candidate=ObjectReference(
            kind="interview_invitation_candidate",
            id=candidate.id,
            version=candidate.version,
        ),
        conversation_id=turn.conversation_id if turn is not None else None,
        turn_id=turn.id if turn is not None else None,
        interaction=(
            ObjectReference(
                kind="agent_interaction",
                id=interaction.id,
                version=interaction.version,
            )
            if interaction is not None
            else None
        ),
        status=candidate.status,
        deduplicated=intake.deduplicated,
        replayed=intake.replayed and registered.replayed,
    )


__all__ = ["ingest_fixture_interview_invitation"]
