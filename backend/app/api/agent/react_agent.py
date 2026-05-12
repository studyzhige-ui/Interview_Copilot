"""``/agent/react/*`` — ReAct tool-using agent endpoints (synchronous + SSE)."""

import json
import logging

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import StreamingResponse

from app.agent_runtime import run_react_agent, run_react_agent_stream
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.agent import ReactAgentRequest

logger = logging.getLogger(__name__)

router = APIRouter(tags=["agent"])


@router.post("/agent/react/chat")
async def api_react_agent_chat(
    request: ReactAgentRequest,
    current_user: User = Depends(get_current_user),
    x_session_id: str = Header("default_session", description="Session id"),
):
    """ReAct agent endpoint, isolated from normal chat flow."""
    try:
        result = await run_react_agent(
            user_message=request.message,
            user_id=current_user.username,
            session_id=x_session_id,
        )
        payload = {
            "status": "success",
            "run_id": result["run_id"],
            "reply": result["reply"],
            "steps_used": result["steps_used"],
            "tool_calls": result["tool_calls"],
            "prompt_tokens": result["prompt_tokens"],
            "completion_tokens": result["completion_tokens"],
            "budget_stop_reason": result["budget_stop_reason"],
        }
        if request.include_trace:
            payload["trace"] = result["trace"]
        return payload
    except Exception as e:
        logger.error("ReAct agent invocation failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/agent/react/stream")
async def api_react_agent_stream(
    request: ReactAgentRequest,
    current_user: User = Depends(get_current_user),
    x_session_id: str = Header("default_session", description="Session id"),
):
    """SSE streaming endpoint for the ReAct agent.

    Yields HarnessEvents as Server-Sent Events for real-time tool
    call visualization in the frontend.
    """
    async def event_generator():
        try:
            async for event in run_react_agent_stream(
                user_message=request.message,
                user_id=current_user.username,
                session_id=x_session_id,
            ):
                yield f"data: {event.to_json()}\n\n"
        except Exception as exc:
            logger.error("SSE agent stream failed: %s", exc)
            error_payload = json.dumps(
                {"type": "error", "data": {"error": str(exc)}},
                ensure_ascii=False,
            )
            yield f"data: {error_payload}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
