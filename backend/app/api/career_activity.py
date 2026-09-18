"""Authenticated rebuildable Career OS activity projection."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.career.application.activity_projection import list_career_activity
from app.core.security import get_current_user
from app.db.database import get_db
from app.models.user import User
from app.schemas.career_activity import CareerActivityEvent


router = APIRouter(prefix="/career/activity", tags=["career-activity"])


@router.get("", response_model=list[CareerActivityEvent])
def read_career_activity(
    limit: int = Query(100, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[CareerActivityEvent]:
    return list_career_activity(db, user_pk=current_user.id, limit=limit)


__all__ = ["router"]
