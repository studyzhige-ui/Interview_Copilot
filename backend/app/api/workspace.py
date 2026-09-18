"""User-scoped home projection. No onboarding flags or duplicate task state."""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.database import get_db
from app.models.artifact import Artifact
from app.models.chat import Conversation
from app.models.conversation_turn import ConversationTurn
from app.models.job_opportunity import JobOpportunity, NextAction
from app.models.user import User

router = APIRouter(prefix="/workspace", tags=["workspace"])


class RecentWork(BaseModel):
    session_id: str
    title: str
    status: Literal["not_started", "pending", "running", "waiting", "completed", "blocked", "failed", "cancelled", "unknown"]
    updated_at: datetime | None


class WorkspaceOverview(BaseModel):
    has_resume: bool
    active_opportunities: int
    open_actions: int
    recent_work: list[RecentWork]


@router.get("", response_model=WorkspaceOverview)
def overview(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Read canonical owners, including durable turn status across reloads."""
    user_id = current_user.id
    sessions = db.query(Conversation).filter(
        Conversation.user_id == user_id, Conversation.type == "general", Conversation.archived_at.is_(None),
    ).order_by(Conversation.updated_at.desc(), Conversation.id).limit(5).all()
    # One bounded latest-turn lookup per visible session; an older failed turn
    # must never make a later successful conversation look broken.
    recent = []
    statuses = {"pending", "running", "waiting", "completed", "blocked", "failed", "cancelled"}
    for session in sessions:
        turn = db.query(ConversationTurn).filter(
            ConversationTurn.conversation_id == session.id,
            ConversationTurn.user_id == user_id,
        ).order_by(ConversationTurn.created_at.desc(), ConversationTurn.id.desc()).first()
        recent.append(RecentWork(
            session_id=session.id,
            title=session.title or "未命名协作",
            status=(turn.status if turn.status in statuses else "unknown") if turn else "not_started",
            updated_at=session.updated_at,
        ))
    return WorkspaceOverview(
        has_resume=db.query(Artifact.id).filter(
            Artifact.user_id == user_id, Artifact.kind == "resume", Artifact.archived_at.is_(None),
        ).first() is not None,
        active_opportunities=db.query(JobOpportunity).filter(
            JobOpportunity.user_id == user_id, JobOpportunity.archived_at.is_(None),
            JobOpportunity.outcome.is_(None),
        ).count(),
        open_actions=db.query(NextAction).filter(
            NextAction.user_id == user_id, NextAction.status.in_(["suggested", "planned"]),
        ).count(),
        recent_work=recent,
    )
