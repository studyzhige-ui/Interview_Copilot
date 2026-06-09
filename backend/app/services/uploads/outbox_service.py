"""Enqueue + drain for ``outbox_jobs`` — reliable cross-system side effects.

Producers call :func:`enqueue_job` inside the same transaction as the business
write. A worker periodically calls :func:`run_due_outbox_jobs`, which claims a
batch of due jobs (lock-guarded), runs the registered handler, and marks each
succeeded / retry-with-backoff / dead.

This package registers the object-storage cleanup handlers
(``delete_object`` / ``cleanup_failed_upload``). Later packages register their
own job types (ingest / transcribe / memory) against the same table + runner.
"""
from __future__ import annotations

import json
import logging
import socket
from datetime import datetime, timedelta
from typing import Any, Callable

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.outbox_job import OutboxJob, generate_outbox_job_id

logger = logging.getLogger(__name__)

# job_type -> handler(db, job) -> None (raise to fail/retry).
_HANDLERS: dict[str, Callable[[Session, OutboxJob], None]] = {}

# Exponential backoff per attempt, capped. attempts=1 -> 60s, 2 -> 240s, ...
_BACKOFF_BASE_SECONDS = 60
_BACKOFF_CAP_SECONDS = 3600


def register_handler(job_type: str, handler: Callable[[Session, OutboxJob], None]) -> None:
    _HANDLERS[job_type] = handler


def enqueue_job(
    db: Session,
    *,
    user_pk: int,
    job_type: str,
    aggregate_type: str | None = None,
    aggregate_id: str | None = None,
    payload: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
    max_attempts: int = 5,
) -> OutboxJob | None:
    """Add a job in the caller's transaction (caller commits).

    Idempotent on ``(job_type, idempotency_key)``: a duplicate enqueue is a
    no-op (returns the existing job) rather than a second side effect.
    """
    if idempotency_key is not None:
        existing = (
            db.query(OutboxJob)
            .filter(
                OutboxJob.job_type == job_type,
                OutboxJob.idempotency_key == idempotency_key,
            )
            .first()
        )
        if existing is not None:
            return existing

    job = OutboxJob(
        id=generate_outbox_job_id(),
        user_id=user_pk,
        job_type=job_type,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        payload_json=json.dumps(payload, ensure_ascii=False) if payload else None,
        status="pending",
        attempts=0,
        max_attempts=max_attempts,
        next_run_at=datetime.utcnow(),
        idempotency_key=idempotency_key,
    )
    db.add(job)
    return job


def run_due_outbox_jobs(db: Session, *, limit: int = 50) -> int:
    """Claim and run up to ``limit`` due jobs. Returns the count processed.

    A claimed job is locked (``locked_by`` = host) so concurrent workers don't
    double-run it. Handlers are expected to be idempotent regardless.
    """
    worker_id = f"{socket.gethostname()}:{id(db)}"
    now = datetime.utcnow()
    # Atomic claim: lock a due batch with FOR UPDATE SKIP LOCKED and flip it to
    # ``running`` in ONE transaction, so two concurrent workers never grab the
    # same job. SKIP LOCKED is a no-op on sqlite (unit tests run single-
    # threaded), so we only request it on Postgres.
    query = (
        db.query(OutboxJob)
        .filter(
            or_(OutboxJob.status == "pending", OutboxJob.status == "failed"),
            OutboxJob.next_run_at <= now,
            OutboxJob.locked_at.is_(None),
        )
        .order_by(OutboxJob.next_run_at.asc())
        .limit(limit)
    )
    if db.get_bind().dialect.name == "postgresql":
        query = query.with_for_update(skip_locked=True)
    claimed = query.all()
    for job in claimed:
        job.status = "running"
        job.locked_at = datetime.utcnow()
        job.locked_by = worker_id
        db.add(job)
    db.commit()

    processed = 0
    for job in claimed:
        handler = _HANDLERS.get(job.job_type)
        try:
            if handler is None:
                raise RuntimeError(f"no handler registered for job_type={job.job_type}")
            handler(db, job)
            job.status = "succeeded"
            job.last_error = None
        except Exception as exc:  # noqa: BLE001 — record + retry, never crash the loop
            job.attempts += 1
            job.last_error = str(exc)[:2000]
            if job.attempts >= job.max_attempts:
                job.status = "dead"
                logger.error("outbox job %s dead after %d attempts: %s", job.id, job.attempts, exc)
            else:
                job.status = "failed"
                delay = min(_BACKOFF_BASE_SECONDS * (4 ** (job.attempts - 1)), _BACKOFF_CAP_SECONDS)
                job.next_run_at = datetime.utcnow() + timedelta(seconds=delay)
                logger.warning("outbox job %s failed (attempt %d), retrying in %ds: %s", job.id, job.attempts, delay, exc)
        finally:
            job.locked_at = None
            job.locked_by = None
            job.updated_at = datetime.utcnow()
            db.add(job)
            db.commit()
        processed += 1
    return processed


# ── Object-storage cleanup handlers (this package's job types) ──────────────


def _handle_delete_object(db: Session, job: OutboxJob) -> None:
    """Delete an object-storage blob (s3:// or local://). Missing is success."""
    from app.services.storage_service import delete_local_uri, delete_s3_object, is_local_uri

    payload = json.loads(job.payload_json) if job.payload_json else {}
    storage_uri = payload.get("storage_uri")
    if not storage_uri:
        return
    if is_local_uri(storage_uri):
        delete_local_uri(storage_uri)
    elif storage_uri.startswith("s3://"):
        delete_s3_object(storage_uri)
    else:
        logger.debug("delete_object: unhandled storage scheme, skipping: %s", storage_uri)


register_handler("delete_object", _handle_delete_object)
register_handler("cleanup_failed_upload", _handle_delete_object)
