from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.types import utc_now
from app.models.agent_execution import AgentCheckpoint, AgentToolCall
from app.services.chat import session_task_service


def save_checkpoint(
    db: Session,
    session_id: str,
    *,
    summary: str,
    current_task_id: int | None,
    next_action: str,
) -> dict:
    if (
        current_task_id is not None
        and session_task_service.get_task(
            db,
            session_id,
            current_task_id,
        )
        is None
    ):
        raise ValueError(f"task {current_task_id} not found")
    row = db.get(AgentCheckpoint, session_id)
    if row is None:
        row = AgentCheckpoint(
            session_id=session_id, summary=summary, next_action=next_action
        )
        db.add(row)
    row.summary = summary
    row.current_task_id = current_task_id
    row.next_action = next_action
    row.updated_at = utc_now()
    db.commit()
    db.refresh(row)
    return checkpoint_payload(row)


def checkpoint_payload(row: AgentCheckpoint) -> dict:
    return {
        "summary": row.summary,
        "current_task_id": row.current_task_id,
        "next_action": row.next_action,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def load_recovery_state(
    db: Session, session_id: str, *, journal_limit: int = 12
) -> dict:
    checkpoint = db.get(AgentCheckpoint, session_id)
    events = (
        db.query(AgentToolCall)
        .filter(
            AgentToolCall.session_id == session_id,
        )
        .order_by(AgentToolCall.id.desc())
        .limit(journal_limit)
        .all()
    )
    return {
        "checkpoint": checkpoint_payload(checkpoint) if checkpoint else None,
        "tasks": session_task_service.list_incomplete(db, session_id),
        "recent_events": [
            {
                "tool": event.tool_name,
                "payload": {
                    "arguments": event.arguments_json,
                    "result": event.result_json,
                    "status": event.status,
                    "error": event.error,
                },
                "created_at": event.started_at.isoformat()
                if event.started_at
                else None,
            }
            for event in reversed(events)
        ],
    }
