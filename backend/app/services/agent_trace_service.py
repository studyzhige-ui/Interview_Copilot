import asyncio
import json
from datetime import datetime
from typing import Any

from app.db.database import SessionLocal
from app.models.agent_trace import AgentRun, AgentStep


def _safe_json_dump(payload: Any) -> str:
    try:
        return json.dumps(payload, ensure_ascii=False)
    except Exception:
        return json.dumps({"non_serializable": str(payload)}, ensure_ascii=False)


def _safe_json_load(text: str) -> Any:
    if not text:
        return {}
    try:
        return json.loads(text)
    except Exception:
        return {"raw": text}


def _create_run_sync(user_id: str, session_id: str, goal: str, mode: str) -> str:
    db = SessionLocal()
    try:
        run = AgentRun(
            user_id=user_id,
            session_id=session_id,
            goal=goal,
            mode=mode,
            status="running",
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        return run.id
    finally:
        db.close()


async def create_run(user_id: str, session_id: str, goal: str, mode: str = "function_calling") -> str:
    return await asyncio.to_thread(_create_run_sync, user_id, session_id, goal, mode)


def _append_step_sync(
    *,
    run_id: str,
    step_index: int,
    action_type: str,
    tool_name: str | None,
    tool_call_id: str | None,
    tool_args: dict[str, Any] | None,
    observation: Any,
    assistant_content: str,
    is_error: bool,
    latency_ms: float,
) -> None:
    db = SessionLocal()
    try:
        db.add(
            AgentStep(
                run_id=run_id,
                step_index=step_index,
                action_type=action_type,
                tool_name=tool_name,
                tool_call_id=tool_call_id,
                tool_args_json=_safe_json_dump(tool_args or {}),
                observation_json=_safe_json_dump(observation),
                assistant_content=assistant_content or "",
                is_error=is_error,
                latency_ms=latency_ms,
            )
        )
        db.commit()
    finally:
        db.close()


async def append_step(
    *,
    run_id: str,
    step_index: int,
    action_type: str,
    tool_name: str | None = None,
    tool_call_id: str | None = None,
    tool_args: dict[str, Any] | None = None,
    observation: Any = None,
    assistant_content: str = "",
    is_error: bool = False,
    latency_ms: float = 0.0,
) -> None:
    await asyncio.to_thread(
        _append_step_sync,
        run_id=run_id,
        step_index=step_index,
        action_type=action_type,
        tool_name=tool_name,
        tool_call_id=tool_call_id,
        tool_args=tool_args,
        observation=observation,
        assistant_content=assistant_content,
        is_error=is_error,
        latency_ms=latency_ms,
    )


def _finish_run_sync(
    *,
    run_id: str,
    status: str,
    final_answer: str,
    steps_used: int,
    tool_calls: int,
    prompt_tokens: int,
    completion_tokens: int,
    total_latency_ms: float,
    error_message: str | None,
    budget_stop_reason: str | None,
) -> None:
    db = SessionLocal()
    try:
        run = db.query(AgentRun).filter(AgentRun.id == run_id).first()
        if not run:
            return
        run.status = status
        run.final_answer = final_answer or ""
        run.steps_used = steps_used
        run.tool_calls = tool_calls
        run.prompt_tokens = prompt_tokens
        run.completion_tokens = completion_tokens
        run.total_latency_ms = total_latency_ms
        run.error_message = error_message
        run.budget_stop_reason = budget_stop_reason
        run.finished_at = datetime.utcnow()
        db.commit()
    finally:
        db.close()


async def finish_run(
    *,
    run_id: str,
    status: str,
    final_answer: str,
    steps_used: int,
    tool_calls: int,
    prompt_tokens: int,
    completion_tokens: int,
    total_latency_ms: float,
    error_message: str | None = None,
    budget_stop_reason: str | None = None,
) -> None:
    await asyncio.to_thread(
        _finish_run_sync,
        run_id=run_id,
        status=status,
        final_answer=final_answer,
        steps_used=steps_used,
        tool_calls=tool_calls,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_latency_ms=total_latency_ms,
        error_message=error_message,
        budget_stop_reason=budget_stop_reason,
    )


def _serialize_run(run: AgentRun) -> dict[str, Any]:
    return {
        "run_id": run.id,
        "user_id": run.user_id,
        "session_id": run.session_id,
        "mode": run.mode,
        "goal": run.goal,
        "status": run.status,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "steps_used": run.steps_used,
        "tool_calls": run.tool_calls,
        "prompt_tokens": run.prompt_tokens,
        "completion_tokens": run.completion_tokens,
        "total_latency_ms": run.total_latency_ms,
        "budget_stop_reason": run.budget_stop_reason,
        "error_message": run.error_message,
    }


def _serialize_step(step: AgentStep) -> dict[str, Any]:
    return {
        "step_index": step.step_index,
        "action_type": step.action_type,
        "tool_name": step.tool_name,
        "tool_call_id": step.tool_call_id,
        "tool_args": _safe_json_load(step.tool_args_json),
        "observation": _safe_json_load(step.observation_json),
        "assistant_content": step.assistant_content,
        "is_error": step.is_error,
        "latency_ms": step.latency_ms,
        "created_at": step.created_at.isoformat() if step.created_at else None,
    }


def _get_run_with_steps_sync(run_id: str, user_id: str) -> dict[str, Any] | None:
    db = SessionLocal()
    try:
        run = db.query(AgentRun).filter(AgentRun.id == run_id, AgentRun.user_id == user_id).first()
        if not run:
            return None
        payload = _serialize_run(run)
        payload["final_answer"] = run.final_answer
        payload["steps"] = [_serialize_step(step) for step in run.steps]
        return payload
    finally:
        db.close()


async def get_run_with_steps(run_id: str, user_id: str) -> dict[str, Any] | None:
    return await asyncio.to_thread(_get_run_with_steps_sync, run_id, user_id)


def _list_runs_sync(user_id: str, session_id: str | None, limit: int, offset: int) -> list[dict[str, Any]]:
    db = SessionLocal()
    try:
        query = db.query(AgentRun).filter(AgentRun.user_id == user_id)
        if session_id:
            query = query.filter(AgentRun.session_id == session_id)
        rows = (
            query.order_by(AgentRun.started_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return [_serialize_run(row) for row in rows]
    finally:
        db.close()


async def list_runs(user_id: str, session_id: str | None, limit: int, offset: int) -> list[dict[str, Any]]:
    return await asyncio.to_thread(_list_runs_sync, user_id, session_id, limit, offset)


def _aggregate_trajectory_metrics_sync(user_id: str, session_id: str | None) -> dict[str, Any]:
    db = SessionLocal()
    try:
        query = db.query(AgentRun).filter(AgentRun.user_id == user_id)
        if session_id:
            query = query.filter(AgentRun.session_id == session_id)
        runs = query.all()
        if not runs:
            return {
                "run_count": 0,
                "completion_rate": 0.0,
                "avg_steps": 0.0,
                "avg_tool_calls": 0.0,
                "invalid_tool_call_rate": 0.0,
                "avg_latency_ms": 0.0,
            }

        run_ids = [run.id for run in runs]
        steps = db.query(AgentStep).filter(AgentStep.run_id.in_(run_ids)).all()
        tool_steps = [step for step in steps if step.action_type == "tool_call"]
        invalid_tool_steps = [step for step in tool_steps if step.is_error]
        finished_runs = [run for run in runs if run.status == "completed"]
        return {
            "run_count": len(runs),
            "completion_rate": round(len(finished_runs) / len(runs), 4),
            "avg_steps": round(sum(run.steps_used for run in runs) / len(runs), 4),
            "avg_tool_calls": round(sum(run.tool_calls for run in runs) / len(runs), 4),
            "invalid_tool_call_rate": round(
                len(invalid_tool_steps) / len(tool_steps), 4
            ) if tool_steps else 0.0,
            "avg_latency_ms": round(sum(run.total_latency_ms for run in runs) / len(runs), 2),
        }
    finally:
        db.close()


async def aggregate_trajectory_metrics(user_id: str, session_id: str | None) -> dict[str, Any]:
    return await asyncio.to_thread(_aggregate_trajectory_metrics_sync, user_id, session_id)
