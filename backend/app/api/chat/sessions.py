"""Chat-session CRUD + history + transcript + memory-recall toggle.

Hierarchy (post-0018): an interview_record has N conversations; each
session is a self-contained chat thread. No sub-conversation level.
"""

import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.core.user_identity import resolve_user_pk
from app.db.database import get_db
from app.models.chat import ConversationMessage, Conversation, generate_uuid
from app.models.user import User
from app.schemas.chat import (
    MessageItem,
    SessionCreateRequest,
    SessionCreateResponse,
    SessionListItem,
    SessionRenameRequest,
)
from app.services.chat.chat_history_service import transcript_service
from app.services.chat.mock_interview_state import (
    default_mock_state,
    dump_mock_state,
    parse_mock_state,
)

logger = logging.getLogger(__name__)


def _session_list_label(row: Conversation) -> str:
    """One-line label for the session-list UI, derived from dedicated columns.

    Prefers the compaction ``summary``; otherwise a type-based label (mock
    sessions append the current phase, read from ``mock_interview_state``).
    """
    summary = (row.summary or "").strip()
    if summary:
        return summary[:150]
    session_type = row.session_type or "general"
    if session_type == "mock_interview":
        phase = str(parse_mock_state(row.mock_interview_state).get("current_phase") or "").strip()
        return f"模拟面试 | {phase}" if phase else "模拟面试"
    if session_type == "debrief":
        return "面试复盘"
    return "通用对话"

router = APIRouter(tags=["chat"])


@router.post("/chat/sessions", response_model=SessionCreateResponse)
def create_chat_session(
    request: SessionCreateRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    req = request or SessionCreateRequest()
    session_type = req.session_type if req.session_type in {"general", "debrief", "mock_interview"} else "general"

    if session_type == "debrief" and req.interview_id:
        from app.models.interview_record import InterviewRecord
        record = db.query(InterviewRecord).filter(
            InterviewRecord.id == req.interview_id,
            InterviewRecord.user_id == resolve_user_pk(db, current_user.username),
        ).first()
        if record is None:
            raise HTTPException(status_code=404, detail="Interview record not found")

    default_titles = {
        "general": "通用对话",
        "debrief": "面试复盘",
        "mock_interview": "模拟面试",
    }
    title = req.title or default_titles.get(session_type, "新的面试对话")

    try:
        mock_state = (
            dump_mock_state(default_mock_state(req.interview_id or ""))
            if session_type == "mock_interview"
            else None
        )
        new_session = Conversation(
            id=generate_uuid(),
            user_id=resolve_user_pk(db, current_user.username),
            title=title,
            session_type=session_type,
            interview_id=req.interview_id,
            mock_interview_state=mock_state,
        )
        db.add(new_session)
        db.commit()
        db.refresh(new_session)
        return SessionCreateResponse(
            session_id=new_session.id,
            title=new_session.title,
            session_type=new_session.session_type,
        )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.exception(
            "create_chat_session failed (user=%s, type=%s, interview_id=%s): %s",
            current_user.username, session_type, req.interview_id, exc,
        )
        raise HTTPException(
            status_code=500,
            detail=f"创建对话失败: {type(exc).__name__}: {exc}",
        ) from exc


@router.get("/chat/sessions", response_model=List[SessionListItem])
def list_conversations(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    session_type: str | None = Query(None, description="Filter: general/debrief/mock_interview"),
    interview_id: str | None = Query(None, description="Filter: tie to a specific interview record"),
):
    q = db.query(Conversation).filter(Conversation.user_id == resolve_user_pk(db, current_user.username))
    if session_type:
        q = q.filter(Conversation.session_type == session_type)
    if interview_id:
        q = q.filter(Conversation.interview_id == interview_id)
    rows = (
        q.order_by(Conversation.updated_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [
        SessionListItem(
            session_id=row.id,
            title=row.title or "新的面试对话",
            session_type=row.session_type or "general",
            state_summary=_session_list_label(row),
            turn_count=row.turn_count or 0,
            updated_at=row.updated_at.isoformat() if row.updated_at else "",
        )
        for row in rows
    ]


@router.get("/chat/history", response_model=List[MessageItem])
def get_chat_history(
    session_id: str = Query(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
):
    session_row = db.query(Conversation).filter(Conversation.id == session_id).first()
    if not session_row or session_row.user_id != resolve_user_pk(db, current_user.username):
        raise HTTPException(status_code=404, detail="Session not found or access denied")

    rows = (
        db.query(ConversationMessage)
        .filter(ConversationMessage.session_id == session_id)
        .order_by(ConversationMessage.seq.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    rows.reverse()
    return [
        MessageItem(
            seq=row.seq,
            role=row.role,
            content=row.content,
            created_at=row.created_at.isoformat() if row.created_at else "",
        )
        for row in rows
    ]


@router.patch("/chat/sessions/{session_id}/title")
def update_session_title(
    session_id: str,
    payload: SessionRenameRequest | None = None,
    title: str | None = Query(default=None, description="Legacy: title via query param"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    new_title = (payload.title if payload and payload.title else title) or ""
    new_title = new_title.strip()
    if not new_title:
        raise HTTPException(status_code=400, detail="title 不能为空")
    row = db.query(Conversation).filter(Conversation.id == session_id).first()
    if not row or row.user_id != resolve_user_pk(db, current_user.username):
        raise HTTPException(status_code=404, detail="Session not found or access denied")
    row.title = new_title
    db.commit()
    return {"status": "success", "session_id": session_id, "new_title": new_title}


@router.delete("/chat/sessions/{session_id}")
def delete_chat_session(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = db.query(Conversation).filter(Conversation.id == session_id).first()
    if not row or row.user_id != resolve_user_pk(db, current_user.username):
        raise HTTPException(status_code=404, detail="Session not found or access denied")
    try:
        db.query(ConversationMessage).filter(
            ConversationMessage.session_id == session_id
        ).delete(synchronize_session=False)
        db.delete(row)
        db.commit()
        return {"status": "success", "id": session_id}
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.exception(
            "delete_chat_session failed (id=%s user=%s): %s",
            session_id, current_user.username, exc,
        )
        raise HTTPException(
            status_code=500,
            detail=f"删除对话失败: {type(exc).__name__}: {exc}",
        ) from exc


@router.get("/chat/transcript")
def get_full_transcript(
    session_id: str = Query(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    session_row = db.query(Conversation).filter(Conversation.id == session_id).first()
    if not session_row or session_row.user_id != resolve_user_pk(db, current_user.username):
        raise HTTPException(status_code=404, detail="Session not found or access denied")

    meta = transcript_service.get_session_meta(session_id)
    messages = transcript_service.get_full_transcript(session_id)
    return {
        "status": "success",
        "session_id": session_id,
        "session_type": meta["session_type"] if meta else "general",
        "turn_count": meta["turn_count"] if meta else 0,
        "compaction_cursor": meta["compaction_cursor"] if meta else 0,
        "mock_interview_state": (
            parse_mock_state(session_row.mock_interview_state)
            if (session_row.session_type or "general") == "mock_interview"
            else {}
        ),
        "messages": messages,
        "total_messages": len(messages),
    }


# ── Memory recall toggle (per session) ──────────────────────────────────
# Resolves the per-session ``global_memory_enabled`` column → user-level
# default → False via ``recall_policy``. Frontend uses GET to render the
# switch and POST to
# flip it. The interview_fact recall path checks this on every turn.


class MemoryRecallToggleBody(BaseModel):
    enabled: bool


@router.get("/chat/sessions/{session_id}/memory-recall")
def get_session_memory_recall(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    session_row = db.query(Conversation).filter(Conversation.id == session_id).first()
    if not session_row or session_row.user_id != resolve_user_pk(db, current_user.username):
        raise HTTPException(status_code=404, detail="Session not found or access denied")
    from app.services.memory.recall_policy import is_global_memory_enabled_for_session
    effective = is_global_memory_enabled_for_session(session_id, current_user.username)
    return {"status": "success", "session_id": session_id, "enabled": effective}


@router.post("/chat/sessions/{session_id}/memory-recall")
def set_session_memory_recall(
    session_id: str,
    body: MemoryRecallToggleBody,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    session_row = db.query(Conversation).filter(Conversation.id == session_id).first()
    if not session_row or session_row.user_id != resolve_user_pk(db, current_user.username):
        raise HTTPException(status_code=404, detail="Session not found or access denied")
    from app.services.memory.recall_policy import set_session_global_memory
    set_session_global_memory(session_id, current_user.username, body.enabled)
    return {"status": "success", "session_id": session_id, "enabled": bool(body.enabled)}
