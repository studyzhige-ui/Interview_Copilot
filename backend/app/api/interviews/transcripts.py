"""Thin authenticated boundary for source evidence and correction receipts."""

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from app.core.rate_limit import RATE_EXPENSIVE, limiter
from app.core.bounded_work import WorkCapacityExceeded
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
    TranscriptPlaybackRequest,
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


@router.post("/interview-records/{record_id}/transcript/playback")
@limiter.limit(RATE_EXPENSIVE)
async def transcript_playback(
    request: Request,
    record_id: str,
    body: TranscriptPlaybackRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.interviews.application.transcript_playback import create_playback
    from app.media.application.workers import pool

    # get_current_user used the same cached get_db dependency. Release that
    # authentication transaction too, not only the application's source reads.
    user_pk = int(user.id)
    db.close()
    with command_errors():
        try:
            selection, content = await pool("probe").run(
                create_playback, record_id=record_id, user_pk=user_pk, command=body
            )
        except WorkCapacityExceeded as exc:
            raise HTTPException(
                status_code=429, detail="回放任务繁忙，请稍后重试"
            ) from exc
    return Response(
        content=content,
        media_type="audio/wav",
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "X-Transcript-ID": selection.transcript_id,
            "X-Audio-Source-SHA256": selection.sha256,
        },
    )
