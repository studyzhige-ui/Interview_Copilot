import json
import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from jose import JWTError, jwt
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import get_current_user
from app.db.database import get_db
from app.models.chat import ChatMessage, ChatSession, generate_uuid
from app.models.memory import MemoryItem
from app.models.user import User
from app.services.interview_state_service import interview_state_service
from app.services.memory_extraction_service import memory_retrieval_service
from app.services.state_utils import default_working_state_payload
from app.services.state_utils import parse_state_blob
from app.services.state_utils import summarize_working_state
from app.services.transcript_service import transcript_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])


class SessionCreateResponse(BaseModel):
    session_id: str
    title: str


class SessionListItem(BaseModel):
    session_id: str
    title: str
    working_state_summary: str
    turn_count: int
    updated_at: str


class MessageItem(BaseModel):
    seq: int
    role: str
    content: str
    created_at: str


class SSEChatRequest(BaseModel):
    message: str


@router.post("/chat/sessions", response_model=SessionCreateResponse)
def create_chat_session(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    new_session = ChatSession(
        id=generate_uuid(),
        user_id=current_user.username,
        title="新的面试对话",
    )
    db.add(new_session)
    db.commit()
    db.refresh(new_session)
    return SessionCreateResponse(session_id=new_session.id, title=new_session.title)


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
            working_state_summary=summarize_working_state(
                parse_state_blob(row.working_state, lambda: {})
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


@router.get("/memory/items")
async def list_memory_items(current_user: User = Depends(get_current_user)):
    items = await memory_retrieval_service.get_memory_index(current_user.username)
    return {"status": "success", "items": items, "total": len(items)}


@router.get("/memory/items/{memory_id}")
def get_memory_item(
    memory_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = (
        db.query(MemoryItem)
        .filter(MemoryItem.id == memory_id, MemoryItem.user_id == current_user.username)
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Memory item not found")
    return {
        "status": "success",
        "item": {
            "id": row.id,
            "type": row.type,
            "description": row.description,
            "normalized_key": row.normalized_key,
            "content": row.content,
            "confidence": row.confidence or 0.0,
            "source_session_id": row.source_session_id,
            "last_evidence_seq": row.last_evidence_seq,
            "recall_count": row.recall_count or 0,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        },
    }


@router.delete("/memory/items/{memory_id}")
def delete_memory_item(
    memory_id: str,
    current_user: User = Depends(get_current_user),
):
    success = memory_retrieval_service.delete_memory(memory_id, current_user.username)
    if not success:
        raise HTTPException(status_code=404, detail="Memory item not found or access denied")
    return {"status": "success", "message": f"Memory {memory_id} deleted"}


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
        "turn_count": meta["turn_count"] if meta else 0,
        "compaction_cursor": meta["compaction_cursor"] if meta else 0,
        "memory_cursor": meta["memory_cursor"] if meta else 0,
        "working_state": (
            parse_state_blob(meta["working_state"], default_working_state_payload)
            if meta
            else default_working_state_payload()
        ),
        "interview_state": interview_state_service.get_state(session_id, current_user.username),
        "messages": messages,
        "total_messages": len(messages),
    }


def get_ws_current_user(token: str, db: Session) -> User | None:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        username = payload.get("sub")
        if not username:
            return None
        return db.query(User).filter(User.username == username).first()
    except JWTError:
        return None


@router.websocket("/chat/ws/{session_id}")
async def websocket_chat_endpoint(
    websocket: WebSocket,
    session_id: str,
    token: str = Query(...),
    db: Session = Depends(get_db),
):
    user = get_ws_current_user(token, db)
    if not user:
        await websocket.close(code=1008, reason="Unauthorized or expired token")
        return

    session_row = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if not session_row or session_row.user_id != user.username:
        await websocket.close(code=1008, reason="Session not found or access denied")
        return

    await websocket.accept()
    from app.agent.agent_executor import stream_chat_with_agent

    try:
        while True:
            data = await websocket.receive_json()
            message = data.get("message", "")
            if not message:
                continue
            async for chunk in stream_chat_with_agent(message, user.username, session_id):
                if chunk:
                    await websocket.send_json({"type": "chunk", "content": chunk})
            await websocket.send_json({"type": "done"})
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected: session=%s", session_id)
    except Exception as exc:  # noqa: BLE001
        logger.error("WebSocket pipeline failed: %s", exc)
        try:
            await websocket.send_json({"type": "chunk", "content": f"\n\n[system]: {exc}"})
            await websocket.send_json({"type": "done"})
        except Exception:  # noqa: BLE001
            pass


@router.post("/chat/sse/{session_id}")
async def sse_chat_endpoint(
    session_id: str,
    request: SSEChatRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if not row or row.user_id != current_user.username:
        raise HTTPException(status_code=404, detail="Session not found or access denied")

    from app.agent.agent_executor import stream_chat_with_agent

    async def event_generator():
        try:
            async for chunk in stream_chat_with_agent(
                request.message,
                current_user.username,
                session_id,
            ):
                if chunk:
                    yield f"data: {json.dumps({'type': 'chunk', 'content': chunk}, ensure_ascii=False)}\n\n"
            yield "data: {\"type\": \"done\"}\n\n"
        except Exception as exc:  # noqa: BLE001
            logger.error("SSE pipeline failed: %s", exc)
            yield f"data: {json.dumps({'type': 'chunk', 'content': f'[system]: {exc}'}, ensure_ascii=False)}\n\n"
            yield "data: {\"type\": \"done\"}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
