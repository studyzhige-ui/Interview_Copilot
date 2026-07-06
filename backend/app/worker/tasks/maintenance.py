"""Beat-driven DB sweepers (light queue) — the terminal-state guarantee of
last resort for rows nothing else re-examines.

* ``sweep_stale_interview_records`` — interview records stuck in an
  in-flight status (lost broker message, dead worker).
* ``sweep_orphan_file_assets`` — presigned uploads whose client vanished
  before confirm/consume.
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

# Threshold rationale — two tiers, keyed off ``updated_at`` (bumped by every
# status transition AND every per-question progress increment):
#
# * Upload pipeline (pending/transcribing/extracting/analyzing): a legitimate
#   run can be quiet for a long stretch — transcription writes nothing for up
#   to one attempt (time_limit=1800s), × up to 3 retries + backoff. 2 hours
#   comfortably exceeds the worst case.
# * Mock review (processing_review): no silent stage — the orchestrator bumps
#   the counter per analyzed batch, so a 30-minute-quiet review is dead.
#   Sweeping it faster matters because the UI's retry card only appears once
#   the record reaches review_failed.
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


# A pending_upload row whose client never PUT/confirmed is an orphan: nothing
# will ever look at it again, but its presigned URL may have been used, so an
# unreferenced blob can sit in MinIO forever. One day is far beyond any
# legitimate upload-then-confirm window.
_ORPHAN_ASSET_STALE_AFTER = timedelta(hours=24)


@celery_app.task(
    bind=True,
    name="tasks.sweep_orphan_file_assets",
    time_limit=120,
    soft_time_limit=100,
)
def sweep_orphan_file_assets(self):
    """Daily orphan cleanup for the presigned upload flow (UP-3).

    * ``pending_upload`` > 24h: enqueue a blob delete (the client may have
      PUT bytes without ever confirming) and mark the row ``deleted``.
    * ``failed`` > 24h: cleanup was already enqueued by ``_fail_asset`` at
      failure time — just mark the row ``deleted`` for hygiene.
    """
    from app.models.file_asset import FileAsset
    from app.services.uploads.file_asset_service import (
        UPLOAD_STATUS_DELETED,
        UPLOAD_STATUS_FAILED,
        UPLOAD_STATUS_PENDING,
        enqueue_asset_blob_delete,
    )

    cutoff = datetime.utcnow() - _ORPHAN_ASSET_STALE_AFTER
    swept = 0
    with SessionLocal() as db:
        rows = (
            db.query(FileAsset)
            .filter(
                FileAsset.upload_status.in_((UPLOAD_STATUS_PENDING, UPLOAD_STATUS_FAILED)),
                FileAsset.updated_at < cutoff,
                FileAsset.deleted_at.is_(None),
            )
            .all()
        )
        for asset in rows:
            if asset.upload_status == UPLOAD_STATUS_PENDING:
                enqueue_asset_blob_delete(db, asset)
            asset.upload_status = UPLOAD_STATUS_DELETED
            asset.deleted_at = datetime.utcnow()
            asset.updated_at = datetime.utcnow()
            db.add(asset)
            swept += 1
        db.commit()
    if swept:
        logger.info("sweep_orphan_file_assets: swept %d asset(s)", swept)
    return {"swept": swept}
