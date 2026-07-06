"""Zombie-state sweeper (light queue).

If the broker loses a dispatched analysis message outright (e.g. Redis
restarts without persistence after the API committed status='pending'),
the record sits in an intermediate state forever: Celery's retry/ack
machinery only protects messages it still has. Nothing else re-examines
those rows — this beat task is the terminal-state guarantee of last
resort.

Threshold rationale: a legitimate run can be alive for a long time —
time_limit=1800s per attempt × up to 3 retries + backoff, and
``updated_at`` only moves on status transitions (a 30-minute
transcription stage writes nothing). 2 hours comfortably exceeds the
worst legitimate case, and a record whose message is truly lost never
moves again anyway, so the extra latency only delays the *error
message*, not any work.
"""
import logging
from datetime import datetime, timedelta

from app.db.database import SessionLocal
from app.models.interview_record import InterviewRecord
from app.worker.celery_app import celery_app

logger = logging.getLogger(__name__)

# Upload-path in-flight states + the mock review in-flight state.
_STALE_SWEEP_STATES = (
    "pending", "transcribing", "extracting", "analyzing", "processing_review",
)
_STALE_AFTER = timedelta(hours=2)


@celery_app.task(
    bind=True,
    name="tasks.sweep_stale_interview_records",
    time_limit=60,
    soft_time_limit=50,
)
def sweep_stale_interview_records(self):
    """Move records stuck >2h in an in-flight state to a terminal one.

    Idempotent and safe against races with a live worker: the analysis
    task's own status writes will simply overwrite ours if (against all
    odds) it is still running — the orchestrator writes completed/
    review_ready unconditionally at the end of a successful run.
    """
    cutoff = datetime.utcnow() - _STALE_AFTER
    swept = 0
    with SessionLocal() as db:
        rows = (
            db.query(InterviewRecord)
            .filter(
                InterviewRecord.status.in_(_STALE_SWEEP_STATES),
                InterviewRecord.updated_at < cutoff,
            )
            .all()
        )
        for rec in rows:
            terminal = "review_failed" if rec.source == "mock" else "failed"
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
