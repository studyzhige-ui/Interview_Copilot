"""User-scoped home projection. No onboarding flags or duplicate task state."""

from datetime import datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select, func, and_
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.database import get_db
from app.models.artifact import Artifact
from app.models.chat import Conversation
from app.models.conversation_turn import ConversationTurn
from app.models.job_opportunity import JobOpportunity, JobOpportunityMerge, NextAction
from app.career.application.workspace import job_query
from app.models.interview_record import InterviewRecord
from app.models.user import User
from app.db.types import utc_now

router = APIRouter(prefix="/workspace", tags=["workspace"])


class RecentWork(BaseModel):
    session_id: str
    title: str
    status: Literal[
        "pending",
        "running",
        "waiting",
        "blocked",
        "failed",
    ]
    updated_at: datetime | None


class UpcomingInterview(BaseModel):
    id: str
    opportunity_id: str
    company_name: str
    job_title: str
    starts_at: datetime


class WorkspaceOverview(BaseModel):
    has_resume: bool
    active_opportunities: int
    open_actions: int
    recent_work: list[RecentWork]
    upcoming_interviews: list[UpcomingInterview]


@router.get("", response_model=WorkspaceOverview)
def overview(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db, scope="function"),
):
    """Read canonical owners, including durable turn status across reloads."""
    user_id = current_user.id
    latest_turn = (
        select(ConversationTurn.id)
        .where(
            ConversationTurn.conversation_id == Conversation.id,
            ConversationTurn.user_id == user_id,
        )
        .order_by(ConversationTurn.created_at.desc(), ConversationTurn.id.desc())
        .limit(1)
        .correlate(Conversation)
        .scalar_subquery()
    )
    sessions = (
        db.query(Conversation, ConversationTurn.status)
        .join(ConversationTurn, ConversationTurn.id == latest_turn)
        .filter(
            Conversation.user_id == user_id,
            Conversation.type == "general",
            Conversation.archived_at.is_(None),
            ConversationTurn.status.in_(
                ("pending", "running", "waiting", "blocked", "failed")
            ),
        )
        .order_by(Conversation.updated_at.desc(), Conversation.id)
        .limit(3)
        .all()
    )
    recent = [
        RecentWork(
            session_id=session.id,
            title=session.title or "未命名协作",
            status=turn_status,
            updated_at=session.updated_at,
        )
        for session, turn_status in sessions
    ]
    active_jobs = job_query(db, user_id).filter(
        JobOpportunity.archived_at.is_(None), JobOpportunity.outcome.is_(None)
    )
    interviews = (
        db.query(InterviewRecord, JobOpportunity)
        .outerjoin(
            JobOpportunityMerge,
            and_(
                JobOpportunityMerge.duplicate_opportunity_id
                == InterviewRecord.job_opportunity_id,
                JobOpportunityMerge.user_id == user_id,
                JobOpportunityMerge.status == "active",
            ),
        )
        .join(
            JobOpportunity,
            JobOpportunity.id
            == func.coalesce(
                JobOpportunityMerge.canonical_opportunity_id,
                InterviewRecord.job_opportunity_id,
            ),
        )
        .filter(
            InterviewRecord.user_id == user_id,
            InterviewRecord.source == "invitation",
            InterviewRecord.invitation_operation_id.is_not(None),
            InterviewRecord.scheduled_start_at >= utc_now(),
            InterviewRecord.scheduled_start_at <= utc_now() + timedelta(days=30),
            JobOpportunity.id.in_(active_jobs.with_entities(JobOpportunity.id)),
        )
        .order_by(InterviewRecord.scheduled_start_at, InterviewRecord.id)
        .limit(3)
        .all()
    )
    return WorkspaceOverview(
        has_resume=db.query(Artifact.id)
        .filter(
            Artifact.user_id == user_id,
            Artifact.kind == "resume",
            Artifact.archived_at.is_(None),
        )
        .first()
        is not None,
        active_opportunities=active_jobs.count(),
        open_actions=db.query(NextAction)
        .filter(
            NextAction.user_id == user_id,
            NextAction.status.in_(["suggested", "planned"]),
        )
        .count(),
        recent_work=recent,
        upcoming_interviews=[
            UpcomingInterview(
                id=record.id,
                opportunity_id=job.id,
                company_name=job.company_name,
                job_title=job.job_title,
                starts_at=record.scheduled_start_at,
            )
            for record, job in interviews
        ],
    )


@router.get("/model-usage", deprecated=True)
def primary_model_usage(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db, scope="function"),
):
    """Read-only, owner-scoped accounting; this is not a provider invoice."""
    from app.usage.service import usage_view

    return usage_view(db, user_id=current_user.id)
