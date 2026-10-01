"""Shared, controller-authored review ingress for fixture and Gmail observations.

No source text is promoted to a user instruction. This creates only a waiting
Turn and typed decision; the invitation Operation remains the sole write owner.
"""

import json
from sqlalchemy.orm import Session
from app.db.types import utc_now
from app.models.agent_execution import AgentToolCall
from app.models.agent_interaction import AgentInteraction
from app.models.chat import Conversation
from app.models.conversation_turn import ConversationTurn
from .invitation_interaction import create_invitation_fact_confirmation


def review_interaction_for_candidate(
    db: Session,
    *,
    user_pk: int,
    candidate_id: str,
    candidate_version: int,
) -> tuple[AgentInteraction, ConversationTurn] | None:
    """Reuse the exact review even after a decision but before its operation.

    A source replay is not a new request for user approval. In particular,
    queue failure or worker death after a saved decision must not create a
    second Turn/Interaction. The original Turn owns recovery; terminal candidate
    versions are projected by the caller and never reopened here.
    """
    return (
        db.query(AgentInteraction, ConversationTurn)
        .join(ConversationTurn, ConversationTurn.id == AgentInteraction.turn_id)
        .filter(
            ConversationTurn.user_id == user_pk,
            AgentInteraction.kind == "fact_confirmation",
            AgentInteraction.schema_version == 1,
            AgentInteraction.request_json["candidate_reference"]["id"].as_string()
            == candidate_id,
            AgentInteraction.request_json["expected_candidate_version"].as_integer()
            == candidate_version,
        )
        .order_by(AgentInteraction.created_at.desc(), AgentInteraction.id)
        .first()
    )


def create_waiting_review_turn(
    db: Session,
    *,
    user_pk: int,
    candidate_id: str,
    candidate_version: int,
    origin: str = "fixture",
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
            "kind": f"{origin}_interview_invitation_review",
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
    tool_call_id = f"{origin}-review:{candidate_id}"
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
            policy_reason=f"{origin}_waits_for_fact_confirmation",
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
