"""SSE chat streaming endpoint.

One-way server-to-client streaming for chat turns. Frontend posts a
message JSON, server emits ``data: {type, content}\\n\\n`` frames as
the LLM streams its response, terminated by a ``{type:"done"}`` frame.

Why SSE and not WebSocket: every major chat API (OpenAI, Anthropic,
Gemini) uses SSE for one-way text streaming. SSE rides plain HTTP so it
inherits standard JWT bearer auth, browser keep-alive, proxy/CDN/
firewall friendliness — none of the complexity of WS subprotocol token
plumbing or socket-life-cycle bookkeeping. The WebSocket path that used
to live here was removed once the frontend migrated to SSE; bring it
back ONLY when realtime voice (bidirectional audio frames) lands and
WS is the right transport for that — text alone never justifies WS.

Wire format (Stage-G — unified across chat + agent paths):
    Each frame is one :class:`HarnessEvent` serialized as JSON. The
    frontend dispatches on ``event.type``:

      status / text_delta / text / error / done   — emitted by both
      sources                                     — L1 RAG only, once
                                                    before generation
      tool_start / tool_done / budget             — agent usage (legacy name)

    L1 (chat) uses ``mode="chat"``; the engine instantiates
    :class:`ChatPipelineStrategy` and fires status / text_delta / text /
    error / done, plus a single ``sources`` event on RAG turns (the L1
    [K#] citation sources). L2 (agent) uses ``mode="agent"`` and gets the
    tool / usage events on top.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.agent_runtime.harness_events import HarnessEvent
from app.core.rate_limit import RATE_EXPENSIVE, limiter
from app.core.security import get_current_user
from app.core.user_identity import resolve_user_pk
from app.db.database import get_db
from app.models.chat import Conversation
from app.models.conversation_turn import ConversationTurn
from app.models.user import User
from app.schemas.chat import (
    AttachmentDraftCreateRequest,
    AttachmentDraftResponse,
    ChatTurnRequest,
    ChatTurnResponse,
    PendingSubmissionCommandRequest,
    PendingSubmissionItem,
    PendingSubmissionUpdateRequest,
)
from app.schemas.agent_interaction import (
    AgentInteractionView,
    ResolveInteractionRequest,
    ResolveInteractionResponse,
)
from app.schemas.tool_call_audit import AgentToolCallAuditView

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])


@router.get(
    "/chat/{session_id}/turns/{turn_id}/tool-calls/{call_id}",
    response_model=AgentToolCallAuditView,
)
async def get_turn_tool_call_audit(
    session_id: str,
    turn_id: str,
    call_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Read the deep audit layer for the same durable live/replay call id."""

    from app.services.chat.tool_call_audit_service import (
        ToolCallAuditNotFoundError,
        get_tool_call_audit,
    )

    user_pk = resolve_user_pk(db, current_user.username)
    try:
        return get_tool_call_audit(
            db,
            user_id=user_pk,
            conversation_id=session_id,
            turn_id=turn_id,
            call_id=call_id,
        )
    except ToolCallAuditNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _attachment_draft_view(draft, projection, *, removed: bool = False):
    status = "removed" if removed else projection.status
    if status == "retrying":
        status = "processing"
    return AttachmentDraftResponse(
        draft_id=draft.id,
        file_asset_id=draft.file_asset_id,
        conversation_id=draft.conversation_id,
        filename=projection.title,
        status=status,
        error_message=projection.error_message,
    )


@router.post(
    "/chat/{session_id}/attachment-drafts",
    response_model=AttachmentDraftResponse,
)
async def create_chat_attachment_draft(
    session_id: str,
    body: AttachmentDraftCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.services.chat.attachment_ingress_service import (
        AttachmentIngressError,
        create_attachment_draft,
    )

    user_pk = resolve_user_pk(db, current_user.username)
    try:
        row = create_attachment_draft(
            db,
            user_pk=user_pk,
            conversation_id=session_id,
            file_asset_id=body.file_asset_id,
            draft_id=body.draft_id,
        )
        db.commit()
    except AttachmentIngressError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    from app.models.knowledge import KnowledgeDocument
    from app.task_queue.dispatch import dispatch_document_ingestion

    projection = db.get(KnowledgeDocument, row.source_document_id)
    if projection is None:
        raise HTTPException(status_code=500, detail="Attachment projection missing")
    try:
        task = dispatch_document_ingestion(projection.id)
        projection.task_id = task.id
    except Exception:  # noqa: BLE001
        logger.exception("attachment ingestion dispatch failed: %s", projection.id)
        projection.status = "failed"
        projection.error_message = "后台处理队列暂时不可用，请稍后重试。"
    db.commit()
    db.refresh(projection)
    return _attachment_draft_view(row, projection)


@router.get(
    "/chat/{session_id}/attachment-drafts/{draft_id}",
    response_model=AttachmentDraftResponse,
)
async def get_chat_attachment_draft(
    session_id: str,
    draft_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.services.chat.attachment_ingress_service import (
        AttachmentIngressError,
        get_attachment_draft,
    )

    user_pk = resolve_user_pk(db, current_user.username)
    try:
        draft, projection = get_attachment_draft(
            db,
            user_pk=user_pk,
            conversation_id=session_id,
            draft_id=draft_id,
        )
    except AttachmentIngressError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _attachment_draft_view(
        draft,
        projection,
        removed=draft.removed_at is not None,
    )


@router.delete(
    "/chat/{session_id}/attachment-drafts/{draft_id}",
    response_model=AttachmentDraftResponse,
)
async def remove_chat_attachment_draft(
    session_id: str,
    draft_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.services.chat.attachment_ingress_service import (
        AttachmentIngressError,
        remove_attachment_draft,
    )

    user_pk = resolve_user_pk(db, current_user.username)
    try:
        row = remove_attachment_draft(
            db,
            user_pk=user_pk,
            conversation_id=session_id,
            draft_id=draft_id,
        )
        db.commit()
    except AttachmentIngressError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    from app.models.knowledge import KnowledgeDocument

    projection = db.get(KnowledgeDocument, row.source_document_id)
    if projection is None:
        raise HTTPException(status_code=500, detail="Attachment projection missing")
    return _attachment_draft_view(row, projection, removed=True)


@router.get(
    "/chat/{session_id}/turns/{turn_id}/interaction",
    response_model=AgentInteractionView | None,
)
async def get_turn_interaction(
    session_id: str,
    turn_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.services.chat.interaction_service import get_pending_interaction

    user_pk = resolve_user_pk(db, current_user.username)
    turn = db.get(ConversationTurn, turn_id)
    if turn is None or turn.conversation_id != session_id or turn.user_id != user_pk:
        raise HTTPException(status_code=404, detail="Turn not found or access denied")
    row = get_pending_interaction(db, turn_id=turn_id, user_id=user_pk)
    if row is None:
        return None
    view = AgentInteractionView.model_validate(row)
    if row.kind == "client_readiness":
        from app.services.chat.client_action_service import (
            sanitized_interaction_request,
        )

        view = view.model_copy(update={"request": sanitized_interaction_request(row)})
    return view


@router.post(
    "/chat/{session_id}/turns/{turn_id}/interactions/{interaction_id}/resolve",
    response_model=ResolveInteractionResponse,
)
async def resolve_turn_interaction(
    session_id: str,
    turn_id: str,
    interaction_id: str,
    body: ResolveInteractionRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.services.chat.interaction_service import (
        InteractionConflictError,
        InteractionNotFoundError,
        InteractionOwnershipError,
        resolve_interaction,
    )
    from app.services.chat.turn_event_buffer import turn_event_buffer
    from app.services.chat.turn_executor import (
        cancel_pending_turn,
        fail_pending_turn,
        resume_waiting_turn,
        schedule_turn,
    )

    user_pk = resolve_user_pk(db, current_user.username)
    turn = db.get(ConversationTurn, turn_id)
    if turn is None or turn.conversation_id != session_id or turn.user_id != user_pk:
        raise HTTPException(status_code=404, detail="Turn not found or access denied")
    from app.models.agent_interaction import AgentInteraction

    target_interaction = db.get(AgentInteraction, interaction_id)
    if (
        target_interaction is not None
        and target_interaction.kind == "client_readiness"
        and isinstance(target_interaction.request_json, dict)
        and target_interaction.request_json.get("protocol") == "mock_handoff.v1"
    ):
        raise HTTPException(
            status_code=409,
            detail="Client Action must be resolved by its bound client endpoint",
        )
    try:
        interaction = resolve_interaction(
            db,
            interaction_id=interaction_id,
            user_id=user_pk,
            expected_version=body.expected_version,
            status=body.status,
            resolution=body.resolution,
        )
    except (InteractionNotFoundError, InteractionOwnershipError) as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InteractionConflictError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    if interaction.turn_id != turn_id:
        db.rollback()
        raise HTTPException(
            status_code=404, detail="Interaction does not belong to Turn"
        )

    if body.status == "cancelled":
        generation = int(turn.dispatch_generation or 1)
        if not cancel_pending_turn(db, turn_id, user_pk):
            db.rollback()
            raise HTTPException(status_code=409, detail="Turn is not waiting")
        return ResolveInteractionResponse(
            interaction=AgentInteractionView.model_validate(interaction),
            turn_status="cancelled",
            dispatch_generation=generation,
        )

    if body.status == "rejected" and interaction.kind == "clarification":
        generation = int(turn.dispatch_generation or 1)
        if not cancel_pending_turn(db, turn_id, user_pk):
            db.rollback()
            raise HTTPException(status_code=409, detail="Turn is not waiting")
        return ResolveInteractionResponse(
            interaction=AgentInteractionView.model_validate(interaction),
            turn_status="cancelled",
            dispatch_generation=generation,
        )

    generation = resume_waiting_turn(
        db,
        turn_id,
        user_pk,
        expected_reason="interaction",
    )
    if generation is None:
        db.rollback()
        raise HTTPException(status_code=409, detail="Turn is not waiting")
    try:
        await turn_event_buffer.reset(turn_id)
        schedule_turn(turn_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Could not resume conversation turn %s", turn_id)
        fail_pending_turn(db, turn_id, user_pk, "后台任务队列暂时不可用")
        raise HTTPException(status_code=503, detail="无法恢复本轮执行") from exc
    return ResolveInteractionResponse(
        interaction=AgentInteractionView.model_validate(interaction),
        turn_status="pending",
        dispatch_generation=generation,
    )


def _turn_terminal_state(turn_id: str) -> tuple[str | None, str | None]:
    from app.db.database import SessionLocal

    session = SessionLocal()
    try:
        row = session.get(ConversationTurn, turn_id)
        return (row.status, row.error) if row else (None, None)
    finally:
        session.close()


def _recovery_events(status: str, error: str | None) -> list[str]:
    """Rebuild terminal events when the Redis stream is unavailable or expired."""
    from app.conversation.events import HarnessEvent

    events: list[str] = []
    if status == "failed":
        events.append(HarnessEvent.error(error or "本轮执行失败").to_json())
    elif status == "cancelled":
        events.append(HarnessEvent.error(error or "本轮已取消").to_json())
    events.append(HarnessEvent.done(step=0, elapsed_ms=0, outcome=status).to_json())
    return events


def _interaction_event(turn_id: str) -> str | None:
    from app.conversation.events import HarnessEvent
    from app.db.database import SessionLocal
    from app.models.agent_interaction import AgentInteraction

    session = SessionLocal()
    try:
        row = (
            session.query(AgentInteraction)
            .filter(
                AgentInteraction.turn_id == turn_id,
                AgentInteraction.status == "pending",
            )
            .one_or_none()
        )
        if row is None:
            return None
        request = row.request_json
        if row.kind == "client_readiness":
            from app.services.chat.client_action_service import (
                sanitized_interaction_request,
            )

            request = sanitized_interaction_request(row)
        return HarnessEvent.interaction(
            {
                "id": row.id,
                "turn_id": row.turn_id,
                "tool_call_id": row.tool_call_id,
                "kind": row.kind,
                "status": row.status,
                "request": request,
                "version": row.version,
            },
            step=0,
            elapsed_ms=0,
        ).to_json()
    finally:
        session.close()


@router.post(
    "/chat/{session_id}/turns",
    status_code=202,
    response_model=ChatTurnResponse,
)
@limiter.limit(RATE_EXPENSIVE)
async def create_chat_turn(
    request: Request,
    response: Response,
    session_id: str,
    body: ChatTurnRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_pk = resolve_user_pk(db, current_user.username)
    row = db.get(Conversation, session_id)
    if row is None or row.user_id != user_pk:
        raise HTTPException(
            status_code=404, detail="Session not found or access denied"
        )
    from app.services.chat.turn_event_buffer import turn_event_buffer
    from app.services.chat.turn_executor import (
        SubmissionConflictError,
        admit_submission,
        fail_pending_turn,
        schedule_turn,
    )

    try:
        result = admit_submission(
            db,
            row,
            submission_id=body.submission_id,
            version=int(body.version),
            user_id=user_pk,
            requested_mode=body.mode,
            requested_execution_mode=body.execution_mode,
            message=body.message,
            question_indexes=[int(index) for index in body.question_indexes],
            attachment_draft_ids=[item.draft_id for item in body.attachments],
            object_references=[
                item.model_dump(mode="json") for item in body.object_references
            ],
            source_client_id=body.source_client_id,
        )
    except SubmissionConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail={"message": str(exc), "submission_id": body.submission_id},
        ) from exc
    if not result.should_dispatch:
        payload = {
            "submission_id": result.submission_id,
            "version": result.version,
            "status": result.status,
            "turn_id": result.turn_id,
            "queue_position": result.queue_position,
        }
        if result.error:
            payload["error"] = result.error
        return payload

    try:
        await turn_event_buffer.ping()
    except Exception as exc:  # noqa: BLE001
        fail_pending_turn(
            db,
            result.dispatch_turn_id or "",
            user_pk,
            "Turn event buffer unavailable",
        )
        raise HTTPException(
            status_code=503, detail="Turn event buffer is unavailable"
        ) from exc
    try:
        schedule_turn(result.dispatch_turn_id or "")
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "Could not dispatch conversation turn %s: %s",
            result.dispatch_turn_id,
            exc,
        )
        fail_pending_turn(
            db,
            result.dispatch_turn_id or "",
            user_pk,
            "后台任务队列暂时不可用",
        )
        raise HTTPException(
            status_code=503,
            detail="后台任务队列暂时不可用，请稍后重试",
        ) from exc
    payload = {
        "submission_id": result.submission_id,
        "version": result.version,
        "status": result.status,
        "turn_id": result.turn_id,
        "queue_position": result.queue_position,
    }
    if result.error:
        payload["error"] = result.error
    return payload


@router.get(
    "/chat/{session_id}/submissions",
    response_model=list[PendingSubmissionItem],
)
async def list_pending_submissions(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_pk = resolve_user_pk(db, current_user.username)
    conversation = db.get(Conversation, session_id)
    if conversation is None or conversation.user_id != user_pk:
        raise HTTPException(
            status_code=404, detail="Session not found or access denied"
        )
    from app.models.pending_submission import PendingSubmission

    rows = (
        db.query(PendingSubmission)
        .filter(
            PendingSubmission.conversation_id == session_id,
            PendingSubmission.user_id == user_pk,
            PendingSubmission.status.in_(("pending", "failed")),
        )
        .order_by(PendingSubmission.position, PendingSubmission.id)
        .all()
    )
    return [
        PendingSubmissionItem(
            submission_id=row.id,
            version=row.version,
            queue_position=row.position,
            message=row.message,
            mode=row.mode,
            execution_mode=row.execution_mode,
            question_indexes=list(row.question_indexes_json or []),
            attachments=[
                {"draft_id": item["draft_id"]}
                for item in (row.attachments_json or [])
                if isinstance(item, dict) and item.get("draft_id")
            ],
            object_references=list(row.object_references_json or []),
            source_client_id=row.source_client_id,
            status="failed" if row.status == "failed" else "queued",
            error=row.error,
        )
        for row in rows
    ]


def _owned_conversation_or_404(db: Session, session_id: str, user_pk: int):
    conversation = db.get(Conversation, session_id)
    if conversation is None or conversation.user_id != user_pk:
        raise HTTPException(
            status_code=404, detail="Session not found or access denied"
        )
    return conversation


def _submission_view(row) -> PendingSubmissionItem:
    return PendingSubmissionItem(
        submission_id=row.id,
        version=row.version,
        status="failed" if row.status == "failed" else "queued",
        queue_position=row.position,
        message=row.message,
        mode=row.mode,
        execution_mode=row.execution_mode,
        question_indexes=list(row.question_indexes_json or []),
        attachments=[
            {"draft_id": item["draft_id"]}
            for item in (row.attachments_json or [])
            if isinstance(item, dict) and item.get("draft_id")
        ],
        object_references=list(row.object_references_json or []),
        source_client_id=row.source_client_id,
        error=row.error,
    )


@router.patch(
    "/chat/{session_id}/submissions/{submission_id}",
    response_model=PendingSubmissionItem,
)
async def edit_pending_submission(
    session_id: str,
    submission_id: str,
    body: PendingSubmissionUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.services.chat.turn_executor import (
        SubmissionConflictError,
        update_pending_submission,
    )

    user_pk = resolve_user_pk(db, current_user.username)
    _owned_conversation_or_404(db, session_id, user_pk)
    try:
        row = update_pending_submission(
            db,
            session_id,
            user_pk,
            submission_id,
            expected_version=int(body.expected_version),
            message=body.message,
            mode=body.mode,
            execution_mode=body.execution_mode,
            question_indexes=[int(index) for index in body.question_indexes],
            attachment_draft_ids=[item.draft_id for item in body.attachments],
            object_references=[
                item.model_dump(mode="json") for item in body.object_references
            ],
        )
    except SubmissionConflictError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _submission_view(row)


@router.delete(
    "/chat/{session_id}/submissions/{submission_id}",
    status_code=204,
)
async def withdraw_pending_submission_endpoint(
    session_id: str,
    submission_id: str,
    expected_version: int = Query(ge=1),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.services.chat.turn_executor import (
        SubmissionConflictError,
        schedule_turn,
        withdraw_pending_submission,
    )

    user_pk = resolve_user_pk(db, current_user.username)
    _owned_conversation_or_404(db, session_id, user_pk)
    try:
        next_turn_id = withdraw_pending_submission(
            db,
            session_id,
            user_pk,
            submission_id,
            expected_version=expected_version,
        )
    except SubmissionConflictError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if next_turn_id:
        try:
            schedule_turn(next_turn_id)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Could not dispatch Turn %s after withdraw", next_turn_id)
            from app.services.chat.turn_executor import fail_pending_turn

            fail_pending_turn(db, next_turn_id, user_pk, "后台任务队列暂时不可用")
            raise HTTPException(
                status_code=503, detail="后台任务队列暂时不可用"
            ) from exc
    return Response(status_code=204)


async def _dispatch_admission_result(db: Session, user_pk: int, result):
    from app.services.chat.turn_event_buffer import turn_event_buffer
    from app.services.chat.turn_executor import fail_pending_turn, schedule_turn

    if not result.should_dispatch:
        return
    try:
        await turn_event_buffer.ping()
        schedule_turn(result.dispatch_turn_id or "")
    except Exception as exc:  # noqa: BLE001
        fail_pending_turn(
            db,
            result.dispatch_turn_id or "",
            user_pk,
            "后台任务队列暂时不可用",
        )
        raise HTTPException(status_code=503, detail="后台任务队列暂时不可用") from exc


@router.post(
    "/chat/{session_id}/submissions/{submission_id}/retry",
    response_model=ChatTurnResponse,
)
async def retry_pending_submission_endpoint(
    session_id: str,
    submission_id: str,
    body: PendingSubmissionCommandRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.services.chat.turn_executor import (
        SubmissionConflictError,
        retry_pending_submission,
    )

    user_pk = resolve_user_pk(db, current_user.username)
    _owned_conversation_or_404(db, session_id, user_pk)
    try:
        result = retry_pending_submission(
            db,
            session_id,
            user_pk,
            submission_id,
            expected_version=int(body.expected_version),
        )
    except SubmissionConflictError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await _dispatch_admission_result(db, user_pk, result)
    payload = {
        "submission_id": result.submission_id,
        "version": result.version,
        "status": result.status,
        "turn_id": result.turn_id,
        "queue_position": result.queue_position,
    }
    if result.error:
        payload["error"] = result.error
    return payload


class _InterruptRequest(PendingSubmissionCommandRequest):
    submission_id: str


@router.post(
    "/chat/{session_id}/turns/{turn_id}/interrupt",
    status_code=202,
)
async def interrupt_turn_for_submission(
    session_id: str,
    turn_id: str,
    body: _InterruptRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.services.chat.turn_executor import (
        SubmissionConflictError,
        cancel_pending_turn,
        request_turn_interrupt,
    )
    from app.services.chat.turn_event_buffer import turn_event_buffer

    user_pk = resolve_user_pk(db, current_user.username)
    _owned_conversation_or_404(db, session_id, user_pk)
    try:
        status, generation = request_turn_interrupt(
            db,
            session_id,
            turn_id,
            user_pk,
            body.submission_id,
            expected_version=int(body.expected_version),
        )
    except SubmissionConflictError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    await turn_event_buffer.request_cancel(turn_id)
    # Pending/waiting has no active worker to consume the signal; terminalize
    # synchronously. Running returns cancelling and its worker owns durability.
    if status in {"pending", "waiting"}:
        cancel_pending_turn(db, turn_id, user_pk)
        status = "cancelled"
    return {
        "turn_id": turn_id,
        "status": status if status == "cancelled" else "cancelling",
        "submission_id": body.submission_id,
        "dispatch_generation": generation,
    }


@router.get("/chat/{session_id}/turns/{turn_id}/events")
async def stream_chat_turn_events(
    session_id: str,
    turn_id: str,
    after: str | None = Query(default=None),
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_pk = resolve_user_pk(db, current_user.username)
    turn = db.get(ConversationTurn, turn_id)
    if turn is None or turn.conversation_id != session_id or turn.user_id != user_pk:
        raise HTTPException(status_code=404, detail="Turn not found or access denied")
    from app.services.chat.turn_event_buffer import turn_event_buffer

    async def event_generator():
        import asyncio

        cursor = after or last_event_id or "0-0"
        while True:
            events = await turn_event_buffer.read(turn_id, cursor)
            if not events:
                status, error = await asyncio.to_thread(_turn_terminal_state, turn_id)
                if status == "waiting":
                    interaction_event = await asyncio.to_thread(
                        _interaction_event, turn_id
                    )
                    if interaction_event:
                        yield f"data: {interaction_event}\n\n"
                    yield (
                        "data: "
                        + HarnessEvent.done(
                            step=0,
                            elapsed_ms=0,
                            outcome="waiting",
                        ).to_json()
                        + "\n\n"
                    )
                    return
                if status in {"completed", "blocked", "failed", "cancelled"}:
                    for event_json in _recovery_events(status, error):
                        yield f"data: {event_json}\n\n"
                    return
                yield ": keepalive\n\n"
                continue
            for event_id, event_json in events:
                cursor = event_id
                yield f"id: {event_id}\ndata: {event_json}\n\n"
                if turn_event_buffer.is_done(event_json):
                    return

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/chat/{session_id}/turns/{turn_id}/cancel", status_code=202)
async def cancel_chat_turn(
    session_id: str,
    turn_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_pk = resolve_user_pk(db, current_user.username)
    turn = db.get(ConversationTurn, turn_id)
    if turn is None or turn.conversation_id != session_id or turn.user_id != user_pk:
        raise HTTPException(status_code=404, detail="Turn not found or access denied")
    if turn.status not in {"pending", "running", "waiting"}:
        return {"turn_id": turn_id, "status": turn.status, "cancelled": False}
    from app.services.chat.turn_event_buffer import turn_event_buffer
    from app.services.chat.turn_executor import cancel_pending_turn

    await turn_event_buffer.request_cancel(turn_id)
    cancelled_before_start = cancel_pending_turn(db, turn_id, user_pk)
    return {
        "turn_id": turn_id,
        "status": "cancelled" if cancelled_before_start else "cancelling",
        "cancelled": True,
    }
