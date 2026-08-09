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

import logging
import socket
from collections.abc import Collection
from datetime import datetime, timedelta
from typing import Any, Callable, Literal

from sqlalchemy import and_, event, or_
from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.db.types import utc_now
from app.models.outbox_job import OutboxJob, generate_outbox_job_id

logger = logging.getLogger(__name__)

# job_type -> handler(db, job) -> None (raise to fail/retry).
_HANDLERS: dict[str, Callable[[Session, OutboxJob], None]] = {}

# Exponential backoff per attempt, capped. attempts=1 -> 60s, 2 -> 240s, ...
_BACKOFF_BASE_SECONDS = 60
_BACKOFF_CAP_SECONDS = 3600

OutboxLane = Literal["index", "intelligence", "cleanup"]

INDEX_JOB_TYPES = frozenset(
    {
        "milvus_delete_document",
        "milvus_upsert_document",
        "milvus_reindex_resume",
        "upsert_memory_ability_index",
        "delete_memory_ability_index",
    }
)
INTELLIGENCE_JOB_TYPES = frozenset(
    {"extract_memory_realtime", "extract_memory_dreaming", "dream_check_user"}
)
CLEANUP_JOB_TYPES = frozenset({"delete_object", "cleanup_failed_upload"})

_JOB_LANES: dict[str, OutboxLane] = {
    **dict.fromkeys(INDEX_JOB_TYPES, "index"),
    **dict.fromkeys(INTELLIGENCE_JOB_TYPES, "intelligence"),
    **dict.fromkeys(CLEANUP_JOB_TYPES, "cleanup"),
}
_WAKEUP_LANES_KEY = "outbox_wakeup_lanes"


def _request_outbox_wakeup(
    db: Session,
    job_type: str,
    *,
    run_after: datetime | None = None,
) -> None:
    """Coalesce one immediate wake-up per resource lane and transaction."""

    lane = _JOB_LANES.get(job_type)
    if lane is None or (run_after is not None and run_after > utc_now()):
        return
    lanes = db.info.setdefault(_WAKEUP_LANES_KEY, set())
    lanes.add(lane)


def _dispatch_committed_outbox_wakeups(db: Session) -> None:
    """Wake workers only after the transaction that created jobs committed."""

    lanes = sorted(db.info.pop(_WAKEUP_LANES_KEY, set()))
    if not lanes:
        return
    from app.task_queue.dispatch import dispatch_outbox_drain

    for lane in lanes:
        try:
            dispatch_outbox_drain(lane)
        except Exception as exc:  # broker outage: Beat remains the recovery path
            logger.warning(
                "Could not wake %s outbox worker after commit; "
                "periodic reconciliation will retry: %s",
                lane,
                exc,
            )


def _clear_pending_outbox_wakeups(db: Session) -> None:
    db.info.pop(_WAKEUP_LANES_KEY, None)


# Listen only to the application's session factory. Unit-test sessionmakers and
# third-party SQLAlchemy sessions do not unexpectedly publish Celery messages.
event.listen(SessionLocal, "after_commit", _dispatch_committed_outbox_wakeups)
event.listen(SessionLocal, "after_rollback", _clear_pending_outbox_wakeups)


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
        "payload_json": payload or None,
        "status": "pending",
        "attempts": 0,
        "max_attempts": max_attempts,
        "next_run_at": run_after or utc_now(),
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
            _request_outbox_wakeup(db, job_type, run_after=run_after)
            return db.get(OutboxJob, inserted_id)
        existing = (
            db.query(OutboxJob)
            .filter(
                OutboxJob.job_type == job_type,
                OutboxJob.idempotency_key == idempotency_key,
            )
            .one()
        )
        if existing.status in {"pending", "failed"}:
            _request_outbox_wakeup(
                db,
                job_type,
                run_after=existing.next_run_at,
            )
        return existing

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
            if existing.status in {"pending", "failed"}:
                _request_outbox_wakeup(
                    db,
                    job_type,
                    run_after=existing.next_run_at,
                )
            return existing

    job = OutboxJob(**values)
    db.add(job)
    _request_outbox_wakeup(db, job_type, run_after=run_after)
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
    now = utc_now()
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
        job.locked_at = utc_now()
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
                job.next_run_at = utc_now() + timedelta(seconds=delay)
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
            job.updated_at = utc_now()
            db.add(job)
            db.commit()
        processed += 1

    # Dead-backlog visibility: dead jobs mean permanently-skipped side
    # effects (leaked blobs / stale Milvus rows / lost memory extraction)
    # and nothing else surfaces them. One WARNING per drain while
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

    payload = job.payload_json or {}
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
