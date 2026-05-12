"""``/agent/runs/*`` and ``/agent/metrics`` — agent-run inspection endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.security import get_current_user
from app.models.user import User
from app.services.agent_trace_service import (
    aggregate_trajectory_metrics,
    get_run_with_steps,
    list_runs,
)

router = APIRouter(tags=["agent"])


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
