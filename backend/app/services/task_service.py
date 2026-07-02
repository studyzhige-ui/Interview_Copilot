"""Synchronous CRUD layer for session-scoped tasks.

All public functions take a SQLAlchemy ``Session`` and are synchronous —
tool handlers call them via ``asyncio.to_thread``.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.session_task import SessionTask

VALID_STATUSES = {"pending", "in_progress", "completed"}


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
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def create_task(
    db: Session,
    session_id: str,
    subject: str,
    description: str = "",
) -> dict[str, Any]:
    task_id = _next_task_id(db, session_id)
    row = SessionTask(
        session_id=session_id,
        task_id=task_id,
        subject=subject,
        description=description,
        status="pending",
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
) -> dict[str, Any] | None:
    row = (
        db.query(SessionTask)
        .filter(
            SessionTask.session_id == session_id,
            SessionTask.task_id == task_id,
        )
        .first()
    )
    if row is None:
        return None
    if status is not None:
        if status not in VALID_STATUSES:
            return {"error": f"invalid status '{status}', must be one of {sorted(VALID_STATUSES)}"}
        row.status = status
    if subject is not None:
        row.subject = subject
    if description is not None:
        row.description = description
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


def delete_task(
    db: Session,
    session_id: str,
    task_id: int,
) -> bool:
    count = (
        db.query(SessionTask)
        .filter(
            SessionTask.session_id == session_id,
            SessionTask.task_id == task_id,
        )
        .delete()
    )
    db.commit()
    return count > 0


def count_incomplete(db: Session, session_id: str) -> int:
    return (
        db.query(func.count(SessionTask.id))
        .filter(
            SessionTask.session_id == session_id,
            SessionTask.status != "completed",
        )
        .scalar()
    ) or 0


def list_incomplete(db: Session, session_id: str) -> list[dict[str, Any]]:
    rows = (
        db.query(SessionTask)
        .filter(
            SessionTask.session_id == session_id,
            SessionTask.status != "completed",
        )
        .order_by(SessionTask.task_id)
        .all()
    )
    return [_row_to_dict(r) for r in rows]
