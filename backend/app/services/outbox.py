"""Enqueue + drain for ``outbox_jobs`` — reliable cross-system side effects.

Producers call :func:`enqueue_job` inside the same transaction as the business
write. A worker periodically calls :func:`run_due_outbox_jobs`, which claims a
batch of due jobs (lock-guarded), runs the registered handler, and marks each
succeeded / retry-with-backoff / dead.

This module registers object-storage cleanup handlers. Domain packages
register their own indexing and cleanup job types against the same runner.
"""

from __future__ import annotations

import logging
import socket
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from copy import deepcopy
from threading import Event, Thread
from collections.abc import Collection
from datetime import datetime, timedelta
from typing import Any, Callable, Literal

from sqlalchemy import and_, event, or_
from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.db.types import utc_now
from app.models.outbox_job import OutboxJob, generate_outbox_job_id

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OutboxAttempt:
    id: str
    user_id: int
    job_type: str
    aggregate_id: str | None
    payload_json: Any
    idempotency_key: str | None
    attempts: int
    max_attempts: int
    status: str
    lease_version: int
    locked_by: str | None


# job_type -> handler(db, job) -> None (raise to fail/retry).
_HANDLERS: dict[str, Callable[[Session, OutboxAttempt], None]] = {}

# Exponential backoff per attempt, capped. attempts=1 -> 60s, 2 -> 240s, ...
_BACKOFF_BASE_SECONDS = 60
_BACKOFF_CAP_SECONDS = 3600

OutboxLane = Literal["index", "cleanup"]

INDEX_JOB_TYPES = frozenset(
    {
        "milvus_delete_document",
        "milvus_upsert_document",
    }
)
# Pre-cut-over ``milvus_reindex_resume`` rows are intentionally outside every
# production lane. They remain inert audit records until retention cleanup;
# no handler may mutate legacy Resume/ResumeSection state after the cut-over.
CLEANUP_JOB_TYPES = frozenset({"delete_object", "cleanup_failed_upload"})

_JOB_LANES: dict[str, OutboxLane] = {
    **dict.fromkeys(INDEX_JOB_TYPES, "index"),
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
    job_type: str, handler: Callable[[Session, OutboxAttempt], None]
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


def _owned_job(db: Session, job: OutboxAttempt):
    return db.query(OutboxJob).filter(
        OutboxJob.id == job.id,
        OutboxJob.status == "running",
        OutboxJob.lease_version == job.lease_version,
        OutboxJob.locked_by == job.locked_by,
    )


def _claim_job(db: Session, allowed_types) -> OutboxAttempt | None:
    now = utc_now()
    query = db.query(OutboxJob).filter(
        or_(
            and_(
                OutboxJob.status.in_(["pending", "failed"]),
                OutboxJob.next_run_at <= now,
                OutboxJob.locked_at.is_(None),
            ),
            and_(
                OutboxJob.status == "running",
                OutboxJob.locked_at < now - timedelta(minutes=20),
            ),
        )
    )
    if allowed_types is not None:
        query = query.filter(OutboxJob.job_type.in_(allowed_types))
    query = query.order_by(OutboxJob.next_run_at.asc()).limit(1)
    if db.get_bind().dialect.name == "postgresql":
        query = query.with_for_update(skip_locked=True)
    job = query.populate_existing().one_or_none()
    if job is None:
        db.rollback()
        return None
    if job.status == "running":
        job.attempts += 1
    if job.attempts >= job.max_attempts:
        job.status = "dead"
        job.last_error = "worker lease expired repeatedly"
        job.locked_by = None
        job.locked_at = None
    else:
        job.status = "running"
        job.lease_version += 1
        job.locked_by = f"{socket.gethostname()}:{uuid.uuid4().hex}"
        job.locked_at = now
    db.commit()
    db.refresh(job)
    # Handlers receive an attempt snapshot. ORM autoflush must never write an
    # obsolete job object after a newer owner has claimed it.
    snapshot = OutboxAttempt(
        **{
            name: deepcopy(getattr(job, name))
            for name in OutboxAttempt.__dataclass_fields__
        }
    )
    db.rollback()  # release the refresh transaction before external I/O
    return snapshot


@contextmanager
def _renew_lease(db: Session, job: OutboxAttempt):
    stopped = Event()
    bind = db.get_bind()
    # Each renewal owns a new connection/transaction, not the handler Session.
    engine = getattr(bind, "engine", bind)

    def renew():
        while not stopped.wait(60):
            try:
                with Session(engine) as lease_db:
                    changed = _owned_job(lease_db, job).update(
                        {OutboxJob.locked_at: utc_now()}, synchronize_session=False
                    )
                    lease_db.commit()
                if not changed:
                    return
            except Exception:
                logger.exception("outbox lease renewal failed: %s", job.id)
                return

    thread = Thread(target=renew, name="outbox-lease", daemon=True)
    thread.start()
    try:
        yield
    finally:
        stopped.set()
        thread.join(timeout=10)


def run_due_outbox_jobs(
    db: Session, *, limit: int = 50, job_types: Collection[str] | None = None
) -> int:
    """Claim just-in-time, renew while executing, and fence every settlement.

    External operations must still be idempotent: losing a lease cannot undo
    a request already accepted by another system.
    """
    allowed = tuple(sorted(set(job_types))) if job_types is not None else None
    if allowed == ():
        return 0
    processed = 0
    for _ in range(limit):
        job = _claim_job(db, allowed)
        if job is None:
            break
        if job.status == "dead":
            continue
        values = {"status": "succeeded", "last_error": None}
        with _renew_lease(db, job):
            try:
                handler = _HANDLERS.get(job.job_type)
                if handler is None:
                    raise RuntimeError(
                        f"no handler registered for job_type={job.job_type}"
                    )
                handler(db, job)
            except Exception as exc:
                db.rollback()  # SQL failures must not poison the settlement.
                attempts = job.attempts + 1
                values = {
                    "status": "dead" if attempts >= job.max_attempts else "failed",
                    "attempts": attempts,
                    "last_error": str(exc)[:2000],
                    "next_run_at": utc_now()
                    + timedelta(
                        seconds=min(
                            _BACKOFF_BASE_SECONDS * 4 ** (attempts - 1),
                            _BACKOFF_CAP_SECONDS,
                        )
                    ),
                }
            values.update(locked_at=None, locked_by=None, updated_at=utc_now())
            changed = _owned_job(db, job).update(values, synchronize_session=False)
            if changed:
                db.commit()
            else:
                db.rollback()
                logger.warning(
                    "outbox stale owner settlement rejected: %s/%s",
                    job.id,
                    job.lease_version,
                )
        processed += 1
    dead = db.query(OutboxJob).filter(OutboxJob.status == "dead")
    if allowed is not None:
        dead = dead.filter(OutboxJob.job_type.in_(allowed))
    if count := dead.count():
        logger.warning("outbox has %d dead job(s) needing manual attention", count)
    return processed


# ── Object-storage cleanup handlers (this package's job types) ──────────────


def _handle_delete_object(db: Session, job: OutboxAttempt) -> None:
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
    # Permanent FileAsset deletion keeps a minimal reference tombstone because
    # Artifact/Interview History may still point at the exact old identity.
    # Only this aggregate shape therefore graduates delete_pending -> deleted;
    # ordinary cleanup jobs may have physically removed their FileAsset row.
    if getattr(job, "aggregate_type", None) == "file_asset" and db is not None:
        from app.models.file_asset import FileAsset

        asset = db.get(FileAsset, job.aggregate_id)
        if (
            asset is not None
            and asset.user_id == job.user_id
            and asset.upload_status == "delete_pending"
        ):
            asset.upload_status = "deleted"
            asset.updated_at = utc_now()
            db.add(asset)


register_handler("delete_object", _handle_delete_object)
register_handler("cleanup_failed_upload", _handle_delete_object)
