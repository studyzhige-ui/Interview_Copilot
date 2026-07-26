"""Nightly memory-consolidation tasks for the light worker."""

import logging

from app.worker.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name="tasks.scan_and_dream_batch",
    time_limit=900,
    soft_time_limit=840,
)
def scan_and_dream_batch_task(self):
    """Run the nightly memory-consolidation batch.

    Wakes up via Celery Beat at 03:30 Asia/Shanghai. Walks every user
    that passes the per-user gates (>=24h cursor + activity volume)
    and dreams each user's silent records, then bumps the user's
    cursor. See ``dreaming_worker`` module docstring for the full gate
    table.

    Per-user work is dispatched as a dedicated ``dream_for_user_task``
    so a slow LLM call on one user doesn't block another, and Celery's
    soft_time_limit / retry policy applies per-user (not per-batch).
    """
    from app.services.memory.dreaming_worker import select_dreamable_users

    users = select_dreamable_users(limit=200)
    dispatched = 0
    for uid in users:
        try:
            dream_for_user_task.delay(uid)
            dispatched += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "scan_and_dream_batch: dispatch failed for user=%s: %s",
                uid,
                exc,
            )
    logger.info(
        "scan_and_dream_batch: dispatched %d dream tasks (of %d eligible users)",
        dispatched,
        len(users),
    )
    return {"dispatched": dispatched, "users": len(users)}


@celery_app.task(
    bind=True,
    name="tasks.dream_for_user",
    autoretry_for=(ConnectionError, TimeoutError, OSError),
    retry_backoff=True,
    retry_backoff_max=120,
    retry_jitter=True,
    max_retries=2,
    acks_late=True,
    time_limit=1200,
    soft_time_limit=1140,
)
def dream_for_user_task(self, user_id: str):
    """Enqueue a persistent dreaming job per silent record + bump the user cursor.

    Per-record dreaming runs as an ``extract_memory_dreaming`` outbox job
    (drained every minute, retried with backoff, idempotent via the record's
    ``last_dreamed_at`` re-check), so a slow/failing LLM call on one record
    never blocks the others and survives a worker crash. The user cursor is
    bumped to scan-start right after enqueuing — the per-record cursor advances
    atomically inside each job. Pinning to scan-start (not "now") means any chat
    message arriving during processing isn't dropped from the next nightly's
    gate-3 count (review found this as M1).
    """
    from datetime import datetime
    from app.core.user_identity import resolve_user_pk
    from app.db.database import SessionLocal
    from app.services.memory import extraction_jobs
    from app.services.memory.dreaming_worker import (
        bump_user_last_dreamed_at,
        select_records_for_user,
    )

    scan_started_at = datetime.utcnow()
    records = select_records_for_user(user_id, limit=50)
    enqueued = 0
    db = SessionLocal()
    try:
        user_pk = resolve_user_pk(db, user_id)
        if user_pk is not None:
            for rec in records:
                if (
                    extraction_jobs.enqueue_dreaming(
                        db, user_pk=user_pk, record_id=rec.id
                    )
                    is not None
                ):
                    enqueued += 1
            db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    # Bump cursor unconditionally — gate 3 (volume) guards against firing this
    # task in the first place; the consolidation pass for this user has been
    # scheduled, so the next nightly waits for new activity before firing again.
    bump_user_last_dreamed_at(user_id, at=scan_started_at)
    logger.info(
        "dream_for_user: user=%s candidates=%d enqueued=%d",
        user_id,
        len(records),
        enqueued,
    )
    return {"user_id": user_id, "candidates": len(records), "enqueued": enqueued}
