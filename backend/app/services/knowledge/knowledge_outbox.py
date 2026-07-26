"""Outbox handlers for the Milvus knowledge index (INGEST-INDEXING §4.6.3).

The knowledge document delete / reindex paths enqueue these in the SAME
transaction as the Postgres state change; the outbox worker drains them,
applying the Milvus side effect with retry/backoff. Keeping Milvus out of the
business transaction means a Milvus outage delays index cleanup, never blocks
(or silently corrupts) the delete — and the read path stays correct because
visibility is decided by Postgres document/chunk state, not by Milvus.

Reuses the shared ``OutboxJob`` / ``outbox_service`` infrastructure (no new
table, no second retry framework). Convention: ``aggregate_id = document_id``.

Imported by the worker's drain task so the handlers are registered before any
job runs.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.models.outbox_job import OutboxJob
from app.services.uploads.outbox_service import enqueue_job, register_handler

logger = logging.getLogger(__name__)

JOB_MILVUS_DELETE = "milvus_delete_document"
JOB_MILVUS_UPSERT = "milvus_upsert_document"


def _handle_milvus_upsert(db: Session, job: OutboxJob) -> None:
    """Rebuild a document's Milvus rows from its live Postgres facts and graduate
    it to ``ready`` (plan §4.6.3 / C2). Enqueued when the ingest-time Milvus
    write failed — the facts are already committed ``pending`` and the document
    is left ``processing`` until this lands.

    On the attempt that would exhaust the job (``max_attempts``), mark the
    document ``failed`` before re-raising, so a prolonged Milvus outage resolves
    to a terminal state instead of stranding the doc in ``processing`` forever.
    """
    from app.rag.ingestion import reindex_document
    from app.services.knowledge.knowledge_service import (
        mark_document_index_failed,
        mark_document_indexed_ready,
    )

    document_id = job.aggregate_id
    if not document_id:
        logger.warning(
            "%s: job %s has no aggregate_id (document_id)", JOB_MILVUS_UPSERT, job.id
        )
        return
    try:
        reindex_document(db, document_id)  # rebuild Milvus + flip chunks indexed
    except Exception:
        # attempts is incremented AFTER the handler raises, so this attempt is
        # the last one exactly when attempts + 1 >= max_attempts.
        if job.attempts + 1 >= job.max_attempts:
            mark_document_index_failed(
                db,
                document_id,
                "向量索引多次重试仍失败，请稍后重新导入该文档。",
            )
        raise
    mark_document_indexed_ready(db, document_id)


def _handle_milvus_delete(db: Session, job: OutboxJob) -> None:
    """Delete a document's Milvus rows by ``document_id``. Idempotent: a missing
    collection or already-deleted rows is success (delete-by-filter is a no-op),
    so a retry never errors."""
    from app.rag import milvus_hybrid

    document_id = job.aggregate_id
    if not document_id:
        logger.warning(
            "%s: job %s has no aggregate_id (document_id)", JOB_MILVUS_DELETE, job.id
        )
        return
    milvus_hybrid.delete_by_field(milvus_hybrid.KNOWLEDGE, "document_id", document_id)


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


register_handler(JOB_MILVUS_UPSERT, _handle_milvus_upsert)
register_handler(JOB_MILVUS_DELETE, _handle_milvus_delete)
