"""Interview-analysis pipeline task (heavy queue — needs Whisper)."""
import logging

from app.core.error_messages import humanize_error
from app.db.database import SessionLocal
from app.worker.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name="tasks.process_interview_analysis",
    autoretry_for=(ConnectionError, TimeoutError, OSError),
    retry_backoff=True,
    retry_backoff_max=120,
    retry_jitter=True,          # avoid thundering herd on transient outages
    max_retries=3,
    # Reliability: acks_late + time bounds. Keep both ceilings well below
    # the broker visibility_timeout (3700s) so a hung task is reclaimed and
    # re-delivered before Redis would re-deliver on its own.
    acks_late=True,
    # 30 min budgets a GPU/cloud-ASR deployment. On CPU-only WhisperX a
    # 60-minute recording can exceed this — raise via env-specific config
    # if you deploy transcription on CPU.
    time_limit=1800,            # 30 min hard
    soft_time_limit=1740,       # 1 min before hard kill
)
def process_interview_analysis(self, record_id: str, language: str = "zh"):
    """Run the unified analysis pipeline for an InterviewRecord.

    The orchestrator handles both source='upload' (audio → ASR → analysis)
    and source='mock' (composed transcript from QA buffer → analysis).

    ``language`` is a WhisperX language hint:
      * ``"zh"`` / ``"en"``: force the decoder to that language. Faster
        + much more accurate than auto-detect on clean monolingual audio.
      * ``"auto"``: let Whisper detect per clip. Use only for genuinely
        mixed-language recordings.
    Default ``"zh"`` matches the API's default and the UI default.

    Idempotent under retry: if the record is already in a terminal state
    (``completed``/``failed`` from a prior attempt that succeeded but whose
    ack we lost), short-circuit instead of re-running the entire pipeline.
    """
    from app.models.interview_record import InterviewRecord
    from app.services.interview.analysis_orchestrator import analysis_orchestrator
    from app.services.interview.interview_record_service import interview_record_service

    # ── Idempotency gate ────────────────────────────────────────────────
    db = SessionLocal()
    try:
        row = db.query(InterviewRecord).filter(InterviewRecord.id == record_id).first()
        source = row.source if row is not None else "upload"
        if row is not None and row.status in ("completed", "review_ready"):
            logger.info(
                "[Task %s] InterviewRecord %s already terminal (%s); skipping re-run.",
                self.request.id, record_id, row.status,
            )
            return {"status": "skipped", "record_id": record_id, "reason": "already_terminal"}
    finally:
        db.close()

    is_mock = source == "mock"

    # Stash the celery task id so the cancel endpoint can revoke us. The
    # in-flight status differs by source (mock → processing_review, so the
    # record stays out of the review list while the review runs).
    try:
        interview_record_service.set_status(
            record_id,
            "processing_review" if is_mock else "pending",
            celery_task_id=self.request.id,
        )
    except Exception:  # noqa: BLE001
        logger.warning("Failed to stash celery_task_id on %s", record_id)

    try:
        return analysis_orchestrator.run(record_id, language=language)
    except Exception as exc:  # noqa: BLE001
        # The orchestrator itself catches and writes STATUS_FAILED before
        # re-raising (see analysis_orchestrator.py:126), so in the common
        # case the record is already in the right state. The block below
        # is a *belt-and-braces* safety net:
        #
        #   1. If we're on the LAST retry attempt (Celery would discard
        #      the task next), make sure the record actually carries a
        #      "max retries exhausted" message so the user UI doesn't
        #      show a transient error from one of the middle attempts.
        #   2. If the orchestrator never got far enough to set FAILED
        #      (e.g. it crashed before its own try/except), force the
        #      status to FAILED here so the record never gets stuck in
        #      an intermediate state forever.
        retries_left = max(0, (self.max_retries or 0) - self.request.retries)
        is_final_attempt = retries_left == 0
        try:
            if is_final_attempt:
                # Humanize the user-facing message — the raw exception
                # (incl. the retry count) is already in the worker log above.
                interview_record_service.set_status(
                    record_id,
                    "review_failed" if is_mock else "failed",
                    error_message=f"分析失败：{humanize_error(exc)}"[:500],
                )
            else:
                # Mid-retry: only force-write if status is still in an
                # intermediate state (orchestrator didn't reach its
                # except branch). Don't overwrite a "completed" set by
                # a parallel success.
                row = SessionLocal()
                try:
                    rec = (
                        row.query(InterviewRecord)
                        .filter(InterviewRecord.id == record_id)
                        .first()
                    )
                    if rec is not None and rec.status not in {
                        "completed", "failed", "review_ready", "review_failed",
                    }:
                        interview_record_service.set_status(
                            record_id,
                            "review_failed" if is_mock else "failed",
                            error_message=f"分析失败：{humanize_error(exc)}"[:500],
                        )
                finally:
                    row.close()
        except Exception as recovery_exc:  # noqa: BLE001
            # Never let the recovery path mask the original error.
            logger.error(
                "Failed to mark interview %s as failed after task crash: %s "
                "(original error follows)",
                record_id, recovery_exc,
            )

        logger.error(
            "Interview analysis task failed for %s (attempt %d/%d): %s",
            record_id, self.request.retries + 1, self.max_retries + 1, exc,
        )
        raise
