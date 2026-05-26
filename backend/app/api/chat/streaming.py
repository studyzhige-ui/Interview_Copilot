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
      tool_start / tool_done / budget             — agent-mode only

    L1 (chat) uses ``mode="chat"``; the engine instantiates
    :class:`ChatPipelineStrategy` and only the status / text_delta /
    text / error / done events fire. L2 (agent) uses ``mode="agent"``
    and gets the tool / budget events on top.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.rate_limit import RATE_EXPENSIVE, limiter
from app.core.security import get_current_user
from app.db.database import get_db
from app.models.chat import ChatSession
from app.models.user import User
from app.schemas.chat import SSEChatRequest

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])


@router.post("/chat/sse/{session_id}")
@limiter.limit(RATE_EXPENSIVE)
async def sse_chat_endpoint(
    request: Request,
    response: Response,
    session_id: str,
    body: SSEChatRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Stream one chat turn over SSE for ``session_id``.

    Ownership is enforced up-front (404 on mismatch) so the generator
    doesn't waste an LLM round-trip on a session the caller can't see.
    """
    # NB (P1-H deferral): this query is SYNC on the event-loop thread.
    # The audit considered wrapping it in ``asyncio.to_thread`` for
    # consistency with engine._prepare, but the FastAPI-injected ``db``
    # is a sync ``Session`` whose lifecycle is bound to this request
    # scope. Handing it to another thread risks cross-thread session
    # use (SQLAlchemy 1.4+ doesn't guarantee thread-safety on the sync
    # session). The query is a single indexed lookup (~3-10ms) — the
    # complexity-vs-perf trade-off lands on keeping it sync. If load
    # testing later shows this is a real bottleneck, the right fix is
    # to open a fresh ``SessionLocal()`` inside ``to_thread`` rather
    # than reusing ``db``.
    row = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if not row or row.user_id != current_user.username:
        raise HTTPException(status_code=404, detail="Session not found or access denied")

    # Lazy import so cold-startup doesn't pay the conversation-engine
    # cost when other chat-router endpoints are hit. The agent factory
    # in turn lazy-imports the full agent_runtime, which is heavy.
    from app.conversation import (
        ConversationEngine,
        make_agent_strategy,
        make_chat_strategy,
    )

    # Dispatch on the request's ``mode`` field. The frontend's AGENT
    # pill sends ``mode="agent"``; everything else (and the default
    # for back-compat) is the L1 chat pipeline.
    strategy = (
        make_agent_strategy() if body.mode == "agent" else make_chat_strategy()
    )

    async def event_generator():
        engine = ConversationEngine(
            user_id=current_user.username,
            session_id=session_id,
            user_message=body.message,
            strategy=strategy,
        )
        try:
            async for event in engine.submit_message():
                yield f"data: {event.to_json()}\n\n"
        except Exception as exc:  # noqa: BLE001 — last-resort net so the stream always closes
            logger.error("SSE pipeline failed: %s", exc)
            # Fall back to a hand-rolled error+done so the client
            # always gets a terminator.
            from app.conversation.events import HarnessEvent
            yield f"data: {HarnessEvent.error(str(exc)).to_json()}\n\n"
            yield f"data: {HarnessEvent.done(step=0, elapsed_ms=0).to_json()}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            # Disable nginx/proxy buffering — without this header an
            # SSE response gets buffered into a single chunk and the
            # whole "streaming" effect collapses.
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
