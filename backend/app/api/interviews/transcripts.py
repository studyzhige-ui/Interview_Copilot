"""Thin authenticated boundary for source evidence and correction receipts."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.api.command_errors import command_errors
from app.core.security import get_current_user
from app.db.database import get_db
from app.models.user import User
from app.schemas.transcript_correction import (
    TranscriptCorrectionRequest,
    TranscriptCorrectionReceipt,
    TranscriptHistoryPage,
    TranscriptPage,
)
from app.interviews.application import transcript_corrections as service

router = APIRouter()


@router.get("/interview-records/{record_id}/transcript", response_model=TranscriptPage)
def transcript_page(
    record_id: str,
    transcript_id: str | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    with command_errors():
        return service.get_page(
            db,
            record_id=record_id,
            user_pk=user.id,
            transcript_id=transcript_id,
            offset=offset,
            limit=limit,
        )


@router.post(
    "/interview-records/{record_id}/transcript/corrections",
    response_model=TranscriptCorrectionReceipt,
)
def correct_transcript(
    record_id: str,
    body: TranscriptCorrectionRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    with command_errors():
        return service.correct_transcript(
            db, record_id=record_id, user_pk=user.id, command=body
        )


@router.get(
    "/interview-records/{record_id}/transcript/corrections",
    response_model=TranscriptHistoryPage,
)
def correction_history(
    record_id: str,
    before: str | None = None,
    limit: int = Query(20, ge=1, le=50),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    with command_errors():
        return service.history(
            db, record_id=record_id, user_pk=user.id, before=before, limit=limit
        )


@router.get(
    "/interview-records/{record_id}/transcript/corrections/{request_id}",
    response_model=TranscriptCorrectionReceipt,
)
def correction_receipt(
    record_id: str,
    request_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    with command_errors():
        return service.get_receipt(
            db, record_id=record_id, user_pk=user.id, request_id=request_id
        )
