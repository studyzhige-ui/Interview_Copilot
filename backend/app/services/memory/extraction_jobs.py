"""Persistent memory-extraction outbox jobs (MEMORY-V3).

Realtime + dreaming extraction run as ``outbox_jobs`` so a transient LLM/DB
failure is retried with backoff (never silently lost) and the extraction
cursor advances ONLY when the job succeeds. The extraction CORES live in their
domain modules (``realtime_extraction.run_realtime_extraction`` and
``dreaming_worker.dream_for_record``) — both manage their own DB session with an
atomic dispatch + cursor advance, so a partial write can't escape and a retry
is idempotent. This module is just the outbox glue: enqueue helpers + handlers.

Worker handlers are registered by ``app.worker.tasks.outbox``.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.outbox_job import OutboxJob
from app.services.outbox import enqueue_job

REALTIME_JOB = "extract_memory_realtime"
DREAMING_JOB = "extract_memory_dreaming"

# Statuses for which a job is still "in flight" — used to avoid piling up
# duplicate dreaming jobs for the same record within a scan.
_INFLIGHT = ("pending", "running", "failed")


# ── Enqueue helpers ──────────────────────────────────────────────────────


def enqueue_realtime_extraction_in_transaction(
    db: Session,
    *,
    user_pk: int,
    session_id: str,
    user_id: str,
    record_id: str | None,
    upto_seq: int,
) -> OutboxJob | None:
    """Add extraction to the transaction that persisted the assistant reply."""
    return enqueue_job(
        db,
        user_pk=user_pk,
        job_type=REALTIME_JOB,
        aggregate_type="conversation",
        aggregate_id=session_id,
        payload={
            "session_id": session_id,
            "user_id": user_id,
            "record_id": record_id,
            "upto_seq": upto_seq,
        },
        idempotency_key=f"rt:{session_id}:{upto_seq}",
    )


def enqueue_dreaming(db: Session, *, user_pk: int, record_id: str) -> OutboxJob | None:
    """Enqueue a dreaming job for a record, unless one is already in flight for
    it (avoids piling up no-op dups within a nightly scan). Added to the
    caller's transaction — the caller commits."""
    existing = (
        db.query(OutboxJob.id)
        .filter(
            OutboxJob.job_type == DREAMING_JOB,
            OutboxJob.aggregate_id == record_id,
            OutboxJob.status.in_(_INFLIGHT),
        )
        .first()
    )
    if existing:
        return None
    return enqueue_job(
        db,
        user_pk=user_pk,
        job_type=DREAMING_JOB,
        aggregate_type="interview_record",
        aggregate_id=record_id,
        payload={"record_id": record_id},
    )


__all__ = [
    "REALTIME_JOB",
    "DREAMING_JOB",
    "enqueue_realtime_extraction_in_transaction",
    "enqueue_dreaming",
]
