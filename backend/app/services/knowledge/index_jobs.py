"""Durable job producers for the Milvus knowledge index.

The knowledge document delete / reindex paths enqueue these in the SAME
transaction as the Postgres state change; the outbox worker drains them,
applying the Milvus side effect with retry/backoff. Keeping Milvus out of the
business transaction means a Milvus outage delays index cleanup, never blocks
(or silently corrupts) the delete — and the read path stays correct because
visibility is decided by Postgres document/chunk state, not by Milvus.

Reuses the shared ``OutboxJob`` / ``outbox_service`` infrastructure (no new
table, no second retry framework). Convention: ``aggregate_id = document_id``.

Worker-side handlers live in ``app.worker.outbox_handlers.knowledge``.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.services.outbox import enqueue_job

JOB_MILVUS_DELETE = "milvus_delete_document"
JOB_MILVUS_UPSERT = "milvus_upsert_document"


def enqueue_milvus_delete(db: Session, *, user_pk: int, document_id: str) -> None:
    """Queue a reliable Milvus row delete for a document (caller commits).

    Idempotency-keyed per document so duplicate enqueues coalesce: a document is
    deleted once, so a single delete job per ``document_id`` is sufficient. No
    payload — delete only needs ``document_id``; ``source_kind`` is for the
    rebuild jobs (upsert/reindex, C2+) that re-select facts, so carrying it here
    would be an unread key.
    """
    enqueue_job(
        db,
        user_pk=user_pk,
        job_type=JOB_MILVUS_DELETE,
        aggregate_type="knowledge_document",
        aggregate_id=document_id,
        payload={"user_id": user_pk},
        idempotency_key=f"{JOB_MILVUS_DELETE}:{document_id}",
    )


def enqueue_milvus_upsert(db: Session, *, user_pk: int, document_id: str) -> None:
    """Queue a Milvus index (re)build for a document whose ingest-time write
    failed (caller commits). No idempotency_key — unlike delete this is
    repeatable across re-ingests, and the handler (rebuild-from-facts) is itself
    idempotent, so an occasional duplicate run is harmless."""
    enqueue_job(
        db,
        user_pk=user_pk,
        job_type=JOB_MILVUS_UPSERT,
        aggregate_type="knowledge_document",
        aggregate_id=document_id,
    )


__all__ = [
    "JOB_MILVUS_DELETE",
    "JOB_MILVUS_UPSERT",
    "enqueue_milvus_delete",
    "enqueue_milvus_upsert",
]
