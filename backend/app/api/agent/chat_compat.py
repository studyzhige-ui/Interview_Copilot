"""``/agent/chat`` — legacy compatibility wrapper around the chat pipeline.

The endpoint name is preserved for clients that still POST to ``/agent/chat``;
internally it constructs a :class:`ConversationEngine` with the chat
strategy (the same plumbing used by ``/chat/sse/{session_id}``),
consumes the HarnessEvent stream, and concatenates the final answer
into a single ``{status, reply}`` response.

Newer code should call ``/chat/sse/{session_id}`` directly for the
real streaming UX.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Header, HTTPException

from app.core.security import get_current_user
from app.models.user import User
from app.schemas.agent import ChatRequest

logger = logging.getLogger(__name__)

router = APIRouter(tags=["agent"])


@router.post("/agent/chat")
async def api_agent_chat(
    request: ChatRequest,
    current_user: User = Depends(get_current_user),
    x_session_id: str = Header("default_session", description="Session id"),
):
    """Legacy chat endpoint — batch wrapper over the streaming engine."""
    try:
        # Lazy import — keeps the conversation engine + strategies out
        # of import-time graph for unrelated endpoints.
        from app.conversation import ConversationEngine, make_chat_strategy

        engine = ConversationEngine(
            user_id=current_user.username,
            session_id=x_session_id,
            user_message=request.message,
            strategy=make_chat_strategy(),
        )
        reply = ""
        async for event in engine.submit_message():
            if event.type.value == "text_delta":
                reply += event.data.get("delta", "")
            elif event.type.value == "text" and not reply:
                # Fallback if no text_delta arrived (e.g. tests that
                # only emit a final `text` event).
                reply = event.data.get("content", "")

        return {"status": "success", "reply": reply}
    except Exception as e:  # noqa: BLE001
        logger.error("Agent chat invocation failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
