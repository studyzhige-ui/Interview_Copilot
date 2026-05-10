import json
import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.agent_runtime import run_react_agent, run_react_agent_stream
from app.core.security import get_current_user
from app.models.user import User
from app.services.agent_trace_service import (
    aggregate_trajectory_metrics,
    get_run_with_steps,
    list_runs,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["agent"])


class ChatRequest(BaseModel):
    message: str = Field(..., description="Message for normal agent chat")


class ReactAgentRequest(BaseModel):
    message: str = Field(..., description="Goal for ReAct tool-using agent")
    include_trace: bool = Field(default=False, description="Whether to return tool trace")


@router.post("/agent/chat")
async def api_agent_chat(
    request: ChatRequest,
    current_user: User = Depends(get_current_user),
    x_session_id: str = Header("default_session", description="Session id"),
):
    """
    Existing normal chat endpoint.
    This path keeps the current RAG-based conversational behavior.
    """
    try:
        # Lazy import to avoid coupling app startup to legacy agent pipeline dependencies.
        from app.agent.agent_executor import stream_chat_with_agent

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


@router.post("/agent/react/chat")
async def api_react_agent_chat(
    request: ReactAgentRequest,
    current_user: User = Depends(get_current_user),
    x_session_id: str = Header("default_session", description="Session id"),
):
    """
    ReAct agent endpoint, isolated from normal chat flow.
    """
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
    """
    SSE streaming endpoint for the ReAct agent.
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
            error_payload = json.dumps({"type": "error", "data": {"error": str(exc)}}, ensure_ascii=False)
            yield f"data: {error_payload}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/agent/runs")
async def api_list_agent_runs(
    current_user: User = Depends(get_current_user),
    session_id: str | None = Query(default=None, description="Filter by session id"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    rows = await list_runs(
        user_id=current_user.username,
        session_id=session_id,
        limit=limit,
        offset=offset,
    )
    return {"status": "success", "runs": rows}


@router.get("/agent/runs/{run_id}")
async def api_get_agent_run(
    run_id: str,
    current_user: User = Depends(get_current_user),
):
    payload = await get_run_with_steps(run_id=run_id, user_id=current_user.username)
    if payload is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return {"status": "success", "run": payload}


@router.get("/agent/metrics")
async def api_get_agent_metrics(
    current_user: User = Depends(get_current_user),
    session_id: str | None = Query(default=None, description="Optional session filter"),
):
    metrics = await aggregate_trajectory_metrics(
        user_id=current_user.username,
        session_id=session_id,
    )
    return {"status": "success", "metrics": metrics}
