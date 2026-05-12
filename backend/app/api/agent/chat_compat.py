"""``/agent/chat`` — legacy compatibility wrapper around the L1 QA pipeline.

The endpoint name is preserved for clients that still POST to ``/agent/chat``;
internally it streams via :func:`app.agent.agent_executor.stream_chat_with_agent`
and concatenates the chunks.  Newer code should call the SSE chat endpoint
on the chat API instead.
"""

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
    """Legacy chat endpoint — keeps existing RAG-based conversational behavior."""
    try:
        # Lazy import to avoid coupling app startup to legacy agent pipeline deps.
        from app.qa_pipeline.agent_executor import stream_chat_with_agent

        reply = ""
        async for chunk in stream_chat_with_agent(
            request.message,
            user_id=current_user.username,
            session_id=x_session_id,
        ):
            if chunk:
                reply += chunk

        return {"status": "success", "reply": reply}
    except Exception as e:
        logger.error("Agent chat invocation failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
