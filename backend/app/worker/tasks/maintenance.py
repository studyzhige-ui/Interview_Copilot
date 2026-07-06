"""Zombie-state sweeper (light queue).

If the broker loses a dispatched analysis message outright (e.g. Redis
restarts without persistence after the API committed status='pending'),
the record sits in an intermediate state forever: Celery's retry/ack
machinery only protects messages it still has. Nothing else re-examines
those rows — this beat task is the terminal-state guarantee of last
resort.

Threshold rationale — two tiers, keyed off ``updated_at`` (bumped by
every status transition AND every per-question progress increment):

* Upload pipeline (pending/transcribing/extracting/analyzing): a
  legitimate run can be quiet for a long stretch — transcription writes
  nothing for up to one attempt (time_limit=1800s), × up to 3 retries +
  backoff. 2 hours comfortably exceeds the worst case.
* Mock review (processing_review): no silent stage — the orchestrator
  bumps the counter per analyzed batch, so a 30-minute-quiet review is
  dead. Sweeping it faster matters because the UI's retry card only
  appears once the record reaches review_failed.
"""
import logging
from datetime import datetime, timedelta

from sqlalchemy import and_, or_

from app.db.database import SessionLocal
from app.models.interview_record import InterviewRecord
from app.services.interview.interview_record_service import (
    STATUS_ANALYZING,
    STATUS_EXTRACTING,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_PROCESSING_REVIEW,
    STATUS_REVIEW_FAILED,
    STATUS_TRANSCRIBING,
)
from app.worker.celery_app import celery_app

logger = logging.getLogger(__name__)

_UPLOAD_SWEEP_STATES = (
    STATUS_PENDING, STATUS_TRANSCRIBING, STATUS_EXTRACTING, STATUS_ANALYZING,
)
_UPLOAD_STALE_AFTER = timedelta(hours=2)
_REVIEW_STALE_AFTER = timedelta(minutes=30)


@celery_app.task(
    bind=True,
    name="tasks.sweep_stale_interview_records",
    time_limit=60,
    soft_time_limit=50,
)
def sweep_stale_interview_records(self):
    """Move records stuck in an in-flight state to a terminal one.

    Idempotent and safe against races with a live worker: the analysis
    task's own status writes will simply overwrite ours if (against all
    odds) it is still running — the orchestrator writes completed/
    review_ready unconditionally at the end of a successful run.
    """
    now = datetime.utcnow()
    swept = 0
    with SessionLocal() as db:
        rows = (
            db.query(InterviewRecord)
            .filter(
                or_(
                    and_(
                        InterviewRecord.status.in_(_UPLOAD_SWEEP_STATES),
                        InterviewRecord.updated_at < now - _UPLOAD_STALE_AFTER,
                    ),
                    and_(
                        InterviewRecord.status == STATUS_PROCESSING_REVIEW,
                        InterviewRecord.updated_at < now - _REVIEW_STALE_AFTER,
                    ),
                )
            )
            .all()
        )
        for rec in rows:
            terminal = STATUS_REVIEW_FAILED if rec.source == "mock" else STATUS_FAILED
            logger.warning(
                "sweeping stale interview record %s: %s (updated %s) -> %s",
                rec.id, rec.status, rec.updated_at, terminal,
            )
            rec.status = terminal
            rec.error_message = "分析长时间无进展（任务可能已丢失），请重试。"
            db.add(rec)
            swept += 1
        db.commit()
    if swept:
        logger.info("sweep_stale_interview_records: swept %d record(s)", swept)
    return {"swept": swept}
