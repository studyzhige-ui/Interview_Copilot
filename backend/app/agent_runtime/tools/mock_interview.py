"""Concrete Career Agent entry into the existing Mock Interview Flow.

The Tool stays on one Tool Call while typed Client Actions collect prefill,
device-readiness and enter-live acknowledgements.  The existing Mock
Application Service remains the sole creator of records and runtime state.
"""

from __future__ import annotations

import asyncio
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError

from app.agent_runtime.tool_policy import ToolEffect
from app.agent_runtime.tool_registry import (
    AgentToolContext,
    ToolDefinition,
    registry,
)
from app.db.database import SessionLocal
from app.models.conversation_turn import ConversationTurn
from app.models.interview_record import InterviewRecord
from app.schemas.client_action import (
    MockEnterLivePayload,
    MockPrefillPayload,
    MockReadinessPayload,
)
from app.services.chat.client_action_service import (
    ClientActionConflictError,
    ClientActionUnavailableError,
    action_resolution,
    create_mock_client_action,
    find_mock_client_action,
    latest_handoff_client,
)
from app.services.interview import mock_flow, mock_runtime_service
from app.services.interview.interview_record_service import (
    STATUS_MOCK_IN_PROGRESS,
    InterviewOpportunityNotFoundError,
    interview_record_service,
)


class StartMockInterviewArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resume_id: str = Field(min_length=1, max_length=128)
    jd_text: str = Field(min_length=20, max_length=50_000)
    interviewer_style: Literal["friendly", "professional", "rigorous", "pressure"] = (
        "professional"
    )
    target_question_count: Literal[15, 20, 30] = 20
    job_opportunity_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=35,
    )


def _task_authorizes_mock_start(
    _arguments: dict[str, Any],
    _ctx: AgentToolContext,
    current_task: str,
) -> bool:
    normalized = current_task.casefold()
    # This predicate may only narrow approval requirements.  A keyword hit in
    # an explicit refusal ("不要开始模拟面试" / "do not start a mock") must
    # therefore fail closed and fall back to the exact-call confirmation path.
    # False negatives are safe here; false positives would perform a client
    # action the user explicitly retained.
    refusal_markers = (
        "不要",
        "别",
        "不需要",
        "无需",
        "暂不",
        "先不",
        "do not",
        "don't",
        "dont",
        "not now",
        "without starting",
    )
    if any(marker in normalized for marker in refusal_markers):
        return False
    start_words = ("开始", "启动", "进入", "start", "launch", "begin")
    mock_words = ("模拟面试", "mock interview", "mock")
    return any(word in normalized for word in start_words) and any(
        word in normalized for word in mock_words
    )


def _waiting_result(row, request, **facts: Any) -> dict[str, Any]:
    return {
        "error": "interaction_required",
        "interaction_type": "client_readiness",
        "reason": "client_action_required",
        "action_id": request.action_id,
        "action": request.action,
        "interaction": {
            "id": row.id,
            "version": row.version,
            "kind": row.kind,
        },
        **facts,
    }


def _terminal_client_result(row, *, phase: str) -> dict[str, Any] | None:
    resolution = action_resolution(row)
    if resolution is None:
        return None
    outcome = str(resolution.get("outcome") or "failed")
    if outcome == "acknowledged":
        return None
    return {
        "error": (
            "client_action_refused" if outcome == "refused" else "client_action_failed"
        ),
        "phase": phase,
        "action_id": resolution.get("action_id"),
        "reason": resolution.get("reason") or "Client action did not complete",
    }


def _load_turn(ctx: AgentToolContext, db) -> ConversationTurn | None:
    if not ctx.turn_id or not ctx.tool_call_id or ctx.user_pk is None:
        return None
    turn = db.get(ConversationTurn, ctx.turn_id)
    if (
        turn is None
        or turn.user_id != ctx.user_pk
        or turn.conversation_id != ctx.session_id
    ):
        return None
    return turn


def _run_start_mock(
    args: StartMockInterviewArgs,
    ctx: AgentToolContext,
) -> dict[str, Any]:
    db = SessionLocal()
    try:
        turn = _load_turn(ctx, db)
        if turn is None or not ctx.tool_call_id:
            return {
                "error": "client_action_unavailable",
                "reason": "Mock handoff requires an owned interactive Turn and Tool Call",
            }

        original_client_id, active_client_id = latest_handoff_client(
            db,
            turn=turn,
            tool_call_id=ctx.tool_call_id,
        )

        prefill = find_mock_client_action(
            db,
            turn_id=turn.id,
            tool_call_id=ctx.tool_call_id,
            action="mock_interview.prefill",
        )
        if prefill is None:
            # Validate source ownership/readiness and one-active-runtime before
            # asking the browser to present anything.  This performs no write
            # and does not claim that a Mock Runtime exists.
            if mock_runtime_service.get_active_runtime(db, user_id=ctx.user_id):
                return {
                    "error": "mock_already_in_progress",
                    "reason": "已有进行中的模拟面试，请先继续或放弃它",
                }
            mock_flow.resolve_resume_context(
                db,
                username=ctx.user_id,
                resume_id=args.resume_id,
            )
            try:
                interview_record_service.require_owned_job_opportunity(
                    db,
                    user_pk=turn.user_id,
                    job_opportunity_id=args.job_opportunity_id,
                )
            except InterviewOpportunityNotFoundError:
                return {
                    "error": "job_opportunity_not_found",
                    "reason": "The requested job opportunity is unavailable",
                }
            row, request = create_mock_client_action(
                db,
                turn=turn,
                tool_call_id=ctx.tool_call_id,
                action="mock_interview.prefill",
                payload=MockPrefillPayload(**args.model_dump()),
                original_client_id=original_client_id,
                bound_client_id=active_client_id,
            )
            db.commit()
            return _waiting_result(row, request)

        prefill_row, prefill_request = prefill
        if prefill_row.status == "pending":
            return _waiting_result(prefill_row, prefill_request)
        stopped = _terminal_client_result(prefill_row, phase="prefill")
        if stopped is not None:
            return stopped

        readiness = find_mock_client_action(
            db,
            turn_id=turn.id,
            tool_call_id=ctx.tool_call_id,
            action="mock_interview.check_readiness",
        )
        if readiness is None:
            original_client_id, active_client_id = latest_handoff_client(
                db,
                turn=turn,
                tool_call_id=ctx.tool_call_id,
            )
            row, request = create_mock_client_action(
                db,
                turn=turn,
                tool_call_id=ctx.tool_call_id,
                action="mock_interview.check_readiness",
                payload=MockReadinessPayload(),
                original_client_id=original_client_id,
                bound_client_id=active_client_id,
            )
            db.commit()
            return _waiting_result(row, request)

        readiness_row, readiness_request = readiness
        if readiness_row.status == "pending":
            return _waiting_result(readiness_row, readiness_request)
        stopped = _terminal_client_result(readiness_row, phase="readiness")
        if stopped is not None:
            return stopped
        readiness_result = action_resolution(readiness_row) or {}
        if readiness_result.get("readiness") != "ready":
            return {
                "error": "client_not_ready",
                "phase": "readiness",
                "reason": "The client did not prove microphone readiness",
            }

        enter_live = find_mock_client_action(
            db,
            turn_id=turn.id,
            tool_call_id=ctx.tool_call_id,
            action="mock_interview.enter_live",
        )
        if enter_live is None:
            if mock_runtime_service.get_active_runtime(db, user_id=ctx.user_id):
                return {
                    "error": "mock_already_in_progress",
                    "reason": "已有进行中的模拟面试，请先继续或放弃它",
                }
            started = mock_flow.start_mock(
                db,
                username=ctx.user_id,
                resume_id=args.resume_id,
                jd_text=args.jd_text,
                interviewer_style=args.interviewer_style,
                target_question_count=args.target_question_count,
                job_opportunity_id=args.job_opportunity_id,
            )
            original_client_id, active_client_id = latest_handoff_client(
                db,
                turn=turn,
                tool_call_id=ctx.tool_call_id,
            )
            row, request = create_mock_client_action(
                db,
                turn=turn,
                tool_call_id=ctx.tool_call_id,
                action="mock_interview.enter_live",
                payload=MockEnterLivePayload(
                    record_id=started.record.id,
                    conversation_id=started.conversation.id,
                ),
                original_client_id=original_client_id,
                bound_client_id=active_client_id,
            )
            # Runtime creation and its delivery action are one transaction:
            # there is no crash window that can orphan an uncorrelated run.
            db.commit()
            return _waiting_result(
                row,
                request,
                runtime={
                    "record_id": started.record.id,
                    "conversation_id": started.conversation.id,
                    "status": STATUS_MOCK_IN_PROGRESS,
                },
            )

        enter_row, enter_request = enter_live
        payload = enter_request.payload
        if not isinstance(payload, MockEnterLivePayload):
            return {"error": "invalid_client_action_state", "phase": "enter_live"}
        runtime = mock_runtime_service.get_runtime_for_record(
            db,
            interview_record_id=payload.record_id,
        )
        record = db.get(InterviewRecord, payload.record_id)
        runtime_proven = bool(
            runtime is not None
            and record is not None
            and record.user_id == turn.user_id
            and record.status == STATUS_MOCK_IN_PROGRESS
            and runtime.conversation_id == payload.conversation_id
        )
        if not runtime_proven:
            return {
                "error": "mock_runtime_missing",
                "record_id": payload.record_id,
                "phase": "runtime_verification",
            }
        if enter_row.status == "pending":
            return _waiting_result(
                enter_row,
                enter_request,
                runtime={
                    "record_id": payload.record_id,
                    "conversation_id": payload.conversation_id,
                    "status": STATUS_MOCK_IN_PROGRESS,
                },
            )
        stopped = _terminal_client_result(enter_row, phase="enter_live")
        if stopped is not None:
            return {
                **stopped,
                "runtime_started": True,
                "runtime": {
                    "record_id": payload.record_id,
                    "conversation_id": payload.conversation_id,
                    "status": STATUS_MOCK_IN_PROGRESS,
                },
                "ui_entered": False,
            }

        # The Runtime record proves the Flow started.  The separate client
        # result proves only that this product UI entered that existing Flow.
        return {
            "runtime": {
                "record_id": payload.record_id,
                "conversation_id": payload.conversation_id,
                "status": STATUS_MOCK_IN_PROGRESS,
            },
            "ui_entered": True,
            "handoff": "completed",
        }
    except ClientActionUnavailableError as exc:
        db.rollback()
        return {"error": "client_action_unavailable", "reason": str(exc)}
    except ClientActionConflictError as exc:
        db.rollback()
        return {"error": "client_action_conflict", "reason": str(exc)}
    except mock_flow.ResumeNotFoundError as exc:
        db.rollback()
        return {"error": "resume_not_found", "reason": str(exc)}
    except mock_flow.ResumeNotReadyError as exc:
        db.rollback()
        return {"error": "resume_not_ready", "reason": str(exc)}
    except IntegrityError:
        db.rollback()
        return {
            "error": "mock_already_in_progress",
            "reason": "已有进行中的模拟面试，请先继续或放弃它",
        }
    except Exception:
        db.rollback()
        return {
            "error": "mock_start_failed",
            "reason": "模拟面试启动失败，请稍后重试",
        }
    finally:
        db.close()


async def _start_mock_interview_handler(
    args: StartMockInterviewArgs,
    ctx: AgentToolContext,
) -> dict[str, Any]:
    return await asyncio.to_thread(_run_start_mock, args, ctx)


registry.register(
    ToolDefinition(
        name="start_mock_interview",
        description=(
            "Prepare and start the product's real-time Mock Interview Flow from an "
            "owned resume and explicit job description. The same Tool Call waits "
            "for typed product-client prefill, microphone readiness, and enter-live "
            "acknowledgements; only the returned runtime identity proves start."
        ),
        args_model=StartMockInterviewArgs,
        handler=_start_mock_interview_handler,
        effect=ToolEffect.CLIENT_ACTION,
        task_authorizer=_task_authorizes_mock_start,
        reversible=True,
        concurrency_safe=False,
        emoji="🎙️",
        prompt=(
            "Use only when the user explicitly asks to start a mock interview and "
            "the resume/JD sources are unambiguous. UI acknowledgements do not prove "
            "the Mock Runtime started; report start only from the runtime result."
        ),
    )
)


__all__ = ["StartMockInterviewArgs"]
