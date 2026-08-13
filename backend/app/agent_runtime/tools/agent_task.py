"""Narrow runtime tools for the current Turn's optional flat AgentTask.

These handlers mutate only the plan projection owned by the already-admitted
Agent Turn. They do not schedule work, own waiting, or replace product-domain
services and Tool results.
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.agent_runtime.tool_policy import ToolEffect
from app.agent_runtime.tool_registry import AgentToolContext, ToolDefinition, registry
from app.db.database import SessionLocal
from app.schemas.agent_task import (
    AgentTaskView,
    CreateAgentTaskRequest,
    ReviseAgentTaskRequest,
)
from app.services.chat.agent_task_service import (
    AgentTaskConflictError,
    AgentTaskFrozenError,
    AgentTaskNotFoundError,
    AgentTaskOwnershipError,
    create_agent_task,
    revise_agent_task,
)


def _require_runtime_scope(ctx: AgentToolContext) -> tuple[str, int]:
    if not ctx.turn_id or ctx.user_pk is None or ctx.user_pk <= 0:
        raise ValueError("agent_task_runtime_scope_unavailable")
    return ctx.turn_id, ctx.user_pk


def _view_payload(task: Any) -> dict[str, Any]:
    return AgentTaskView.model_validate(task).model_dump(mode="json")


def _known_error(exc: Exception) -> dict[str, Any] | None:
    if isinstance(exc, AgentTaskOwnershipError):
        return {"error": "permission_denied"}
    if isinstance(exc, AgentTaskFrozenError):
        return {"error": "agent_task_frozen", "detail": str(exc)}
    if isinstance(exc, AgentTaskNotFoundError):
        return {"error": "agent_task_not_found", "detail": str(exc)}
    if isinstance(exc, AgentTaskConflictError):
        return {"error": "agent_task_conflict", "detail": str(exc)}
    return None


async def task_create(
    args: CreateAgentTaskRequest,
    ctx: AgentToolContext,
) -> dict[str, Any]:
    """Create the sole plan for a genuinely complex current Agent Turn."""

    turn_id, user_pk = _require_runtime_scope(ctx)

    def create() -> dict[str, Any]:
        db = SessionLocal()
        try:
            task = create_agent_task(
                db,
                turn_id=turn_id,
                user_id=user_pk,
                request=args,
            )
            payload = _view_payload(task)
            db.commit()
            return {"agent_task": payload}
        except Exception as exc:
            db.rollback()
            known = _known_error(exc)
            if known is not None:
                return known
            raise
        finally:
            db.close()

    return await asyncio.to_thread(create)


async def task_update(
    args: ReviseAgentTaskRequest,
    ctx: AgentToolContext,
) -> dict[str, Any]:
    """CAS-replace the current Turn's flat plan with its next version."""

    turn_id, user_pk = _require_runtime_scope(ctx)

    def update() -> dict[str, Any]:
        db = SessionLocal()
        try:
            task = revise_agent_task(
                db,
                turn_id=turn_id,
                user_id=user_pk,
                request=args,
            )
            payload = _view_payload(task)
            db.commit()
            return {"agent_task": payload}
        except Exception as exc:
            db.rollback()
            known = _known_error(exc)
            if known is not None:
                return known
            raise
        finally:
            db.close()

    return await asyncio.to_thread(update)


registry.register(
    ToolDefinition(
        name="task_create",
        description=(
            "Create one visible flat execution plan for this Turn only when the "
            "user's request is genuinely complex and multi-stage."
        ),
        args_model=CreateAgentTaskRequest,
        handler=task_create,
        effect=ToolEffect.RUNTIME_CONTROL,
        concurrency_safe=False,
        emoji="🧭",
        prompt=(
            "Use only for a complex multi-stage request. Do not create a plan for "
            "a simple answer, analysis, summary, or a few direct calls. The phases "
            "are a flat plan-execute list; never put waiting, approval, connection, "
            "blocked/failed/cancelled state, Tool logs, or copied results in them."
        ),
    )
)

registry.register(
    ToolDefinition(
        name="task_update",
        description=(
            "Revise the current Turn's existing flat AgentTask using version CAS, "
            "including phase progress and identity-only result references."
        ),
        args_model=ReviseAgentTaskRequest,
        handler=task_update,
        effect=ToolEffect.RUNTIME_CONTROL,
        concurrency_safe=False,
        emoji="🧭",
        prompt=(
            "Send the complete next plan with expected_version. Keep completed "
            "phases unchanged; use completed or skipped for every phase before a "
            "successful final answer. Do not use this tool as a scheduler or log."
        ),
    )
)


__all__ = ["task_create", "task_update"]
