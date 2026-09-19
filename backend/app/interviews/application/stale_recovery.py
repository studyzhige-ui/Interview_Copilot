"""Bounded recovery of quiet upload/review records; never advances a live interview."""

from datetime import timedelta
from sqlalchemy import and_, or_
from app.models.interview_record import InterviewRecord
from .interview_record_service import (
    STATUS_ANALYZING,
    STATUS_EXTRACTING,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_PROCESSING_REVIEW,
    STATUS_REVIEW_FAILED,
    STATUS_TRANSCRIBING,
)


def expire_stale_reviews(db, *, now, limit=500) -> int:
    # Upload hard deadline and retries can be long; review publishes progress
    # after each batch. Select and lock current rows instead of using a stale
    # worker-side projection. Already terminal and live interview rows excluded.
    rows = (
        db.query(InterviewRecord)
        .filter(
            or_(
                and_(
                    InterviewRecord.status.in_(
                        (
                            STATUS_PENDING,
                            STATUS_TRANSCRIBING,
                            STATUS_EXTRACTING,
                            STATUS_ANALYZING,
                        )
                    ),
                    InterviewRecord.updated_at < now - timedelta(hours=2),
                ),
                and_(
                    InterviewRecord.status == STATUS_PROCESSING_REVIEW,
                    InterviewRecord.updated_at < now - timedelta(minutes=30),
                ),
            )
        )
        .order_by(InterviewRecord.updated_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
        .populate_existing()
        .all()
    )
    for row in rows:
        row.status = STATUS_REVIEW_FAILED if row.source == "mock" else STATUS_FAILED
        row.error_message = "分析长时间无进展（任务可能已丢失），请重试。"
        db.add(row)
    return len(rows)
