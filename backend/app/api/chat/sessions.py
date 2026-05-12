"""Chat-session CRUD + full-transcript endpoints."""

import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.database import get_db
from app.models.chat import ChatMessage, ChatSession, generate_uuid
from app.models.user import User
from app.schemas.chat import (
    MessageItem,
    SessionCreateRequest,
    SessionCreateResponse,
    SessionListItem,
)
from app.services.chat.chat_history_service import transcript_service
from app.services.chat.session_state import (
    default_session_state_for_type,
    dump_session_state,
    parse_session_state,
    summarize_session_state,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])


@router.post("/chat/sessions", response_model=SessionCreateResponse)
def create_chat_session(
    request: SessionCreateRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    req = request or SessionCreateRequest()
    session_type = req.session_type if req.session_type in {"general", "debrief", "mock_interview"} else "general"

    # Validate interview_id for debrief sessions
    if session_type == "debrief" and req.interview_id:
        from app.models.interview_record import InterviewRecord
        record = db.query(InterviewRecord).filter(
            InterviewRecord.id == req.interview_id,
            InterviewRecord.user_id == current_user.username,
        ).first()
        if record is None:
            raise HTTPException(status_code=404, detail="Interview record not found")

    default_titles = {
        "general": "通用对话",
        "debrief": "面试复盘",
        "mock_interview": "模拟面试",
    }
    title = req.title or default_titles.get(session_type, "新的面试对话")

    state = default_session_state_for_type(session_type, req.interview_id or "")
    new_session = ChatSession(
        id=generate_uuid(),
        user_id=current_user.username,
        title=title,
        session_type=session_type,
        interview_id=req.interview_id,
        session_state=dump_session_state(state),
    )
    db.add(new_session)
    db.commit()
    db.refresh(new_session)
    return SessionCreateResponse(
        session_id=new_session.id,
        title=new_session.title,
        session_type=new_session.session_type,
    )


@router.get("/chat/sessions", response_model=List[SessionListItem])
def list_chat_sessions(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
):
    rows = (
        db.query(ChatSession)
        .filter(ChatSession.user_id == current_user.username)
        .order_by(ChatSession.updated_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [
        SessionListItem(
            session_id=row.id,
            title=row.title or "新的面试对话",
            session_type=row.session_type or "general",
            state_summary=summarize_session_state(
                parse_session_state(row.session_state, row.session_type or "general")
            ),
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
    session_row = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if not session_row or session_row.user_id != current_user.username:
        raise HTTPException(status_code=404, detail="Session not found or access denied")

    rows = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.seq.desc())
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
    title: str = Query(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if not row or row.user_id != current_user.username:
        raise HTTPException(status_code=404, detail="Session not found or access denied")
    row.title = title
    db.commit()
    return {"status": "success", "session_id": session_id, "new_title": title}


@router.get("/chat/transcript")
def get_full_transcript(
    session_id: str = Query(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    session_row = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if not session_row or session_row.user_id != current_user.username:
        raise HTTPException(status_code=404, detail="Session not found or access denied")

    meta = transcript_service.get_session_meta(session_id)
    messages = transcript_service.get_full_transcript(session_id)
    return {
        "status": "success",
        "session_id": session_id,
        "session_type": meta["session_type"] if meta else "general",
        "turn_count": meta["turn_count"] if meta else 0,
        "compaction_cursor": meta["compaction_cursor"] if meta else 0,
        "session_state": (
            parse_session_state(meta["session_state"], meta.get("session_type", "general"))
            if meta
            else {}
        ),
        "messages": messages,
        "total_messages": len(messages),
    }
