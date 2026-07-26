"""Synchronous CRUD layer for session-scoped tasks.

All public functions take a SQLAlchemy ``Session`` and are synchronous —
tool handlers call them via ``asyncio.to_thread``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.chat import Conversation
from app.models.session_task import SessionTask

VALID_STATUSES = {
    "pending",
    "in_progress",
    "blocked",
    "verifying",
    "completed",
    "failed",
    "abandoned",
}
TERMINAL_STATUSES = {"completed", "abandoned"}


def _next_task_id(db: Session, session_id: str) -> int:
    current_max = (
        db.query(func.max(SessionTask.task_id))
        .filter(SessionTask.session_id == session_id)
        .scalar()
    )
    return (current_max or 0) + 1


def _row_to_dict(row: SessionTask) -> dict[str, Any]:
    return {
        "task_id": row.task_id,
        "subject": row.subject,
        "description": row.description,
        "status": row.status,
        "parent_task_id": row.parent_task_id,
        "owner": row.owner,
        "blocked_by": list(row.blocked_by_json or []),
        "acceptance_criteria": row.acceptance_criteria or "",
        "evidence": list(row.evidence_json or []),
        "verification_status": row.verification_status,
        "verification_notes": row.verification_notes,
        "attempt_count": row.attempt_count,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def create_task(
    db: Session,
    session_id: str,
    subject: str,
    description: str = "",
    *,
    parent_task_id: int | None = None,
    owner: str | None = None,
    blocked_by: list[int] | None = None,
    acceptance_criteria: str = "",
) -> dict[str, Any]:
    conversation = (
        db.query(Conversation.id)
        .filter(
            Conversation.id == session_id,
        )
        .with_for_update()
        .one_or_none()
    )
    if conversation is None:
        return {"error": "session_not_found"}
    dependencies = list(dict.fromkeys(blocked_by or []))
    existing_ids = {
        value[0]
        for value in db.query(SessionTask.task_id)
        .filter(
            SessionTask.session_id == session_id,
        )
        .all()
    }
    missing = [task_id for task_id in dependencies if task_id not in existing_ids]
    if parent_task_id is not None and parent_task_id not in existing_ids:
        missing.append(parent_task_id)
    if missing:
        return {"error": "task_dependency_not_found", "task_ids": sorted(set(missing))}
    task_id = _next_task_id(db, session_id)
    row = SessionTask(
        session_id=session_id,
        task_id=task_id,
        subject=subject,
        description=description,
        status="pending",
        parent_task_id=parent_task_id,
        owner=owner,
        blocked_by_json=dependencies,
        acceptance_criteria=acceptance_criteria,
        evidence_json=[],
        verification_status="unverified",
        attempt_count=0,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _row_to_dict(row)


def update_task(
    db: Session,
    session_id: str,
    task_id: int,
    *,
    status: str | None = None,
    subject: str | None = None,
    description: str | None = None,
    owner: str | None = None,
    blocked_by: list[int] | None = None,
    acceptance_criteria: str | None = None,
    evidence: list[str] | None = None,
) -> dict[str, Any] | None:
    row = (
        db.query(SessionTask)
        .filter(
            SessionTask.session_id == session_id,
            SessionTask.task_id == task_id,
        )
        .with_for_update()
        .one_or_none()
    )
    if row is None:
        return None
    if status is not None and status not in VALID_STATUSES:
        return {
            "error": f"invalid status '{status}', must be one of {sorted(VALID_STATUSES)}"
        }
    dependencies = (
        list(dict.fromkeys(blocked_by))
        if blocked_by is not None
        else list(row.blocked_by_json or [])
    )
    if task_id in dependencies:
        return {"error": "task_cannot_block_itself", "task_id": task_id}
    rows = db.query(SessionTask).filter(SessionTask.session_id == session_id).all()
    by_id = {item.task_id: item for item in rows}
    missing = [dependency for dependency in dependencies if dependency not in by_id]
    if missing:
        return {"error": "task_dependency_not_found", "task_ids": missing}

    def reaches(start: int, target: int, seen: set[int]) -> bool:
        if start == target:
            return True
        if start in seen:
            return False
        seen.add(start)
        dependency_row = by_id.get(start)
        return bool(dependency_row) and any(
            reaches(value, target, seen)
            for value in (dependency_row.blocked_by_json or [])
        )

    if any(reaches(dependency, task_id, set()) for dependency in dependencies):
        return {"error": "task_dependency_cycle", "task_id": task_id}

    target_status = status or row.status
    blockers = [
        dependency
        for dependency in dependencies
        if by_id[dependency].status != "completed"
    ]
    if target_status in {"in_progress", "verifying"} and blockers:
        return {"error": "task_blocked", "blocked_by": blockers}
    target_acceptance = (
        acceptance_criteria
        if acceptance_criteria is not None
        else row.acceptance_criteria
    )
    target_evidence = (
        evidence if evidence is not None else list(row.evidence_json or [])
    )
    if target_status == "verifying" and (
        not (target_acceptance or "").strip() or not target_evidence
    ):
        return {"error": "verification_requires_acceptance_and_evidence"}
    if target_status == "completed" and row.verification_status != "passed":
        return {"error": "task_requires_verification", "task_id": task_id}

    if subject is not None:
        row.subject = subject
    if description is not None:
        row.description = description
    if owner is not None:
        row.owner = owner
    if blocked_by is not None:
        row.blocked_by_json = dependencies
    if acceptance_criteria is not None:
        row.acceptance_criteria = acceptance_criteria
    if evidence is not None:
        row.evidence_json = evidence
        row.verification_status = "unverified"
        row.verification_notes = None
    if status is not None:
        if status == "in_progress" and row.status != "in_progress":
            row.attempt_count = (row.attempt_count or 0) + 1
        row.status = status
        if status == "verifying":
            row.verification_status = "pending"
    row.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(row)
    return _row_to_dict(row)


def record_verification(
    db: Session,
    session_id: str,
    task_id: int,
    *,
    verdict: str,
    notes: str,
) -> dict[str, Any] | None:
    row = (
        db.query(SessionTask)
        .filter(
            SessionTask.session_id == session_id,
            SessionTask.task_id == task_id,
        )
        .with_for_update()
        .one_or_none()
    )
    if row is None:
        return None
    mapping = {
        "PASS": ("completed", "passed"),
        "FAIL": ("in_progress", "failed"),
        "PARTIAL": ("blocked", "partial"),
    }
    if verdict not in mapping:
        raise ValueError(f"invalid verification verdict: {verdict}")
    row.status, row.verification_status = mapping[verdict]
    row.verification_notes = notes
    row.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(row)
    return _row_to_dict(row)


def get_task(
    db: Session,
    session_id: str,
    task_id: int,
) -> dict[str, Any] | None:
    row = (
        db.query(SessionTask)
        .filter(
            SessionTask.session_id == session_id,
            SessionTask.task_id == task_id,
        )
        .first()
    )
    return _row_to_dict(row) if row else None


def list_tasks(
    db: Session,
    session_id: str,
) -> list[dict[str, Any]]:
    rows = (
        db.query(SessionTask)
        .filter(SessionTask.session_id == session_id)
        .order_by(SessionTask.task_id)
        .all()
    )
    return [_row_to_dict(r) for r in rows]


def list_incomplete(db: Session, session_id: str) -> list[dict[str, Any]]:
    rows = (
        db.query(SessionTask)
        .filter(
            SessionTask.session_id == session_id,
            SessionTask.status.notin_(TERMINAL_STATUSES),
        )
        .order_by(SessionTask.task_id)
        .all()
    )
    return [_row_to_dict(r) for r in rows]
