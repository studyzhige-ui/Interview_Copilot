"""Read-only user projection of the optional plan for one Agent Turn.

Creation and revision stay inside the Agent runtime; exposing those commands
as model Tools or browser mutation endpoints would create a second task
manager.  The client only reads this projection for the fixed plan card.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.database import get_db
from app.models.conversation_turn import ConversationTurn
from app.models.user import User
from app.schemas.agent_task import AgentTaskView
from app.services.chat.agent_task_service import (
    AgentTaskNotFoundError,
    AgentTaskOwnershipError,
    get_agent_task,
)


router = APIRouter(tags=["chat"])


@router.get(
    "/chat/{session_id}/turns/{turn_id}/agent-task",
    response_model=AgentTaskView | None,
)
def read_agent_task(
    session_id: str,
    turn_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AgentTaskView | None:
    """Return ``null`` when this simple Turn has no AgentTask."""

    turn_scope = (
        db.query(ConversationTurn.conversation_id)
        .filter(ConversationTurn.id == turn_id)
        .scalar()
    )
    if turn_scope is None or turn_scope != session_id:
        raise HTTPException(status_code=404, detail="Conversation turn not found")
    try:
        task = get_agent_task(db, turn_id=turn_id, user_id=current_user.id)
    except (AgentTaskNotFoundError, AgentTaskOwnershipError) as exc:
        raise HTTPException(
            status_code=404, detail="Conversation turn not found"
        ) from exc
    return AgentTaskView.model_validate(task) if task is not None else None


__all__ = ["router"]
