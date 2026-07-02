"""V2 Task System — 4 independent tools aligned with Claude Code's
TaskCreate / TaskUpdate / TaskGet / TaskList.

Self-registers on import via ``registry.register()``.
"""
from __future__ import annotations

import asyncio
from typing import Any, Optional

from pydantic import BaseModel, Field

from app.agent_runtime.tool_registry import AgentToolContext, ToolEntry, registry
from app.db.database import SessionLocal
from app.services import task_service


# ── Pydantic arg models ─────────────────────────────────────────────────

class TaskCreateArgs(BaseModel):
    subject: str = Field(description="Short title describing the task")
    description: str = Field(default="", description="Optional details or acceptance criteria")


class TaskUpdateArgs(BaseModel):
    task_id: int = Field(description="ID of the task to update")
    status: Optional[str] = Field(default=None, description="New status: pending, in_progress, or completed")
    subject: Optional[str] = Field(default=None, description="Updated title")
    description: Optional[str] = Field(default=None, description="Updated description")


class TaskGetArgs(BaseModel):
    task_id: int = Field(description="ID of the task to retrieve")


class TaskListArgs(BaseModel):
    pass


# ── Handlers ─────────────────────────────────────────────────────────────

def _get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


async def _handle_task_create(args: TaskCreateArgs, ctx: AgentToolContext) -> dict[str, Any]:
    def _sync():
        db = SessionLocal()
        try:
            return task_service.create_task(
                db, ctx.session_id, subject=args.subject, description=args.description,
            )
        finally:
            db.close()

    return await asyncio.to_thread(_sync)


async def _handle_task_update(args: TaskUpdateArgs, ctx: AgentToolContext) -> dict[str, Any]:
    def _sync():
        db = SessionLocal()
        try:
            result = task_service.update_task(
                db, ctx.session_id, args.task_id,
                status=args.status,
                subject=args.subject,
                description=args.description,
            )
            if result is None:
                return {"error": f"task {args.task_id} not found"}
            return result
        finally:
            db.close()

    return await asyncio.to_thread(_sync)


async def _handle_task_get(args: TaskGetArgs, ctx: AgentToolContext) -> dict[str, Any]:
    def _sync():
        db = SessionLocal()
        try:
            result = task_service.get_task(db, ctx.session_id, args.task_id)
            if result is None:
                return {"error": f"task {args.task_id} not found"}
            return result
        finally:
            db.close()

    return await asyncio.to_thread(_sync)


async def _handle_task_list(args: TaskListArgs, ctx: AgentToolContext) -> dict[str, Any]:
    def _sync():
        db = SessionLocal()
        try:
            tasks = task_service.list_tasks(db, ctx.session_id)
            return {"tasks": tasks, "total": len(tasks)}
        finally:
            db.close()

    return await asyncio.to_thread(_sync)


# ── Prompts (Claude Code V2 alignment) ──────────────────────────────────

_TASK_CREATE_PROMPT = """\
Use task_create to break work into trackable steps before starting multi-step tasks.

When to use:
- The user asks for something that involves 3+ distinct steps
- You need to coordinate multiple tool calls toward a goal
- You want to show progress on a complex request

When NOT to use:
- Simple questions or single-step tasks
- Conversational replies that don't involve execution
- When you're just retrieving information

Tips:
- Keep subjects short and action-oriented (e.g. "Analyze JD requirements")
- Create all tasks at the start, then work through them
- Each task should be independently completable
"""

_TASK_UPDATE_PROMPT = """\
Use task_update to track progress as you work through tasks.

Status workflow:
- pending → in_progress: when you start working on a task
- in_progress → completed: when the task is done
- Any status can go back to pending if you need to revisit

Tips:
- Update to in_progress before you start working, completed when done
- If a task turns out to be unnecessary, update its subject to reflect why and mark completed
- You can also update the subject/description if the scope changes
"""

_TASK_GET_PROMPT = """\
Use task_get to check the details of a specific task.
Useful when you need to recall what a task involves before working on it.
"""

_TASK_LIST_PROMPT = """\
Use task_list to see all tasks and their current status.
Call this to review progress before giving a status update or final answer.
"""


# ── Registration ─────────────────────────────────────────────────────────

registry.register(ToolEntry(
    name="task_create",
    description="Create a new task to track a unit of work in this session",
    args_model=TaskCreateArgs,
    handler=_handle_task_create,
    toolset="default",
    emoji="📋",
    prompt=_TASK_CREATE_PROMPT,
))

registry.register(ToolEntry(
    name="task_update",
    description="Update an existing task's status, subject, or description",
    args_model=TaskUpdateArgs,
    handler=_handle_task_update,
    toolset="default",
    emoji="📋",
    prompt=_TASK_UPDATE_PROMPT,
))

registry.register(ToolEntry(
    name="task_get",
    description="Get details of a specific task by ID",
    args_model=TaskGetArgs,
    handler=_handle_task_get,
    toolset="default",
    emoji="📋",
    prompt=_TASK_GET_PROMPT,
))

registry.register(ToolEntry(
    name="task_list",
    description="List all tasks in this session",
    args_model=TaskListArgs,
    handler=_handle_task_list,
    toolset="default",
    emoji="📋",
    prompt=_TASK_LIST_PROMPT,
))
