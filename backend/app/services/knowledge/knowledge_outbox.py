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


def _handle_milvus_delete(db: Session, job: OutboxJob) -> None:
    """Delete a document's Milvus rows by ``document_id``. Idempotent: a missing
    collection or already-deleted rows is success (delete-by-filter is a no-op),
    so a retry never errors."""
    from app.rag import milvus_hybrid

    document_id = job.aggregate_id
    if not document_id:
        logger.warning("%s: job %s has no aggregate_id (document_id)", JOB_MILVUS_DELETE, job.id)
        return
    milvus_hybrid.delete_by_field(milvus_hybrid.KNOWLEDGE, "document_id", document_id)


def enqueue_milvus_delete(db: Session, *, user_pk: int, document_id: str) -> None:
    """Queue a reliable Milvus row delete for a document (caller commits).

    Idempotency-keyed per document so duplicate enqueues coalesce: a document is
    deleted once, so a single delete job per ``document_id`` is sufficient.
    """
    enqueue_job(
        db,
        user_pk=user_pk,
        job_type=JOB_MILVUS_DELETE,
        aggregate_type="knowledge_document",
        aggregate_id=document_id,
        idempotency_key=f"{JOB_MILVUS_DELETE}:{document_id}",
    )


register_handler(JOB_MILVUS_DELETE, _handle_milvus_delete)
