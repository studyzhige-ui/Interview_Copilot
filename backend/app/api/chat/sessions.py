"""Chat-session CRUD and transcript endpoints.

Hierarchy (post-0018): an interview_record has N conversations; each
session is a self-contained chat thread. No sub-conversation level.
"""

from app.api.command_errors import command_errors
from app.conversation import session_commands


import logging
from typing import List, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.core.user_identity import resolve_user_pk
from app.db.database import get_db
from app.models.chat import Conversation
from app.models.user import User
from app.conversation.runtime_profile import runtime_profile_for_type
from app.schemas.chat import (
    SessionCreateRequest,
    SessionCreateResponse,
    SessionExecutionModeResponse,
    SessionExecutionModeUpdateRequest,
    SessionListItem,
    SessionRenameRequest,
)
from app.schemas.conversation_lifecycle import (
    ConversationDeleteRequest,
    ConversationDeleteResult,
    ConversationDeletionImpact,
)
from app.conversation.application.chat_history_service import transcript_service

logger = logging.getLogger(__name__)


def _session_list_label(row: Conversation) -> str:
    """One-line label for the session-list UI, derived from dedicated columns.

    Prefers the compaction ``summary``; otherwise a type-based label.
    """
    summary = (row.summary or "").strip()
    if summary:
        return summary[:150]
    conv_type = row.type or "general"
    if conv_type == "mock_interview":
        return "模拟面试"
    if conv_type == "debrief":
        return "面试复盘"
    return "通用对话"


router = APIRouter(tags=["chat"])


@router.get("/chat/sessions/{session_id}/context")
def get_context_status(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Owner-scoped diagnostics, excluding the actual private context payload."""
    from app.conversation.context_store import load
    from app.conversation.context_window import kind, UPSTREAM_REVISION

    row = db.get(Conversation, session_id)
    if row is None or row.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Conversation not found")
    checkpoint = load(session_id)
    active = load(session_id, scope=row.active_turn_id) if row.active_turn_id else None
    chosen = active or checkpoint or {}
    return {
        "revision": UPSTREAM_REVISION,
        "version": chosen.get("version", 0),
        "window_id": chosen.get("window_id"),
        "through_seq": chosen.get("through_seq", 0),
        "active_turn": bool(row.active_turn_id),
        "item_types": [kind(m) for m in chosen.get("state", {}).get("messages", [])],
        "compaction": chosen.get("state", {}).get("compaction", {}),
    }


@router.post("/chat/sessions/{session_id}/context/compact")
async def compact_context(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Manual compaction uses the same model, prompt and checkpoint transaction."""
    import asyncio
    from app.conversation.context_manager import prepare
    from app.core.context_budget import ContextCapacityError
    from app.core.llm_client_factory import build_provider_client_for_role
    from app.conversation.application.context_assembly_pipeline import context_pipeline
    from app.conversation.application.context_assembly_pipeline import prompt_renderer
    from app.prompts.chat import DIRECT_SYSTEM_PROMPT
    from app.prompts.agent import agent_system_prompt_for_runtime

    row = db.get(Conversation, session_id)
    if row is None or row.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if row.active_turn_id:
        raise HTTPException(
            status_code=409, detail="当前任务仍在执行，请结束后再手动压缩。"
        )
    system = (
        agent_system_prompt_for_runtime(runtime_profile_for_type(row.type).name)
        if row.mode == "agent"
        else DIRECT_SYSTEM_PROMPT
    )
    client, profile = await asyncio.to_thread(
        build_provider_client_for_role, "primary", user_id=current_user.username
    )
    assembled = await context_pipeline.assemble_answer_context(
        session_id,
        "",
        user_id=current_user.username,
        model_context_window=profile.context_window,
        model_output_tokens=profile.max_output_tokens,
    )
    try:
        await prepare(
            assembled,
            renderer=prompt_renderer,
            system_prompt=system,
            client=client,
            profile=profile,
            force=True,
        )
    except ContextCapacityError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "version": assembled.checkpoint_version,
        "compaction": assembled.context_report.get("compaction", {}),
    }


@router.post("/chat/sessions", response_model=SessionCreateResponse)
def create_chat_session(
    request: SessionCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    with command_errors():
        return session_commands.create_chat_session(request, current_user, db)


@router.get("/chat/sessions", response_model=List[SessionListItem])
def list_conversations(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    type: Literal["general", "debrief", "mock_interview", "persistent_task"]
    | None = Query(None),
    subject_id: str | None = Query(
        None, description="Filter: tie to a specific interview record"
    ),
):
    q = db.query(Conversation).filter(
        Conversation.user_id == resolve_user_pk(db, current_user.username)
    )
    if type:
        q = q.filter(Conversation.type == type)
    if subject_id:
        q = q.filter(Conversation.subject_id == subject_id)
    rows = q.order_by(Conversation.updated_at.desc()).offset(offset).limit(limit).all()
    return [
        SessionListItem(
            session_id=row.id,
            title=row.title or "新的面试对话",
            type=row.type or "general",
            mode=runtime_profile_for_type(row.type).resolve_mode(row.mode, None),
            execution_mode=row.execution_mode or "standard",
            execution_mode_version=int(row.execution_mode_version or 0),
            state_summary=_session_list_label(row),
            turn_count=row.turn_count or 0,
            updated_at=row.updated_at.isoformat() if row.updated_at else "",
        )
        for row in rows
    ]


def _owned_conversation(db: Session, *, session_id: str, user_pk: int) -> Conversation:
    with command_errors():
        return session_commands._owned_conversation(
            db, session_id=session_id, user_pk=user_pk
        )


@router.get(
    "/chat/sessions/{session_id}/execution-mode",
    response_model=SessionExecutionModeResponse,
)
def get_session_execution_mode(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = _owned_conversation(
        db,
        session_id=session_id,
        user_pk=resolve_user_pk(db, current_user.username),
    )
    return SessionExecutionModeResponse(
        session_id=row.id,
        execution_mode=row.execution_mode or "standard",
        version=int(row.execution_mode_version or 0),
    )


@router.patch(
    "/chat/sessions/{session_id}/execution-mode",
    response_model=SessionExecutionModeResponse,
)
def update_session_execution_mode(
    session_id: str,
    payload: SessionExecutionModeUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    with command_errors():
        return session_commands.update_session_execution_mode(
            session_id, payload, current_user, db
        )


@router.patch("/chat/sessions/{session_id}/title")
def update_session_title(
    session_id: str,
    payload: SessionRenameRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    with command_errors():
        return session_commands.update_session_title(
            session_id, payload, current_user, db
        )


@router.get(
    "/chat/sessions/{session_id}/deletion-impact",
    response_model=ConversationDeletionImpact,
)
def get_chat_session_deletion_impact(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.conversation.application.conversation_deletion_service import (
        ConversationDeletionConflictError,
    )
    from app.conversation.application.conversation_deletion_service import (
        ConversationDeletionNotFoundError,
    )
    from app.conversation.application.conversation_deletion_service import (
        preview_conversation_deletion,
    )

    try:
        return preview_conversation_deletion(
            db,
            user_pk=resolve_user_pk(db, current_user.username),
            conversation_id=session_id,
        )
    except ConversationDeletionNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail="Session not found or access denied"
        ) from exc
    except ConversationDeletionConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete(
    "/chat/sessions/{session_id}",
    response_model=ConversationDeleteResult,
)
def delete_chat_session(
    session_id: str,
    payload: ConversationDeleteRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.conversation.application.conversation_deletion_service import (
        ConversationDeletionConflictError,
    )
    from app.conversation.application.conversation_deletion_service import (
        ConversationDeletionNotFoundError,
    )
    from app.conversation.application.conversation_deletion_service import (
        delete_conversation,
    )

    try:
        deletion = delete_conversation(
            db,
            user_pk=resolve_user_pk(db, current_user.username),
            conversation_id=session_id,
            confirmation_token=payload.confirmation_token,
            confirm_conversation_id=payload.confirm_conversation_id,
        )
        db.commit()
        from app.task_queue.dispatch import revoke_task

        for task_id in deletion.ingestion_task_ids:
            try:
                revoke_task(task_id)
            except Exception:  # noqa: BLE001 - cleanup is already durable
                logger.warning(
                    "Could not revoke deleted attachment ingestion task %s",
                    task_id,
                    exc_info=True,
                )
        if deletion.cancelled_turn_id:
            try:
                from app.core.async_runtime import run_async
                from app.conversation.application.turn_event_buffer import (
                    turn_event_buffer,
                )

                run_async(turn_event_buffer.request_cancel(deletion.cancelled_turn_id))
            except Exception:  # noqa: BLE001 - durable fence is authoritative
                logger.warning(
                    "Could not signal deleted Conversation Turn %s",
                    deletion.cancelled_turn_id,
                    exc_info=True,
                )
        return deletion.result
    except ConversationDeletionNotFoundError as exc:
        db.rollback()
        raise HTTPException(
            status_code=404, detail="Session not found or access denied"
        ) from exc
    except ConversationDeletionConflictError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.exception(
            "delete_chat_session failed (id=%s user=%s): %s",
            session_id,
            current_user.username,
            exc,
        )
        raise HTTPException(
            status_code=500,
            detail="删除对话失败",
        ) from exc


@router.get("/chat/transcript")
def get_full_transcript(
    session_id: str = Query(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    session_row = db.query(Conversation).filter(Conversation.id == session_id).first()
    if not session_row or session_row.user_id != resolve_user_pk(
        db, current_user.username
    ):
        raise HTTPException(
            status_code=404, detail="Session not found or access denied"
        )

    meta = transcript_service.get_session_meta(session_id, db=db)
    messages = transcript_service.get_full_transcript(session_id, db=db)
    return {
        "status": "success",
        "session_id": session_id,
        "type": meta["type"] if meta else "general",
        "turn_count": meta["turn_count"] if meta else 0,
        "compaction_cursor": meta["compaction_cursor"] if meta else 0,
        "active_turn_id": session_row.active_turn_id,
        "messages": messages,
        "total_messages": len(messages),
    }
