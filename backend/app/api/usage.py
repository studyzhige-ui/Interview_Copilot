"""Read-only account consumption API. No refund/retry/price mutation endpoint."""

from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.core.security import get_current_user
from app.db.database import get_db
from app.models.user import User
from app.usage import queries, service

router = APIRouter(prefix="/usage", tags=["usage"])


@router.get("")
def account_usage(
    day: date | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from datetime import datetime, UTC

    return queries.wire(
        service.usage_view(
            db,
            user_id=current_user.id,
            now=datetime.combine(day, datetime.min.time(), tzinfo=UTC) if day else None,
        )
    )


@router.get("/receipts")
def usage_receipts(
    day: date | None = None,
    before: str | None = Query(None, min_length=64, max_length=64),
    limit: int = Query(50, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return queries.wire(
            queries.history(
                db, user_id=current_user.id, day=day, before=before, limit=limit
            )
        )
    except ValueError as exc:
        raise HTTPException(400, detail={"code": "invalid_usage_cursor"}) from exc


@router.get("/receipts/{receipt_id}/corrections")
def usage_corrections(
    receipt_id: str,
    limit: int = Query(50, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return queries.wire(
        {
            "items": queries.corrections(
                db, user_id=current_user.id, receipt_id=receipt_id, limit=limit
            )
        }
    )
