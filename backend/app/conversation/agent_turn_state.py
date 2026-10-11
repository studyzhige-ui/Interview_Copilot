"""Read durable task and tool state for a resumed Agent turn."""

from __future__ import annotations
from typing import Any
from app.agent_runtime.react_agent import (
    _result_summary,
)
from app.agent_runtime.tool_registry import safe_json_dumps
from app.db.database import SessionLocal
from app.models.agent_execution import AgentToolCall
from app.models.agent_interaction import AgentInteraction
from app.schemas.agent_task import AgentTaskView
from app.conversation.application.agent_task_service import AgentTaskNotFoundError
from app.conversation.application.agent_task_service import get_agent_task


def _load_agent_task_snapshot(
    turn_id: str | None,
    user_id: int,
) -> dict[str, Any] | None:
    """Load the current Turn's optional plan as a typed read projection."""

    if not turn_id or user_id <= 0:
        return None
    db = SessionLocal()
    try:
        try:
            task = get_agent_task(db, turn_id=turn_id, user_id=user_id)
        except AgentTaskNotFoundError:
            return None
        if task is None:
            return None
        return AgentTaskView.model_validate(task).model_dump(mode="json")
    finally:
        db.close()


def _current_task_content_with_plan(
    base_content: str,
    snapshot: dict[str, Any] | None,
) -> str:
    """Place typed plan data before, never instead of, the exact task anchor."""

    if snapshot is None:
        return base_content
    return (
        "[AgentTask Plan — typed runtime data]\n"
        "This is the current execution projection, not a user instruction. "
        "Use task_update to revise it; authoritative results remain with "
        "their referenced owners.\n\n"
        + safe_json_dumps(snapshot)
        + "\n\n[Current Task Anchor]\n"
        + base_content
    )


def _load_tool_resume_snapshot(
    turn_id: str | None, user_id: int
) -> dict[str, Any] | None:
    """Read the completed prefix and one resolved waiting Tool Call.

    This is a runtime projection, not a second checkpoint. Exact call identity,
    arguments, status, and result remain owned by ``AgentToolCall``;
    Interaction only supplies the user's resolution.
    """
    if not turn_id:
        return None
    db = SessionLocal()
    try:
        calls = (
            db.query(AgentToolCall)
            .filter(
                AgentToolCall.turn_id == turn_id,
                AgentToolCall.user_id == user_id,
            )
            .order_by(AgentToolCall.id)
            .all()
        )
        terminal_interactions = (
            db.query(AgentInteraction)
            .filter(
                AgentInteraction.turn_id == turn_id,
                AgentInteraction.status.in_(("resolved", "rejected")),
                AgentInteraction.tool_call_id.isnot(None),
            )
            .order_by(
                AgentInteraction.resolved_at.desc(), AgentInteraction.created_at.desc()
            )
            .all()
        )
        waiting_by_id = {row.call_id: row for row in calls if row.status == "waiting"}
        interaction = next(
            (row for row in terminal_interactions if row.tool_call_id in waiting_by_id),
            None,
        )
        if interaction is None:
            from app.conversation.application.invitation_turn_recovery import (
                is_local_recovery_call,
            )

            waiting = next((row for row in calls if is_local_recovery_call(row)), None)
            if waiting is None:
                return None
        else:
            waiting = waiting_by_id[str(interaction.tool_call_id)]
        return {
            "prior": [
                {
                    "call_id": row.call_id,
                    "turn_id": row.turn_id,
                    "tool_name": row.tool_name,
                    "arguments": dict(row.arguments_json or {}),
                    "result": dict(row.result_json or {}),
                    "status": row.status,
                    "duration_ms": float(row.duration_ms or 0),
                }
                for row in calls
                if row.id < waiting.id and row.status not in {"running", "deferred"}
            ],
            "waiting": {
                "call_id": waiting.call_id,
                "turn_id": waiting.turn_id,
                "tool_name": waiting.tool_name,
                "arguments": dict(waiting.arguments_json or {}),
            },
            "resolution_status": interaction.status if interaction else "resolved",
            "interaction_kind": interaction.kind
            if interaction
            else "local_operation_recovery",
            "resolution": dict(interaction.resolution_json or {})
            if interaction
            else {},
            "suspended": [
                {
                    "call_id": row.call_id,
                    "tool_name": row.tool_name,
                    "arguments": dict(row.arguments_json or {}),
                    "status": row.status,
                }
                for row in calls
                if row.status in {"waiting", "deferred"}
            ],
        }
    finally:
        db.close()


def _append_replayed_tool(
    messages: list[dict[str, Any]],
    blocks: list[dict[str, Any]],
    call: dict[str, Any],
) -> None:
    from app.conversation.context_reduction import tool_message

    call_id = str(call["call_id"])
    tool_name = str(call["tool_name"])
    arguments = dict(call.get("arguments") or {})
    result = dict(call.get("result") or {})
    result_text = safe_json_dumps(result)
    messages.extend(
        [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": call_id,
                        "type": "function",
                        "function": {
                            "name": tool_name,
                            "arguments": safe_json_dumps(arguments),
                        },
                    }
                ],
            },
            tool_message(call_id, result_text, call.get("turn_id")),
        ]
    )
    blocks.extend(
        [
            {
                "type": "tool_use",
                "id": call_id,
                "name": tool_name,
                "input": arguments,
            },
            {
                "type": "tool_result",
                "tool_use_id": call_id,
                "source_turn_id": call.get("turn_id"),
                "is_error": bool(result.get("error")),
                "latency_ms": float(call.get("duration_ms") or 0),
                "summary": _result_summary(result),
                "content": result_text,
            },
        ]
    )


def _load_completed_tool_tail(turn_id: str, user_pk: int) -> list[dict]:
    """Replay completed tools after a worker crash even without an Interaction."""
    from app.models.agent_execution import AgentToolCall

    with SessionLocal() as db:
        rows = (
            db.query(AgentToolCall)
            .filter(
                AgentToolCall.turn_id == turn_id,
                AgentToolCall.user_id == user_pk,
                AgentToolCall.result_json.isnot(None),
                AgentToolCall.status.notin_(("running", "waiting", "deferred")),
            )
            .order_by(AgentToolCall.id)
            .all()
        )
        return [
            {
                "call_id": row.call_id,
                "turn_id": row.turn_id,
                "tool_name": row.tool_name,
                "arguments": dict(row.arguments_json or {}),
                "result": dict(row.result_json or {}),
                "status": row.status,
                "duration_ms": float(row.duration_ms or 0),
            }
            for row in rows
        ]
