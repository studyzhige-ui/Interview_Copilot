"""Fixture-only proactive Career Loop adapter for VS-01.

The adapter deliberately stops at a durable fact-confirmation Interaction.
It cannot auto-apply canonical state and never claims a real connector ran.
"""

from __future__ import annotations

import hashlib
import json

from sqlalchemy.orm import Session

from app.career.application.interview_invitation_operations import (
    intake_interview_invitation_observation,
    register_interview_invitation_candidate,
)
from app.career.application.invitation_interaction import (
    create_invitation_fact_confirmation,
)
from app.db.types import utc_now
from app.models.agent_execution import AgentToolCall
from app.models.agent_interaction import AgentInteraction
from app.models.chat import Conversation
from app.models.conversation_turn import ConversationTurn
from app.schemas.interview_invitation import (
    FixtureInterviewInvitationInput,
    FixtureInterviewInvitationResult,
    IntakeInterviewInvitationObservation,
    InvitationFieldEvidence,
    InvitationSourceReference,
    ObjectReference,
    RegisterInterviewInvitationCandidate,
)
from app.services.chat.interaction_service import list_pending_interactions


def _value_hash(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _pending_interaction_for_candidate(
    db: Session,
    *,
    user_pk: int,
    candidate_id: str,
) -> tuple[AgentInteraction, ConversationTurn] | None:
    for interaction, turn in list_pending_interactions(
        db,
        user_id=user_pk,
        kinds=("fact_confirmation",),
    ):
        request = (
            interaction.request_json
            if isinstance(interaction.request_json, dict)
            else {}
        )
        reference = request.get("candidate_reference")
        if isinstance(reference, dict) and reference.get("id") == candidate_id:
            return interaction, turn
    return None


def _create_waiting_review_turn(
    db: Session,
    *,
    user_pk: int,
    candidate_id: str,
    candidate_version: int,
) -> tuple[ConversationTurn, AgentInteraction]:
    conversation = Conversation(
        user_id=user_pk,
        title="面试邀请待确认",
        type="general",
        mode="agent",
        execution_mode="standard",
    )
    db.add(conversation)
    db.flush()
    message = json.dumps(
        {
            "kind": "fixture_interview_invitation_review",
            "candidate_id": candidate_id,
            "candidate_version": candidate_version,
            "instruction": "核对并确认这条面试邀请候选事实；未经用户决定不得写正式状态。",
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    turn = ConversationTurn(
        conversation_id=conversation.id,
        user_id=user_pk,
        mode="agent",
        execution_mode="standard",
        message=message,
        object_references_json=[
            {
                "kind": "interview_invitation_candidate",
                "object_id": candidate_id,
                "version": candidate_version,
            }
        ],
        status="waiting",
        waiting_reason="interaction",
        started_at=utc_now(),
    )
    db.add(turn)
    db.flush()
    tool_call_id = f"fixture-review:{candidate_id}"
    db.add(
        AgentToolCall(
            call_id=tool_call_id,
            turn_id=turn.id,
            session_id=conversation.id,
            user_id=user_pk,
            tool_name="review_interview_invitation_candidate",
            effect="internal_write",
            arguments_json={
                "candidate_id": candidate_id,
                "expected_candidate_version": candidate_version,
            },
            timeout_seconds=30,
            status="waiting",
            dispatch_generation=1,
            policy_decision="allow",
            policy_reason="fixture_waits_for_fact_confirmation",
            resource_identities_json=[
                f"user:{user_pk}:interview-invitation-candidate:{candidate_id}"
            ],
        )
    )
    db.flush()
    interaction = create_invitation_fact_confirmation(
        db,
        user_pk=user_pk,
        turn_id=turn.id,
        tool_call_id=tool_call_id,
        candidate_id=candidate_id,
        expected_candidate_version=candidate_version,
    )
    conversation.active_turn_id = turn.id
    conversation.updated_at = utc_now()
    db.add(conversation)
    db.flush()
    return turn, interaction


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
    candidate = registered.candidate
    pending = _pending_interaction_for_candidate(
        db,
        user_pk=user_pk,
        candidate_id=candidate.id,
    )
    if pending is None and candidate.status == "pending_confirmation":
        turn, interaction = _create_waiting_review_turn(
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
