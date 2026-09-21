"""Recover only audited, idempotent LOCAL invitation transactions.

Never clear an external side-effect fence, restart an unknown model request, or
infer a user decision. The shared Operation keeps the exact original key and
serializes confirmation with its durable receipt. Redis delivery is a hint; the
same Turn and its saved decision remain authoritative across worker loss.
"""

from __future__ import annotations

from datetime import datetime
from sqlalchemy.orm import Session
from app.core.config import settings
from app.db.types import utc_now
from app.models.agent_execution import AgentToolCall
from app.models.agent_interaction import AgentInteraction
from app.models.chat import Conversation
from app.models.conversation_turn import ConversationTurn
from app.models.model_dispatch import AgentModelDispatch

_LOCAL_TOOLS = frozenset(
    {"confirm_interview_invitation", "review_interview_invitation_candidate"}
)
_RECOVERY_EVENT = "local_invitation_recovery"


def is_local_recovery_call(call: AgentToolCall) -> bool:
    return (
        call.tool_name in _LOCAL_TOOLS
        and call.effect == "internal_write"
        and call.status == "waiting"
        and not call.provider_identity
        and not call.connection_identity
        and any(
            isinstance(item, dict) and item.get("event") == _RECOVERY_EVENT
            for item in (call.timeline_json or [])
        )
    )


def recover_invitation_turn(
    db: Session, *, turn_id: str, stale_before: datetime
) -> str | None:
    """Recheck under the lease lock, then restore waiting or queue the same Turn.

    Return None for unsupported/unsafe cases; the generic interrupted terminal
    path keeps all their existing side-effect fences. This function commits only
    when it actually recovers. No provider or business write is performed here.
    """
    hint = db.get(ConversationTurn, turn_id)
    if hint is None:
        return None
    conversation = (
        db.query(Conversation)
        .filter_by(id=hint.conversation_id)
        .with_for_update()
        .populate_existing()
        .one_or_none()
    )
    turn = (
        db.query(ConversationTurn)
        .filter_by(id=turn_id)
        .with_for_update()
        .populate_existing()
        .one_or_none()
    )
    if (
        conversation is None
        or turn is None
        or conversation.active_turn_id != turn.id
        or turn.mode != "agent"
        or turn.assistant_message_seq is not None
        or turn.status not in {"pending", "running"}
        or turn.interrupt_submission_id is not None
        or (
            turn.status == "running"
            and int(turn.recovery_attempts or 0) >= settings.TURN_RECOVERY_MAX_ATTEMPTS
        )
    ):
        return None
    last = (
        (turn.dispatch_requested_at or turn.created_at)
        if turn.status == "pending"
        else (turn.heartbeat_at or turn.started_at or turn.created_at)
    )
    if last is None or last >= stale_before:
        return None
    uncertain_model = (
        db.query(AgentModelDispatch.id)
        .filter(
            AgentModelDispatch.turn_id == turn_id,
            AgentModelDispatch.status.in_(("running", "unknown", "cancelled")),
        )
        .first()
    )
    if uncertain_model is not None:
        return None
    calls = (
        db.query(AgentToolCall)
        .filter_by(turn_id=turn_id)
        .order_by(AgentToolCall.id)
        .with_for_update()
        .all()
    )
    if not calls:
        if (
            turn.status != "pending"
            or db.query(AgentModelDispatch.id).filter_by(turn_id=turn.id).first()
            is not None
        ):
            return None
        # No execution started: redeliver the same durable admission. A broker
        # outage must not consume a worker-recovery attempt or lose user input.
        turn.dispatch_requested_at = utc_now()
        db.commit()
        return "pending"
    # No unexecuted batch tail or other unknown effect is implicitly resumed.
    live = [
        c for c in calls if c.status in {"running", "unknown", "waiting", "deferred"}
    ]
    call = live[0] if len(live) == 1 else calls[-1] if not live else None
    if (
        call is None
        or call.tool_name not in _LOCAL_TOOLS
        or call.effect != "internal_write"
        or call.user_id != turn.user_id
        or call.session_id != turn.conversation_id
        or call.provider_identity
        or call.connection_identity
        or call is not calls[-1]
    ):
        return None
    if (
        db.query(AgentModelDispatch.id)
        .filter(
            AgentModelDispatch.turn_id == turn_id,
            AgentModelDispatch.started_at > call.started_at,
        )
        .first()
        is not None
    ):
        return None
    # Validate persisted input identity before granting a narrowly scoped replay.
    from app.agent_runtime.tools.interview_invitation import (
        ConfirmAssertedInterviewInvitationArgs,
        ReviewInterviewInvitationCandidateArgs,
    )
    from app.schemas.interview_invitation import (
        FactConfirmationRequest,
        FactConfirmationResolution,
    )

    try:
        if call.tool_name == "review_interview_invitation_candidate":
            args = ReviewInterviewInvitationCandidateArgs.model_validate(
                call.arguments_json
            )
            interaction = (
                db.query(AgentInteraction)
                .filter_by(
                    turn_id=turn_id,
                    tool_call_id=call.call_id,
                    kind="fact_confirmation",
                )
                .one_or_none()
            )
            if interaction is None or interaction.schema_version != 1:
                return None
            request = FactConfirmationRequest.model_validate(interaction.request_json)
            if (
                request.candidate_reference.id != args.candidate_id
                or request.expected_candidate_version != args.expected_candidate_version
            ):
                return None
            if interaction.status == "pending":
                target = "waiting"
            elif (
                interaction.status in {"resolved", "rejected"}
                and interaction.resolution_identity
            ):
                decision = FactConfirmationResolution.model_validate(
                    interaction.resolution_json
                )
                if (decision.decision == "reject") != (
                    interaction.status == "rejected"
                ):
                    return None
                target = "pending"
            else:
                return None
        else:
            args = ConfirmAssertedInterviewInvitationArgs.model_validate(
                call.arguments_json
            )
            from app.conversation.application.current_turn_source import (
                require_current_turn_user_message,
            )

            require_current_turn_user_message(
                db,
                user_pk=turn.user_id,
                turn_id=turn.id,
                conversation_id=turn.conversation_id,
                message_id=args.source_message_id,
            )
            target = "pending"
    except (ValueError, LookupError, PermissionError):
        return None
    now = utc_now()
    worker_lost = turn.status == "running"
    generation = int(turn.dispatch_generation or 1) + int(worker_lost)
    call.status = "waiting"
    call.timeline_json = [
        *(call.timeline_json or [])[-63:],
        {
            "event": _RECOVERY_EVENT,
            "dispatch_generation": generation,
            "at": now.isoformat(),
            "status": "waiting",
        },
    ]
    turn.status = target
    turn.waiting_reason = "interaction" if target == "waiting" else None
    turn.dispatch_generation = generation
    turn.dispatch_requested_at = now
    turn.recovery_attempts = int(turn.recovery_attempts or 0) + int(worker_lost)
    turn.owner_id = None
    turn.heartbeat_at = None
    turn.error = None
    db.commit()
    return target
