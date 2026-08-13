"""Chat-session CRUD and transcript endpoints.

Hierarchy (post-0018): an interview_record has N conversations; each
session is a self-contained chat thread. No sub-conversation level.
"""

import logging
from typing import List, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.core.user_identity import resolve_user_pk
from app.db.database import get_db
from app.models.chat import Conversation, generate_uuid
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
from app.services.chat.chat_history_service import transcript_service

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


@router.post("/chat/sessions", response_model=SessionCreateResponse)
def create_chat_session(
    request: SessionCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    req = request
    # mock_interview conversations are created by the mock-interview start
    # endpoint (it owns the atomic record + conversation + runtime creation),
    # never here. This endpoint only opens general / debrief chats.
    conv_type = req.type

    subject_type: str | None = None
    subject_id: str | None = None
    if conv_type == "debrief":
        if not req.subject_id:
            raise HTTPException(status_code=400, detail="debrief 对话必须绑定面试记录")
        from app.models.interview_record import InterviewRecord

        record = (
            db.query(InterviewRecord)
            .filter(
                InterviewRecord.id == req.subject_id,
                InterviewRecord.user_id == resolve_user_pk(db, current_user.username),
            )
            .first()
        )
        if record is None:
            raise HTTPException(status_code=404, detail="Interview record not found")
        subject_type = "interview_record"
        subject_id = req.subject_id

    default_titles = {"general": "通用对话", "debrief": "面试复盘"}
    title = req.title or default_titles.get(conv_type, "新的面试对话")

    try:
        new_session = Conversation(
            id=generate_uuid(),
            user_id=resolve_user_pk(db, current_user.username),
            title=title,
            type=conv_type,
            mode=runtime_profile_for_type(conv_type).default_mode,
            execution_mode=(
                getattr(current_user, "default_execution_mode", None) or "standard"
            ),
            subject_type=subject_type,
            subject_id=subject_id,
        )
        db.add(new_session)
        db.commit()
        db.refresh(new_session)
        return SessionCreateResponse(
            session_id=new_session.id,
            title=new_session.title,
            type=new_session.type,
            execution_mode=new_session.execution_mode,
            execution_mode_version=new_session.execution_mode_version,
        )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.exception(
            "create_chat_session failed (user=%s, type=%s, subject_id=%s): %s",
            current_user.username,
            conv_type,
            req.subject_id,
            exc,
        )
        raise HTTPException(
            status_code=500,
            detail="创建对话失败",
        ) from exc


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
    row = (
        db.query(Conversation)
        .filter(Conversation.id == session_id, Conversation.user_id == user_pk)
        .one_or_none()
    )
    if row is None:
        raise HTTPException(
            status_code=404, detail="Session not found or access denied"
        )
    return row


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
    """CAS-update only the Conversation's setting for future admissions.

    PendingSubmission and ConversationTurn rows already own admitted snapshots;
    this endpoint intentionally never touches them.
    """
    user_pk = resolve_user_pk(db, current_user.username)
    changed = (
        db.query(Conversation)
        .filter(
            Conversation.id == session_id,
            Conversation.user_id == user_pk,
            Conversation.execution_mode_version == payload.expected_version,
        )
        .update(
            {
                Conversation.execution_mode: payload.execution_mode,
                Conversation.execution_mode_version: payload.expected_version + 1,
            },
            synchronize_session=False,
        )
    )
    if changed != 1:
        db.rollback()
        # Preserve owner isolation: a missing/foreign id is always a 404. A
        # same-owner row with a newer token is a conflict; clients reread the
        # authoritative projection instead of trusting their stale copy.
        _owned_conversation(db, session_id=session_id, user_pk=user_pk)
        raise HTTPException(status_code=409, detail="execution mode version conflict")
    db.commit()
    row = _owned_conversation(db, session_id=session_id, user_pk=user_pk)
    return SessionExecutionModeResponse(
        session_id=row.id,
        execution_mode=row.execution_mode,
        version=int(row.execution_mode_version),
    )


@router.patch("/chat/sessions/{session_id}/title")
def update_session_title(
    session_id: str,
    payload: SessionRenameRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    new_title = payload.title.strip()
    if not new_title:
        raise HTTPException(status_code=400, detail="title 不能为空")
    row = db.query(Conversation).filter(Conversation.id == session_id).first()
    if not row or row.user_id != resolve_user_pk(db, current_user.username):
        raise HTTPException(
            status_code=404, detail="Session not found or access denied"
        )
    row.title = new_title
    db.commit()
    return {"status": "success", "session_id": session_id, "new_title": new_title}


@router.get(
    "/chat/sessions/{session_id}/deletion-impact",
    response_model=ConversationDeletionImpact,
)
def get_chat_session_deletion_impact(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.services.chat.conversation_deletion_service import (
        ConversationDeletionConflictError,
        ConversationDeletionNotFoundError,
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
    from app.services.chat.conversation_deletion_service import (
        ConversationDeletionConflictError,
        ConversationDeletionNotFoundError,
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
                from app.services.chat.turn_event_buffer import turn_event_buffer

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
