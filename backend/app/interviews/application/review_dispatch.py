"""Durable review admission precedes broker publication.

The broker may accept a task and lose its acknowledgement. A failed admission is
fenced, not assumed unsent. Success never rewinds a worker's completed status.
"""

from __future__ import annotations
import uuid
from dataclasses import dataclass
from app.db.types import utc_now
from app.interviews.application.review_fence import lock_record


@dataclass(frozen=True)
class ReviewDispatchReceipt:
    id: str


def dispatch_review_command(
    db, record_id, *, sender, rollback_status, error_message, **kwargs
):
    row = lock_record(db, record_id)
    if row is None:
        raise ValueError("interview_record_missing")
    row.review_generation += 1
    generation = row.review_generation
    task_id = str(uuid.uuid4())
    row.celery_task_id = task_id
    row.status = "processing_review" if row.source == "mock" else "pending"
    row.error_message = None
    row.updated_at = utc_now()
    db.commit()
    try:
        task = sender(
            record_id, task_id=task_id, review_generation=generation, **kwargs
        )
        if task.id != task_id:
            raise RuntimeError("review_dispatch_identity_mismatch")
    except Exception:
        db.rollback()
        current = lock_record(db, record_id)
        if current is not None and current.review_generation == generation:
            if (
                current.status in {"review_ready", "completed"}
                and current.analysis_json
            ):
                # The worker's committed result is stronger evidence than the
                # broker's missing reply. Never rewind known success.
                db.rollback()
                return ReviewDispatchReceipt(task_id)
            current.review_generation += 1
            current.status = rollback_status
            current.error_message = error_message
            current.updated_at = utc_now()
            db.commit()
        raise
    # Do not write pending after send_task: a fast worker can already be done.
    return ReviewDispatchReceipt(task_id)
