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
"""

import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.database import get_db
from app.models.chat import ChatSession
from app.models.user import User
from app.schemas.chat import SSEChatRequest

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])


@router.post("/chat/sse/{session_id}")
async def sse_chat_endpoint(
    session_id: str,
    request: SSEChatRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Stream one chat turn over SSE for ``session_id``.

    Ownership is enforced up-front (404 on mismatch) so the generator
    doesn't waste an LLM round-trip on a session the caller can't see.
    The frame protocol is intentionally minimal — three event types —
    so frontend parsers stay small and provider-portable.
    """
    row = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if not row or row.user_id != current_user.username:
        raise HTTPException(status_code=404, detail="Session not found or access denied")

    # Lazy import to keep cold startup snappy — agent_executor pulls in
    # the QA pipeline + retrieval modules and isn't needed by the rest
    # of the chat-API router.
    from app.qa_pipeline.agent_executor import stream_chat_with_agent

    async def event_generator():
        try:
            async for chunk in stream_chat_with_agent(
                request.message,
                current_user.username,
                session_id,
            ):
                if not chunk:
                    continue
                stripped = chunk.lstrip()
                if stripped.startswith("[status]"):
                    content = stripped[len("[status]"):].strip().rstrip("\n")
                    yield f"data: {json.dumps({'type': 'status', 'content': content}, ensure_ascii=False)}\n\n"
                else:
                    yield f"data: {json.dumps({'type': 'chunk', 'content': chunk}, ensure_ascii=False)}\n\n"
            yield "data: {\"type\": \"done\"}\n\n"
        except Exception as exc:  # noqa: BLE001 — last-resort net so the stream always closes
            logger.error("SSE pipeline failed: %s", exc)
            yield f"data: {json.dumps({'type': 'chunk', 'content': f'[system]: {exc}'}, ensure_ascii=False)}\n\n"
            yield "data: {\"type\": \"done\"}\n\n"

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
