"""Durable PostgreSQL projection rebuild/cleanup intents.

Enqueued in the same transaction as source edits. Models run outside business
transactions; the resulting projection and index fingerprint publish atomically.
The existing outbox owns retry and dead-letter state; no second task system.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.platform.outbox import enqueue_job

JOB_RETRIEVAL_DELETE = "retrieval_delete_document"
JOB_RETRIEVAL_UPSERT = "retrieval_upsert_document"


def enqueue_retrieval_delete(db: Session, *, user_pk: int, document_id: str) -> None:
    """Queue a reliable retrieval row delete for a document (caller commits).

    Idempotency-keyed per document so duplicate enqueues coalesce: a document is
    deleted once, so a single delete job per ``document_id`` is sufficient. No
    payload — delete only needs ``document_id``; ``source_kind`` is for the
    rebuild jobs (upsert/reindex, C2+) that re-select facts, so carrying it here
    would be an unread key.
    """
    enqueue_job(
        db,
        user_pk=user_pk,
        job_type=JOB_RETRIEVAL_DELETE,
        aggregate_type="knowledge_document",
        aggregate_id=document_id,
        payload={"user_id": user_pk},
        idempotency_key=f"{JOB_RETRIEVAL_DELETE}:{document_id}",
    )


def enqueue_retrieval_upsert(
    db: Session,
    *,
    user_pk: int,
    document_id: str,
    idempotency_key: str | None = None,
) -> None:
    """Queue a retrieval index (re)build for a document whose ingest-time write
    failed (caller commits). An optional caller-supplied idempotency key distinguishes rebuild campaigns.
    Unlike deletion, reindexing is repeatable across re-ingests, and the handler (rebuild-from-facts) is itself
    idempotent, so an occasional duplicate run is harmless."""
    enqueue_job(
        db,
        user_pk=user_pk,
        job_type=JOB_RETRIEVAL_UPSERT,
        aggregate_type="knowledge_document",
        aggregate_id=document_id,
        idempotency_key=idempotency_key,
    )


__all__ = [
    "JOB_RETRIEVAL_DELETE",
    "JOB_RETRIEVAL_UPSERT",
    "enqueue_retrieval_delete",
    "enqueue_retrieval_upsert",
]
