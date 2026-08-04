"""Enqueue + drain for ``outbox_jobs`` — reliable cross-system side effects.

Producers call :func:`enqueue_job` inside the same transaction as the business
write. A worker periodically calls :func:`run_due_outbox_jobs`, which claims a
batch of due jobs (lock-guarded), runs the registered handler, and marks each
succeeded / retry-with-backoff / dead.

This module registers the object-storage cleanup handlers
(``delete_object`` / ``cleanup_failed_upload``). Later packages register their
own job types (ingest / transcribe / memory) against the same table + runner.
"""

from __future__ import annotations

import json
import logging
import socket
from datetime import datetime, timedelta
from collections.abc import Collection
from typing import Any, Callable

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.models.outbox_job import OutboxJob, generate_outbox_job_id

logger = logging.getLogger(__name__)

# job_type -> handler(db, job) -> None (raise to fail/retry).
_HANDLERS: dict[str, Callable[[Session, OutboxJob], None]] = {}

# Exponential backoff per attempt, capped. attempts=1 -> 60s, 2 -> 240s, ...
_BACKOFF_BASE_SECONDS = 60
_BACKOFF_CAP_SECONDS = 3600


def register_handler(
    job_type: str, handler: Callable[[Session, OutboxJob], None]
) -> None:
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
    run_after: datetime | None = None,
) -> OutboxJob | None:
    """Add a job in the caller's transaction (caller commits).

    Idempotent on ``(job_type, idempotency_key)``: a duplicate enqueue is a
    no-op (returns the existing job) rather than a second side effect.
    """
    job_id = generate_outbox_job_id()
    values = {
        "id": job_id,
        "user_id": user_pk,
        "job_type": job_type,
        "aggregate_type": aggregate_type,
        "aggregate_id": aggregate_id,
        "payload_json": json.dumps(payload, ensure_ascii=False) if payload else None,
        "status": "pending",
        "attempts": 0,
        "max_attempts": max_attempts,
        "next_run_at": run_after or datetime.utcnow(),
        "idempotency_key": idempotency_key,
    }
    if idempotency_key is not None and db.get_bind().dialect.name in {
        "postgresql",
        "sqlite",
    }:
        if db.get_bind().dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import insert
        else:
            from sqlalchemy.dialects.sqlite import insert

        statement = (
            insert(OutboxJob)
            .values(**values)
            .on_conflict_do_nothing(index_elements=["job_type", "idempotency_key"])
            .returning(OutboxJob.id)
        )
        inserted_id = db.execute(statement).scalar_one_or_none()
        if inserted_id is not None:
            return db.get(OutboxJob, inserted_id)
        return (
            db.query(OutboxJob)
            .filter(
                OutboxJob.job_type == job_type,
                OutboxJob.idempotency_key == idempotency_key,
            )
            .one()
        )

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

    job = OutboxJob(**values)
    db.add(job)
    return job


def run_due_outbox_jobs(
    db: Session,
    *,
    limit: int = 50,
    job_types: Collection[str] | None = None,
) -> int:
    """Claim and run up to ``limit`` due jobs. Returns the count processed.

    A claimed job is locked (``locked_by`` = host) so concurrent workers don't
    double-run it. Handlers are expected to be idempotent regardless.
    """
    allowed_types = tuple(sorted(set(job_types))) if job_types is not None else None
    if allowed_types == ():
        return 0

    worker_id = f"{socket.gethostname()}:{id(db)}"
    now = datetime.utcnow()
    # Stale-lock recovery: a worker that is SIGKILLed after the claim commit
    # leaves the job at status='running' with locked_at set — the finally
    # block never runs, and without this clause the job would be invisible
    # to every future claim forever. The drain task has a 15-minute hard
    # limit, so the lease must be longer than that or another worker could
    # steal a live LLM/indexing job.
    stale_cutoff = now - timedelta(minutes=20)
    # Atomic claim: lock a due batch with FOR UPDATE SKIP LOCKED and flip it to
    # ``running`` in ONE transaction, so two concurrent workers never grab the
    # same job. SKIP LOCKED is a no-op on sqlite (unit tests run single-
    # threaded), so we only request it on Postgres.
    query = db.query(OutboxJob).filter(
        or_(
            and_(
                or_(OutboxJob.status == "pending", OutboxJob.status == "failed"),
                OutboxJob.next_run_at <= now,
                OutboxJob.locked_at.is_(None),
            ),
            # Orphaned by a hard-killed worker — reclaim.
            and_(
                OutboxJob.status == "running",
                OutboxJob.locked_at < stale_cutoff,
            ),
        )
    )
    if allowed_types is not None:
        query = query.filter(OutboxJob.job_type.in_(allowed_types))
    query = query.order_by(OutboxJob.next_run_at.asc()).limit(limit)
    if db.get_bind().dialect.name == "postgresql":
        query = query.with_for_update(skip_locked=True)
    claimed = query.all()
    runnable: list[OutboxJob] = []
    for job in claimed:
        if job.status == "running":
            # Count the crashed attempt: a handler that hard-kills its worker
            # every time would otherwise be reclaimed forever without
            # ``attempts`` moving, and could never reach ``dead``.
            job.attempts += 1
            logger.warning(
                "outbox job %s reclaimed from stale lock (locked_by=%s since %s, attempt %d)",
                job.id,
                job.locked_by,
                job.locked_at,
                job.attempts,
            )
            if job.attempts >= job.max_attempts:
                job.status = "dead"
                job.last_error = (
                    "worker died mid-run repeatedly (stale-lock reclaim limit)"
                )
                job.locked_at = None
                job.locked_by = None
                db.add(job)
                logger.error(
                    "outbox job %s dead after %d crashed attempts", job.id, job.attempts
                )
                continue
        job.status = "running"
        job.locked_at = datetime.utcnow()
        job.locked_by = worker_id
        db.add(job)
        runnable.append(job)
    db.commit()

    processed = 0
    for job in runnable:
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
                logger.error(
                    "outbox job %s dead after %d attempts: %s",
                    job.id,
                    job.attempts,
                    exc,
                )
            else:
                job.status = "failed"
                delay = min(
                    _BACKOFF_BASE_SECONDS * (4 ** (job.attempts - 1)),
                    _BACKOFF_CAP_SECONDS,
                )
                job.next_run_at = datetime.utcnow() + timedelta(seconds=delay)
                logger.warning(
                    "outbox job %s failed (attempt %d), retrying in %ds: %s",
                    job.id,
                    job.attempts,
                    delay,
                    exc,
                )
        finally:
            job.locked_at = None
            job.locked_by = None
            job.updated_at = datetime.utcnow()
            db.add(job)
            db.commit()
        processed += 1

    # Dead-backlog visibility: dead jobs mean permanently-skipped side
    # effects (leaked blobs / stale Milvus rows / lost memory extraction)
    # and nothing else surfaces them. One WARNING per drain (≤1/min) while
    # any exist is deliberate — quiet enough to live with, loud enough to
    # notice in logs.
    dead_query = db.query(OutboxJob).filter(OutboxJob.status == "dead")
    if allowed_types is not None:
        dead_query = dead_query.filter(OutboxJob.job_type.in_(allowed_types))
    dead_count = dead_query.count()
    if dead_count:
        logger.warning(
            "outbox has %d dead job(s) needing manual attention "
            "(inspect outbox_jobs WHERE status='dead')",
            dead_count,
        )
    return processed


# ── Object-storage cleanup handlers (this package's job types) ──────────────


def _handle_delete_object(db: Session, job: OutboxJob) -> None:
    """Delete an object-storage blob (s3:// or local://). Missing is success."""
    from app.core.storage import (
        LOCAL_URI_PREFIX,
        delete_local_uri,
        delete_s3_object,
        is_local_uri,
        parse_s3_uri,
    )

    payload = json.loads(job.payload_json) if job.payload_json else {}
    storage_uri = payload.get("storage_uri")
    if not storage_uri or payload.get("user_id") != job.user_id:
        raise ValueError(f"{job.job_type}: bad payload {payload}")

    if is_local_uri(storage_uri):
        object_key = storage_uri[len(LOCAL_URI_PREFIX) :].lstrip("/")
    elif storage_uri.startswith("s3://"):
        _, object_key = parse_s3_uri(storage_uri)
    else:
        raise ValueError(f"{job.job_type}: unsupported storage URI")
    if not object_key.startswith(f"uploads/{job.user_id}/"):
        raise PermissionError("object-delete job points outside its owner prefix")

    if is_local_uri(storage_uri):
        delete_local_uri(storage_uri)
    else:
        delete_s3_object(storage_uri)


register_handler("delete_object", _handle_delete_object)
register_handler("cleanup_failed_upload", _handle_delete_object)
