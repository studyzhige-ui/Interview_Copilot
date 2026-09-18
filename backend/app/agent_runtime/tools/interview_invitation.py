"""Thin Agent adapters for the VS-01 Shared Application Operations."""

from __future__ import annotations

import asyncio
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, PositiveInt

from app.agent_runtime.tool_policy import ToolEffect
from app.agent_runtime.tool_registry import AgentToolContext, ToolDefinition, registry
from app.career.application.interview_invitation_operations import (
    InterviewInvitationOperationError,
    confirm_interview_invitation,
    get_interview_invitation_handoff,
    reject_interview_invitation_candidate,
)
from app.career.application.invitation_interaction import (
    create_invitation_fact_confirmation,
    fact_confirmation_for_tool_call,
)
from app.db.database import SessionLocal
from app.models.conversation_turn import ConversationTurn
from app.schemas.client_action import InterviewPreparationOpenPayload
from app.schemas.interview_invitation import (
    CandidateConfirmationBasis,
    ConfirmInterviewInvitation,
    CreateInterview,
    ExplicitUserAssertionBasis,
    InterviewInvitationFacts,
    InterviewResolution,
    InvitationSourceReference,
    LinkExistingOpportunity,
    OpportunityResolution,
    RejectInterviewInvitationCandidate,
)
from app.services.chat.current_turn_source import (
    CurrentTurnSourceError,
    require_current_turn_user_message,
)
from app.services.chat.client_action_service import (
    ClientActionConflictError,
    ClientActionUnavailableError,
    action_resolution,
    create_client_action,
    find_client_action,
    latest_handoff_client,
)


class ConfirmAssertedInterviewInvitationArgs(BaseModel):
    """Facts explicitly asserted in the current admitted user message."""

    model_config = ConfigDict(extra="forbid")

    source_message_id: PositiveInt
    facts: InterviewInvitationFacts
    opportunity: OpportunityResolution
    interview: InterviewResolution = Field(default_factory=CreateInterview)


class ReviewInterviewInvitationCandidateArgs(BaseModel):
    """Open or resume the typed decision for one low-authority candidate."""

    model_config = ConfigDict(extra="forbid")

    candidate_id: str = Field(min_length=1, max_length=36)
    expected_candidate_version: PositiveInt


class OpenInterviewPreparationArgs(BaseModel):
    """Open one already-verified Interview in the initiating product client."""

    model_config = ConfigDict(extra="forbid")

    interview_id: str = Field(min_length=1, max_length=128)
    expected_interview_version: PositiveInt


def _runtime_scope(ctx: AgentToolContext) -> tuple[int, str, str, str]:
    if (
        ctx.user_pk is None
        or ctx.user_pk <= 0
        or not ctx.session_id
        or not ctx.turn_id
        or not ctx.tool_call_id
    ):
        raise ValueError("interview_invitation_runtime_scope_unavailable")
    return ctx.user_pk, ctx.session_id, ctx.turn_id, ctx.tool_call_id


def _operation_error(exc: Exception) -> dict[str, Any]:
    if isinstance(exc, InterviewInvitationOperationError):
        return {"error": exc.code, "detail": str(exc)}
    if isinstance(exc, CurrentTurnSourceError):
        return {"error": "current_task_confirmation_required", "detail": str(exc)}
    raise exc


def _confirm_asserted_sync(
    args: ConfirmAssertedInterviewInvitationArgs,
    ctx: AgentToolContext,
) -> dict[str, Any]:
    user_pk, session_id, turn_id, tool_call_id = _runtime_scope(ctx)
    db = SessionLocal()
    try:
        message = require_current_turn_user_message(
            db,
            user_pk=user_pk,
            turn_id=turn_id,
            conversation_id=session_id,
            message_id=args.source_message_id,
        )
        result = confirm_interview_invitation(
            db,
            user_pk=user_pk,
            command=ConfirmInterviewInvitation(
                idempotency_key=f"agent-tool:{turn_id}:{tool_call_id}",
                actor_kind="agent_on_behalf",
                asserted_at=message.created_at,
                confirmation_basis=ExplicitUserAssertionBasis(
                    kind="explicit_user_assertion",
                    source=InvitationSourceReference(
                        kind="user_message",
                        identity=f"conversation:{session_id}:message:{message.id}",
                        version=str(message.seq),
                    ),
                ),
                facts=args.facts,
                opportunity=args.opportunity,
                interview=args.interview,
                causation={
                    "conversation_id": session_id,
                    "turn_id": turn_id,
                    "tool_call_id": tool_call_id,
                },
            ),
        )
        db.commit()
        return {
            "operation": result.model_dump(mode="json"),
            "verified": result.verification.conclusion == "verified",
            "preparation_handoff_available": True,
        }
    except Exception as exc:
        db.rollback()
        return _operation_error(exc)
    finally:
        db.close()


async def _confirm_asserted_handler(
    args: ConfirmAssertedInterviewInvitationArgs,
    ctx: AgentToolContext,
) -> dict[str, Any]:
    return await asyncio.to_thread(_confirm_asserted_sync, args, ctx)


def _waiting(row, request) -> dict[str, Any]:
    return {
        "error": "interaction_required",
        "interaction_type": "fact_confirmation",
        "reason": "invitation_fact_confirmation_required",
        "interaction": {
            "id": row.id,
            "version": row.version,
            "kind": row.kind,
            "schema_version": row.schema_version,
            "request": request.model_dump(mode="json"),
        },
    }


def _review_candidate_sync(
    args: ReviewInterviewInvitationCandidateArgs,
    ctx: AgentToolContext,
) -> dict[str, Any]:
    user_pk, session_id, turn_id, tool_call_id = _runtime_scope(ctx)
    db = SessionLocal()
    try:
        state = fact_confirmation_for_tool_call(
            db,
            user_pk=user_pk,
            turn_id=turn_id,
            tool_call_id=tool_call_id,
        )
        if state is None:
            row = create_invitation_fact_confirmation(
                db,
                user_pk=user_pk,
                turn_id=turn_id,
                tool_call_id=tool_call_id,
                candidate_id=args.candidate_id,
                expected_candidate_version=args.expected_candidate_version,
            )
            request = fact_confirmation_for_tool_call(
                db,
                user_pk=user_pk,
                turn_id=turn_id,
                tool_call_id=tool_call_id,
            )
            if request is None:  # pragma: no cover - same transaction invariant
                raise RuntimeError("fact confirmation disappeared")
            db.commit()
            return _waiting(row, request[1])

        interaction, request, resolution = state
        if interaction.status == "pending" or resolution is None:
            return _waiting(interaction, request)
        if interaction.resolution_identity is None:
            return {"error": "fact_confirmation_identity_missing"}

        causation = {
            "conversation_id": session_id,
            "turn_id": turn_id,
            "tool_call_id": tool_call_id,
        }
        if resolution.decision == "reject":
            result = reject_interview_invitation_candidate(
                db,
                user_pk=user_pk,
                command=RejectInterviewInvitationCandidate(
                    idempotency_key=f"fact-decision:{interaction.id}",
                    actor_kind="agent_on_behalf",
                    candidate_id=request.candidate_reference.id,
                    expected_candidate_version=request.expected_candidate_version,
                    interaction_id=interaction.id,
                    decision_identity=interaction.resolution_identity,
                    reason=resolution.reason,
                    causation=causation,
                ),
            )
            db.commit()
            return {
                "operation": result.model_dump(mode="json"),
                "decision": "rejected",
                "canonical_write": False,
            }

        facts = (
            resolution.corrected_facts
            if resolution.decision == "correct_and_confirm"
            else InterviewInvitationFacts.model_validate(
                request.invitation_facts.model_dump(mode="json")
            )
        )
        if facts is None or resolution.opportunity is None:  # schema guard
            return {"error": "fact_confirmation_resolution_invalid"}
        result = confirm_interview_invitation(
            db,
            user_pk=user_pk,
            command=ConfirmInterviewInvitation(
                idempotency_key=f"fact-decision:{interaction.id}",
                actor_kind="agent_on_behalf",
                asserted_at=interaction.resolved_at,
                confirmation_basis=CandidateConfirmationBasis(
                    kind="candidate_confirmation",
                    candidate_id=request.candidate_reference.id,
                    expected_candidate_version=request.expected_candidate_version,
                    interaction_id=interaction.id,
                    decision_identity=interaction.resolution_identity,
                ),
                facts=facts,
                opportunity=resolution.opportunity,
                interview=resolution.interview,
                causation=causation,
            ),
        )
        db.commit()
        return {
            "operation": result.model_dump(mode="json"),
            "decision": resolution.decision,
            "verified": result.verification.conclusion == "verified",
            "preparation_handoff_available": True,
        }
    except Exception as exc:
        db.rollback()
        return _operation_error(exc)
    finally:
        db.close()


async def _review_candidate_handler(
    args: ReviewInterviewInvitationCandidateArgs,
    ctx: AgentToolContext,
) -> dict[str, Any]:
    return await asyncio.to_thread(_review_candidate_sync, args, ctx)


def _owned_turn(db, ctx: AgentToolContext) -> ConversationTurn | None:
    if not ctx.turn_id or ctx.user_pk is None:
        return None
    turn = db.get(ConversationTurn, ctx.turn_id)
    if (
        turn is None
        or turn.user_id != ctx.user_pk
        or turn.conversation_id != ctx.session_id
    ):
        return None
    return turn


def _open_preparation_sync(
    args: OpenInterviewPreparationArgs,
    ctx: AgentToolContext,
) -> dict[str, Any]:
    user_pk, _session_id, _turn_id, tool_call_id = _runtime_scope(ctx)
    db = SessionLocal()
    try:
        turn = _owned_turn(db, ctx)
        if turn is None:
            return {"error": "client_action_unavailable", "detail": "Turn unavailable"}
        handoff = get_interview_invitation_handoff(
            db,
            user_pk=user_pk,
            interview_id=args.interview_id,
        )
        if handoff.interview.version != args.expected_interview_version:
            return {
                "error": "stale_version",
                "detail": f"interview version is {handoff.interview.version}",
            }

        existing = find_client_action(
            db,
            turn_id=turn.id,
            tool_call_id=tool_call_id,
            action="interview.preparation.open",
        )
        if existing is None:
            original_client_id, active_client_id = latest_handoff_client(
                db,
                turn=turn,
                tool_call_id=tool_call_id,
            )
            row, request = create_client_action(
                db,
                turn=turn,
                tool_call_id=tool_call_id,
                action="interview.preparation.open",
                payload=InterviewPreparationOpenPayload(
                    interview_id=handoff.interview.id,
                    opportunity_id=handoff.opportunity.id,
                    expected_interview_version=args.expected_interview_version,
                    expected_opportunity_version=handoff.opportunity.version or 1,
                    source_operation_id=handoff.verification.operation_id,
                ),
                original_client_id=original_client_id,
                bound_client_id=active_client_id,
            )
            db.commit()
            return _waiting_client_action(row, request)

        row, request = existing
        resolution = action_resolution(row)
        if resolution is None:
            return _waiting_client_action(row, request)
        outcome = str(resolution.get("outcome") or "failed")
        if outcome != "acknowledged":
            return {
                "error": f"client_action_{outcome}",
                "reason": resolution.get("reason"),
                "domain_state": "verified",
                "manual_handoff_available": True,
                "interview": handoff.interview.model_dump(mode="json"),
            }
        return {
            "client_action_status": "acknowledged",
            "opened": True,
            "domain_state": "verified",
            "interview": handoff.interview.model_dump(mode="json"),
            "opportunity": handoff.opportunity.model_dump(mode="json"),
        }
    except (ClientActionConflictError, ClientActionUnavailableError) as exc:
        db.rollback()
        return {"error": "client_action_unavailable", "detail": str(exc)}
    except Exception as exc:
        db.rollback()
        return _operation_error(exc)
    finally:
        db.close()


def _waiting_client_action(row, request) -> dict[str, Any]:
    return {
        "error": "interaction_required",
        "interaction_type": "client_readiness",
        "reason": "client_action_required",
        "action_id": request.action_id,
        "action": request.action,
        "interaction": {"id": row.id, "version": row.version, "kind": row.kind},
    }


async def _open_preparation_handler(
    args: OpenInterviewPreparationArgs,
    ctx: AgentToolContext,
) -> dict[str, Any]:
    return await asyncio.to_thread(_open_preparation_sync, args, ctx)


def _task_authorizes_asserted_invitation(
    _arguments: dict[str, Any],
    _ctx: AgentToolContext,
    current_task: str,
) -> bool:
    task = " ".join(str(current_task or "").casefold().split())
    invitation = ("面试", "邀约", "邀请", "interview")
    assertion = ("收到", "安排", "定于", "确认", "scheduled", "invited")
    negation = ("不要记录", "不要确认", "只是问", "do not record", "don't record")
    return (
        any(word in task for word in invitation)
        and any(word in task for word in assertion)
        and not any(word in task for word in negation)
    )


def _task_authorizes_candidate_review(
    _arguments: dict[str, Any],
    _ctx: AgentToolContext,
    current_task: str,
) -> bool:
    task = " ".join(str(current_task or "").casefold().split())
    return any(word in task for word in ("面试邀请", "invitation candidate")) and any(
        word in task for word in ("确认", "核对", "review", "confirm")
    )


def _task_authorizes_preparation_open(
    _arguments: dict[str, Any],
    _ctx: AgentToolContext,
    current_task: str,
) -> bool:
    task = " ".join(str(current_task or "").casefold().split())
    refusal = ("不要打开", "先不准备", "do not open", "not now")
    return any(
        word in task for word in ("开始准备", "打开准备", "面试准备", "start prep")
    ) and not any(word in task for word in refusal)


def _candidate_resources(
    args: ReviewInterviewInvitationCandidateArgs,
    ctx: AgentToolContext,
) -> tuple[str, ...]:
    return (f"user:{ctx.user_pk}:interview-invitation-candidate:{args.candidate_id}",)


def _asserted_resources(
    args: ConfirmAssertedInterviewInvitationArgs,
    ctx: AgentToolContext,
) -> tuple[str, ...]:
    if isinstance(args.opportunity, LinkExistingOpportunity):
        return (
            f"user:{ctx.user_pk}:job-opportunity:{args.opportunity.opportunity_id}",
        )
    return (f"user:{ctx.user_pk}:interview-invitation:new",)


def _preparation_resources(
    args: OpenInterviewPreparationArgs,
    ctx: AgentToolContext,
) -> tuple[str, ...]:
    return (f"user:{ctx.user_pk}:interview:{args.interview_id}:preparation",)


registry.register(
    ToolDefinition(
        name="confirm_interview_invitation",
        description=(
            "Record an interview invitation only when the current user message "
            "explicitly asserts the complete scheduled facts and Opportunity choice."
        ),
        args_model=ConfirmAssertedInterviewInvitationArgs,
        handler=_confirm_asserted_handler,
        effect=ToolEffect.INTERNAL_WRITE,
        task_authorizer=_task_authorizes_asserted_invitation,
        resource_resolver=_asserted_resources,
        concurrency_safe=False,
        emoji="📅",
        prompt=(
            "Use only for a complete, explicit current-user assertion. If facts came "
            "from an Observation or contain inference, register/review a candidate "
            "and obtain fact_confirmation instead. A verified result creates no "
            "NextAction and performs no email or calendar write."
        ),
    )
)

registry.register(
    ToolDefinition(
        name="open_interview_preparation",
        description=(
            "Open the verified Interview preparation context in the initiating "
            "product client. This performs no Career Domain or external write."
        ),
        args_model=OpenInterviewPreparationArgs,
        handler=_open_preparation_handler,
        effect=ToolEffect.CLIENT_ACTION,
        task_authorizer=_task_authorizes_preparation_open,
        resource_resolver=_preparation_resources,
        reversible=True,
        concurrency_safe=False,
        emoji="🧭",
        prompt=(
            "Call only after an invitation Operation returned verified=true or when "
            "the user explicitly asks to open an already verified Interview. A client "
            "acknowledgement means only that the object context opened."
        ),
    )
)

registry.register(
    ToolDefinition(
        name="review_interview_invitation_candidate",
        description=(
            "Open and resume the durable fact confirmation for one evidence-backed "
            "interview invitation candidate. The same Tool Call executes the user's "
            "confirm, correction, or rejection after CAS resolution."
        ),
        args_model=ReviewInterviewInvitationCandidateArgs,
        handler=_review_candidate_handler,
        effect=ToolEffect.INTERNAL_WRITE,
        task_authorizer=_task_authorizes_candidate_review,
        resource_resolver=_candidate_resources,
        concurrency_safe=False,
        emoji="📨",
        prompt=(
            "Never infer the decision. First dispatch creates fact_confirmation@1; "
            "after the user resolves it, the same call resumes and returns the "
            "verified Operation result."
        ),
    )
)


__all__ = [
    "ConfirmAssertedInterviewInvitationArgs",
    "OpenInterviewPreparationArgs",
    "ReviewInterviewInvitationCandidateArgs",
]
