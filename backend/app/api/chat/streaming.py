"""WebSocket + SSE streaming endpoints for QA dialogue."""

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import get_current_user
from app.db.database import get_db
from app.models.chat import ChatSession
from app.models.user import User
from app.schemas.chat import SSEChatRequest

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])


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
    from app.qa_pipeline.agent_executor import stream_chat_with_agent

    try:
        while True:
            data = await websocket.receive_json()
            message = data.get("message", "")
            if not message:
                continue
            async for chunk in stream_chat_with_agent(message, user.username, session_id):
                if not chunk:
                    continue
                # Separate transport: pipeline-internal status hints go on a
                # different event type so the client can display them as
                # progress indicators rather than concatenating them into the
                # final assistant message.
                stripped = chunk.lstrip()
                if stripped.startswith("[status]"):
                    content = stripped[len("[status]"):].strip().rstrip("\n")
                    await websocket.send_json({"type": "status", "content": content})
                else:
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

    from app.qa_pipeline.agent_executor import stream_chat_with_agent

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

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
