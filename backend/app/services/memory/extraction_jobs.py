"""Persistent memory-extraction outbox jobs (MEMORY-V3).

Realtime + dreaming extraction run as ``outbox_jobs`` so a transient LLM/DB
failure is retried with backoff (never silently lost) and the extraction
cursor advances ONLY when the job succeeds. The extraction CORES live in their
domain modules (``realtime_extraction.run_realtime_extraction`` and
``dreaming_worker.dream_for_record``) — both manage their own DB session with an
atomic dispatch + cursor advance, so a partial write can't escape and a retry
is idempotent. This module is just the outbox glue: enqueue helpers + handlers.

Imported by the worker's drain task so the handlers register before any job
runs (mirrors ``ability_outbox``).
"""
from __future__ import annotations

import json
import logging

from sqlalchemy.orm import Session

from app.core.user_identity import resolve_user_pk
from app.db.database import SessionLocal
from app.models.outbox_job import OutboxJob
from app.services.uploads.outbox_service import enqueue_job, register_handler

logger = logging.getLogger(__name__)

REALTIME_JOB = "extract_memory_realtime"
DREAMING_JOB = "extract_memory_dreaming"

# Statuses for which a job is still "in flight" — used to avoid piling up
# duplicate dreaming jobs for the same record within a scan.
_INFLIGHT = ("pending", "running", "failed")


# ── Enqueue helpers ──────────────────────────────────────────────────────


def enqueue_realtime_extraction(
    *, session_id: str, user_id: str, record_id: str | None, upto_seq: int,
) -> None:
    """Enqueue a realtime extraction job for messages up to ``upto_seq``.

    Idempotent on ``(session_id, upto_seq)`` so a re-fired post-turn hook won't
    double-enqueue. Multiple jobs with different ``upto_seq`` are self-
    coordinating: each handler extracts ``(current_cursor, its upto_seq]`` and
    advances the cursor, so a superseded job becomes a no-op (see the core).
    """
    db = SessionLocal()
    try:
        user_pk = resolve_user_pk(db, user_id)
        if user_pk is None:
            return
        enqueue_job(
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
        db.commit()
    except Exception as exc:  # noqa: BLE001 — enqueue is best-effort; the cursor
        # didn't advance, so the next turn re-enqueues the same range.
        db.rollback()
        logger.warning("enqueue_realtime_extraction failed for %s: %s", session_id, exc)
    finally:
        db.close()


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


# ── Handlers ─────────────────────────────────────────────────────────────


def _handle_realtime(db: Session, job: OutboxJob) -> None:
    from app.services.memory.realtime_extraction import run_realtime_extraction

    p = json.loads(job.payload_json) if job.payload_json else {}
    session_id = p.get("session_id")
    user_id = p.get("user_id")
    upto_seq = p.get("upto_seq")
    if not session_id or not user_id or upto_seq is None:
        logger.warning("extract_memory_realtime: bad payload %s", p)
        return
    # Raises on failure → outbox records + retries. The core's own session +
    # cursor re-check make this idempotent.
    run_realtime_extraction(
        session_id=session_id,
        user_id=user_id,
        record_id=p.get("record_id"),
        upto_seq=int(upto_seq),
    )


def _handle_dreaming(db: Session, job: OutboxJob) -> None:
    from app.services.memory.dreaming_worker import dream_for_record

    p = json.loads(job.payload_json) if job.payload_json else {}
    record_id = p.get("record_id")
    if not record_id:
        logger.warning("extract_memory_dreaming: bad payload %s", p)
        return
    summary = dream_for_record(record_id)
    # dream_for_record never raises in normal operation; surface a hard failure
    # to the outbox so it retries (its last_dreamed_at re-check keeps the retry
    # idempotent).
    if summary.get("error"):
        raise RuntimeError(f"dreaming failed for {record_id}: {summary['error']}")


register_handler(REALTIME_JOB, _handle_realtime)
register_handler(DREAMING_JOB, _handle_dreaming)


__all__ = [
    "REALTIME_JOB",
    "DREAMING_JOB",
    "enqueue_realtime_extraction",
    "enqueue_dreaming",
]
