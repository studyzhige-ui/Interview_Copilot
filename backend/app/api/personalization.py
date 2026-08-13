"""Explicit personalization commands; each lifetime keeps its real owner."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.database import get_db
from app.models.user import User
from app.schemas.personalization import (
    CopilotPreferenceUpdate,
    CopilotPreferenceView,
    ScopedGuidanceUpdate,
    ScopedGuidanceView,
)
from app.services import personalization_service


router = APIRouter(prefix="/personalization", tags=["personalization"])


def _run(db: Session, operation, *, commit: bool = False):
    try:
        result = operation()
        if commit:
            db.commit()
        return result
    except personalization_service.PersonalizationNotFoundError as exc:
        if commit:
            db.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except personalization_service.PersonalizationConflictError as exc:
        if commit:
            db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/copilot-preference", response_model=CopilotPreferenceView)
def get_copilot_preference(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return personalization_service.get_copilot_preference(db, user_pk=current_user.id)


@router.put("/copilot-preference", response_model=CopilotPreferenceView)
def put_copilot_preference(
    body: CopilotPreferenceUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _run(
        db,
        lambda: personalization_service.replace_copilot_preference(
            db,
            user_pk=current_user.id,
            command=body,
        ),
        commit=True,
    )


@router.get(
    "/conversations/{conversation_id}/guidance",
    response_model=ScopedGuidanceView,
)
def get_conversation_guidance(
    conversation_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _run(
        db,
        lambda: personalization_service.get_conversation_guidance(
            db,
            user_pk=current_user.id,
            conversation_id=conversation_id,
        ),
    )


@router.put(
    "/conversations/{conversation_id}/guidance",
    response_model=ScopedGuidanceView,
)
def put_conversation_guidance(
    conversation_id: str,
    body: ScopedGuidanceUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _run(
        db,
        lambda: personalization_service.update_conversation_guidance(
            db,
            user_pk=current_user.id,
            conversation_id=conversation_id,
            command=body,
        ),
        commit=True,
    )


@router.get(
    "/interviews/{interview_record_id}/guidance",
    response_model=ScopedGuidanceView,
)
def get_debrief_guidance(
    interview_record_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _run(
        db,
        lambda: personalization_service.get_debrief_guidance(
            db,
            user_pk=current_user.id,
            interview_record_id=interview_record_id,
        ),
    )


@router.put(
    "/interviews/{interview_record_id}/guidance",
    response_model=ScopedGuidanceView,
)
def put_debrief_guidance(
    interview_record_id: str,
    body: ScopedGuidanceUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _run(
        db,
        lambda: personalization_service.update_debrief_guidance(
            db,
            user_pk=current_user.id,
            interview_record_id=interview_record_id,
            command=body,
        ),
        commit=True,
    )


__all__ = ["router"]
