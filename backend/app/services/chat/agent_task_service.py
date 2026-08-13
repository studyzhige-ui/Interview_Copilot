"""Application boundary for one optional flat AgentTask per Turn.

Callers decide that a request is complex enough to need a visible plan.  This
service only enforces ownership, the flat-plan invariants, CAS/idempotency,
completed-phase immutability, and terminal Turn freezing.  It never schedules
Tool calls or writes a second Turn outcome.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.types import utc_now
from app.models.agent_task import AgentTask, AgentTaskRevision
from app.models.conversation_turn import ConversationTurn
from app.schemas.agent_task import (
    AgentTaskPlan,
    CreateAgentTaskRequest,
    ReviseAgentTaskRequest,
)


_TERMINAL_TURN_STATUSES = {"completed", "blocked", "failed", "cancelled"}


class AgentTaskNotFoundError(LookupError):
    """The requested Turn or AgentTask does not exist."""


class AgentTaskOwnershipError(PermissionError):
    """The caller does not own the authoritative Turn."""


class AgentTaskConflictError(RuntimeError):
    """Creation or revision conflicts with durable task state."""


class AgentTaskFrozenError(RuntimeError):
    """The owning Turn is terminal, so its plan snapshot is immutable."""


def _fingerprint(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _plan_payload(plan: AgentTaskPlan) -> dict[str, Any]:
    return {
        "objective": plan.objective,
        "completion_conditions": list(plan.completion_conditions),
        "phases": [phase.model_dump(mode="json") for phase in plan.phases],
    }


def _creation_fingerprint(request: CreateAgentTaskRequest) -> str:
    return _fingerprint(_plan_payload(request))


def _revision_fingerprint(request: ReviseAgentTaskRequest) -> str:
    return _fingerprint(
        {
            **_plan_payload(request),
            "expected_version": request.expected_version,
            "reason": request.reason,
        }
    )


def _owned_turn_locked(
    db: Session,
    *,
    turn_id: str,
    user_id: int,
) -> ConversationTurn:
    turn = (
        db.query(ConversationTurn)
        .filter(ConversationTurn.id == turn_id)
        .with_for_update()
        .one_or_none()
    )
    if turn is None:
        raise AgentTaskNotFoundError(f"Conversation turn {turn_id} does not exist")
    if turn.user_id != user_id:
        raise AgentTaskOwnershipError(
            f"User {user_id} does not own conversation turn {turn_id}"
        )
    return turn


def _ensure_mutable(turn: ConversationTurn, task: AgentTask | None = None) -> None:
    if turn.status in _TERMINAL_TURN_STATUSES or (
        task is not None and task.frozen_at is not None
    ):
        raise AgentTaskFrozenError(
            f"AgentTask for terminal conversation turn {turn.id} is frozen"
        )


def get_agent_task(
    db: Session,
    *,
    turn_id: str,
    user_id: int,
) -> AgentTask | None:
    """Return the owned Turn's optional AgentTask without changing it."""

    turn = db.get(ConversationTurn, turn_id)
    if turn is None:
        raise AgentTaskNotFoundError(f"Conversation turn {turn_id} does not exist")
    if turn.user_id != user_id:
        raise AgentTaskOwnershipError(
            f"User {user_id} does not own conversation turn {turn_id}"
        )
    return db.query(AgentTask).filter(AgentTask.turn_id == turn_id).one_or_none()


def create_agent_task(
    db: Session,
    *,
    turn_id: str,
    user_id: int,
    request: CreateAgentTaskRequest,
) -> AgentTask:
    """Explicitly create the only AgentTask for a complex active Agent Turn."""

    turn = _owned_turn_locked(db, turn_id=turn_id, user_id=user_id)
    fingerprint = _creation_fingerprint(request)
    existing = (
        db.query(AgentTask)
        .filter(AgentTask.turn_id == turn_id)
        .with_for_update()
        .one_or_none()
    )
    if existing is not None:
        if (
            existing.creation_idempotency_key == request.idempotency_key
            and existing.creation_fingerprint == fingerprint
        ):
            return existing
        raise AgentTaskConflictError(
            f"Conversation turn {turn_id} already has an AgentTask"
        )

    _ensure_mutable(turn)
    if turn.mode != "agent":
        raise AgentTaskConflictError("AgentTask may only be created for an Agent Turn")

    payload = _plan_payload(request)
    task = AgentTask(
        turn_id=turn_id,
        objective=payload["objective"],
        completion_conditions_json=payload["completion_conditions"],
        phases_json=payload["phases"],
        version=1,
        creation_idempotency_key=request.idempotency_key,
        creation_fingerprint=fingerprint,
    )
    try:
        db.add(task)
        db.flush()
    except IntegrityError as exc:
        raise AgentTaskConflictError(
            f"Conversation turn {turn_id} already has an AgentTask"
        ) from exc
    return task


def _assert_completed_phases_unchanged(
    old_phases: list[dict[str, Any]],
    new_phases: list[dict[str, Any]],
) -> None:
    new_by_id = {phase["id"]: phase for phase in new_phases}
    for old_phase in old_phases:
        if old_phase.get("status") != "completed":
            continue
        if new_by_id.get(old_phase.get("id")) != old_phase:
            raise AgentTaskConflictError(
                "completed AgentTask phases cannot be removed or rewritten; "
                "add an explicit correction phase instead"
            )


def _changed_phase_ids(
    old_phases: list[dict[str, Any]],
    new_phases: list[dict[str, Any]],
) -> list[str]:
    old_by_id = {phase["id"]: phase for phase in old_phases}
    new_by_id = {phase["id"]: phase for phase in new_phases}
    ordered_ids = [phase["id"] for phase in old_phases]
    ordered_ids.extend(
        phase["id"] for phase in new_phases if phase["id"] not in old_by_id
    )
    return [
        phase_id
        for phase_id in ordered_ids
        if old_by_id.get(phase_id) != new_by_id.get(phase_id)
    ]


def revise_agent_task(
    db: Session,
    *,
    turn_id: str,
    user_id: int,
    request: ReviseAgentTaskRequest,
) -> AgentTask:
    """CAS-replace the current flat plan and append one idempotency revision."""

    turn = _owned_turn_locked(db, turn_id=turn_id, user_id=user_id)
    task = (
        db.query(AgentTask)
        .filter(AgentTask.turn_id == turn_id)
        .with_for_update()
        .one_or_none()
    )
    if task is None:
        raise AgentTaskNotFoundError(
            f"Conversation turn {turn_id} does not have an AgentTask"
        )

    fingerprint = _revision_fingerprint(request)
    replay = (
        db.query(AgentTaskRevision)
        .filter(
            AgentTaskRevision.agent_task_id == task.id,
            AgentTaskRevision.idempotency_key == request.idempotency_key,
        )
        .one_or_none()
    )
    if replay is not None:
        if replay.request_fingerprint != fingerprint:
            raise AgentTaskConflictError(
                "AgentTask revision idempotency key was reused with another request"
            )
        return task

    _ensure_mutable(turn, task)
    if task.version != request.expected_version:
        raise AgentTaskConflictError(
            f"AgentTask {task.id} expected version {request.expected_version}; "
            f"current version is {task.version}"
        )

    payload = _plan_payload(request)
    old_phases = list(task.phases_json or [])
    new_phases = payload["phases"]
    _assert_completed_phases_unchanged(old_phases, new_phases)
    changed_phase_ids = _changed_phase_ids(old_phases, new_phases)
    new_version = task.version + 1

    changed = (
        db.query(AgentTask)
        .filter(
            AgentTask.id == task.id,
            AgentTask.version == request.expected_version,
            AgentTask.frozen_at.is_(None),
        )
        .update(
            {
                AgentTask.objective: payload["objective"],
                AgentTask.completion_conditions_json: payload["completion_conditions"],
                AgentTask.phases_json: new_phases,
                AgentTask.version: new_version,
                AgentTask.updated_at: utc_now(),
            },
            synchronize_session=False,
        )
    )
    if changed != 1:
        raise AgentTaskConflictError(
            f"AgentTask {task.id} lost its version {request.expected_version} CAS"
        )

    db.add(
        AgentTaskRevision(
            agent_task_id=task.id,
            idempotency_key=request.idempotency_key,
            request_fingerprint=fingerprint,
            from_version=request.expected_version,
            to_version=new_version,
            reason=request.reason,
            changed_phase_ids_json=changed_phase_ids,
        )
    )
    db.flush()
    refreshed = (
        db.query(AgentTask).populate_existing().filter(AgentTask.id == task.id).one()
    )
    return refreshed


def freeze_agent_task_for_terminal_turn(
    db: Session,
    *,
    turn_id: str,
) -> AgentTask | None:
    """Idempotently freeze a plan after the authoritative Turn is terminal."""

    turn = (
        db.query(ConversationTurn)
        .filter(ConversationTurn.id == turn_id)
        .with_for_update()
        .one_or_none()
    )
    if turn is None:
        raise AgentTaskNotFoundError(f"Conversation turn {turn_id} does not exist")
    if turn.status not in _TERMINAL_TURN_STATUSES:
        raise AgentTaskConflictError(
            f"Conversation turn {turn_id} is not terminal and cannot freeze its plan"
        )
    task = (
        db.query(AgentTask)
        .filter(AgentTask.turn_id == turn_id)
        .with_for_update()
        .one_or_none()
    )
    if task is None or task.frozen_at is not None:
        return task
    task.frozen_at = turn.completed_at or utc_now()
    task.updated_at = utc_now()
    db.flush()
    return task


def agent_task_structure_complete(task: AgentTask | None) -> bool:
    """Return the deterministic completion-gate result for an optional plan."""

    if task is None:
        return True
    return all(
        phase.get("status") in {"completed", "skipped"}
        for phase in (task.phases_json or [])
    )


__all__ = [
    "AgentTaskConflictError",
    "AgentTaskFrozenError",
    "AgentTaskNotFoundError",
    "AgentTaskOwnershipError",
    "agent_task_structure_complete",
    "create_agent_task",
    "freeze_agent_task_for_terminal_turn",
    "get_agent_task",
    "revise_agent_task",
]
