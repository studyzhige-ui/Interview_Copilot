"""Authenticated product boundary for agenda, reminders, funnel, and Offer analysis."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.database import get_db
from app.models.user import User
from app.schemas.career_insights import (
    FunnelAnalysis,
    NegotiationDraftRequest,
    NegotiationDraftResponse,
    NextActionAgenda,
    NotificationPreferenceUpdate,
    NotificationPreferenceView,
    OfferAnalysisRequest,
    OfferAnalysisResponse,
    ReminderDismiss,
)
from app.schemas.job_opportunity import NextActionView
from app.services import (
    funnel_analysis_service,
    offer_analysis_service,
    reminder_service,
)

router = APIRouter(prefix="/career-insights", tags=["career-insights"])


@router.get("/next-actions/agenda", response_model=NextActionAgenda)
def action_agenda(
    at: datetime | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return reminder_service.build_next_action_agenda(db, user_pk=current_user.id, at=at)


@router.get("/notification-preference", response_model=NotificationPreferenceView)
def get_notification_preference(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return reminder_service.notification_preference(db, user_pk=current_user.id)


@router.put("/notification-preference", response_model=NotificationPreferenceView)
def put_notification_preference(
    body: NotificationPreferenceUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        row = reminder_service.update_notification_preference(
            db, user_pk=current_user.id, command=body
        )
        db.commit()
        return row
    except reminder_service.ReminderConflictError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except reminder_service.ReminderError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/reminders/inbox", response_model=list[NextActionView])
def reminder_inbox(
    limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return reminder_service.list_reminder_inbox(
        db, user_pk=current_user.id, limit=limit
    )


@router.post("/reminders/{action_id}/dismiss", response_model=NextActionView)
def dismiss_reminder(
    action_id: str,
    body: ReminderDismiss,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        row = reminder_service.dismiss_reminder(
            db,
            user_pk=current_user.id,
            action_id=action_id,
            expected_version=body.expected_version,
        )
        db.commit()
        return row
    except reminder_service.ReminderNotFoundError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail="NextAction not found") from exc
    except reminder_service.ReminderConflictError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/funnel", response_model=FunnelAnalysis)
def funnel_analysis(
    direction_id: str | None = None,
    submitted_artifact_version_id: str | None = None,
    channel: str | None = None,
    occurred_from: datetime | None = None,
    occurred_to: datetime | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return funnel_analysis_service.analyze_funnel(
        db,
        user_pk=current_user.id,
        direction_id=direction_id,
        submitted_artifact_version_id=submitted_artifact_version_id,
        channel=channel,
        occurred_from=occurred_from,
        occurred_to=occurred_to,
    )


@router.post("/offers/compare", response_model=OfferAnalysisResponse)
def compare_offers(
    body: OfferAnalysisRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        result = offer_analysis_service.compare_offers(
            db, user_pk=current_user.id, command=body
        )
        db.commit()
        return result
    except offer_analysis_service.OfferAnalysisConflictError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except offer_analysis_service.OfferAnalysisNotFoundError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail="Offer not found") from exc
    except offer_analysis_service.OfferAnalysisError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/offers/{offer_id}/negotiation-draft",
    response_model=NegotiationDraftResponse,
)
def negotiation_draft(
    offer_id: str,
    body: NegotiationDraftRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        result = offer_analysis_service.build_negotiation_draft(
            db,
            user_pk=current_user.id,
            offer_id=offer_id,
            command=body,
        )
        db.commit()
        return result
    except offer_analysis_service.OfferAnalysisConflictError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except offer_analysis_service.OfferAnalysisNotFoundError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail="Offer not found") from exc
    except offer_analysis_service.OfferAnalysisError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc


__all__ = ["router"]
