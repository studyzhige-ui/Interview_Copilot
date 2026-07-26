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
      tool_start / tool_done / budget             — agent-mode only

    L1 (chat) uses ``mode="chat"``; the engine instantiates
    :class:`ChatPipelineStrategy` and fires status / text_delta / text /
    error / done, plus a single ``sources`` event on RAG turns (the L1
    [K#] citation sources). L2 (agent) uses ``mode="agent"`` and gets the
    tool / budget events on top.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.rate_limit import RATE_EXPENSIVE, limiter
from app.core.security import get_current_user
from app.core.user_identity import resolve_user_pk
from app.db.database import get_db
from app.models.chat import Conversation
from app.models.conversation_turn import ConversationTurn
from app.models.user import User
from app.schemas.chat import ChatTurnRequest

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])


def _turn_status(turn_id: str) -> str | None:
    from app.db.database import SessionLocal

    session = SessionLocal()
    try:
        row = session.get(ConversationTurn, turn_id)
        return row.status if row else None
    finally:
        session.close()


def _resolve_mode(row: Conversation, requested: str | None, db: Session) -> str:
    mode = requested or row.mode or "chat"
    if row.type == "mock_interview":
        return "chat"
    if requested and requested != row.mode:
        row.mode = requested
        db.commit()
    return mode


@router.post("/chat/{session_id}/turns", status_code=202)
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
    from app.services.chat.turn_executor import create_turn, schedule_turn

    try:
        await turn_event_buffer.ping()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=503, detail="Turn event buffer is unavailable"
        ) from exc
    try:
        turn = create_turn(
            db,
            row,
            user_id=user_pk,
            mode=_resolve_mode(row, body.mode, db),
            message=body.message,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=409,
            detail={"message": "A turn is already running", "turn_id": str(exc)},
        ) from exc
    schedule_turn(turn.id)
    return {"turn_id": turn.id, "status": turn.status}


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
                status = await asyncio.to_thread(_turn_status, turn_id)
                if status in {"completed", "failed", "cancelled"}:
                    from app.conversation.events import HarnessEvent

                    yield f"data: {HarnessEvent.done(step=0, elapsed_ms=0).to_json()}\n\n"
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
    if turn.status not in {"pending", "running"}:
        return {"turn_id": turn_id, "status": turn.status, "cancelled": False}
    from app.core.background_tasks import cancel_background_task

    from app.services.chat.turn_executor import cancel_pending_turn
    from app.services.chat.turn_event_buffer import turn_event_buffer

    await turn_event_buffer.request_cancel(turn_id)
    cancelled_before_start = cancel_pending_turn(db, turn_id, user_pk)
    cancelled = cancel_background_task(f"chat-turn:{turn_id}")
    return {
        "turn_id": turn_id,
        "status": "cancelled" if cancelled_before_start else "cancelling",
        "cancelled": True,
        "local": cancelled,
    }
