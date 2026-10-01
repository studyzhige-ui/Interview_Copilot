"""Generation-bound upload and mock review tasks."""

import logging
from app.core.error_messages import humanize_error
from app.db.database import SessionLocal
from app.interviews.application.interview_record_service import interview_record_service
from app.interviews.application.review_fence import (
    ReviewSuperseded,
    lock_record,
    review_scope,
)
from app.task_queue.celery_app import celery_app

logger = logging.getLogger(__name__)
_TASK_OPTIONS = {
    "bind": True,
    "acks_late": True,
    "time_limit": 1800,
    "soft_time_limit": 1740,
    # A missing provider response can already be billed. Only explicit user
    # review admission or stage-specific known-safe recovery may resend it.
    "max_retries": 0,
}


@celery_app.task(name="tasks.process_interview_analysis", **_TASK_OPTIONS)
def process_interview_analysis(
    self, record_id: str, language: str = "zh", review_generation: int = 0
):
    return _run_interview_pipeline(
        self, record_id, language=language, review_generation=review_generation
    )


@celery_app.task(name="tasks.process_mock_interview_review", **_TASK_OPTIONS)
def process_mock_interview_review(self, record_id: str, review_generation: int = 0):
    return _run_interview_pipeline(
        self, record_id, language="zh", review_generation=review_generation
    )


def _run_interview_pipeline(
    self, record_id: str, *, language: str, review_generation: int = 0
):
    from app.interviews.application.analysis_orchestrator import analysis_orchestrator
    from app.usage.runtime import scope

    with review_scope(record_id, review_generation):
        try:
            with SessionLocal() as db:
                row = lock_record(db, record_id)
                if row is None:
                    return {"status": "missing", "record_id": record_id}
                if row.celery_task_id and row.celery_task_id != self.request.id:
                    return {"status": "superseded", "record_id": record_id}
                if row.status in (
                    "completed",
                    "review_ready",
                    "failed",
                    "review_failed",
                ):
                    return {
                        "status": "skipped",
                        "record_id": record_id,
                        "reason": "already_terminal",
                    }
                owner_pk = row.user_id
                fail_status = "review_failed" if row.source == "mock" else "failed"
                row.celery_task_id = self.request.id
                db.commit()
            with scope(owner_pk, f"interview:{record_id}:{self.request.id}"):
                return analysis_orchestrator.run(
                    record_id, language=language, review_generation=review_generation
                )
        except ReviewSuperseded:
            return {"status": "superseded", "record_id": record_id}
        except Exception as exc:
            try:
                interview_record_service.set_status(
                    record_id,
                    locals().get("fail_status", "failed"),
                    error_message=f"分析失败：{humanize_error(exc)}"[:500],
                )
            except ReviewSuperseded:
                return {"status": "superseded", "record_id": record_id}
            except Exception:
                logger.exception("Could not persist review failure for %s", record_id)
            raise
