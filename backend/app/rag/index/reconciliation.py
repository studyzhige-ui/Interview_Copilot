"""Reconcile Postgres documents into the active semantic index generation."""

from __future__ import annotations

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.knowledge import KnowledgeDocument
from app.models.outbox_job import OutboxJob
from app.rag.index.identity import current_index_identity
from app.services.knowledge.index_jobs import JOB_MILVUS_UPSERT, enqueue_milvus_upsert


def enqueue_stale_documents(db: Session, *, limit: int = 100) -> int:
    """Enqueue each ready document missing from the active generation once."""

    fingerprint = current_index_identity().fingerprint
    documents = (
        db.query(KnowledgeDocument.id, KnowledgeDocument.user_id)
        .filter(
            KnowledgeDocument.status == "ready",
            KnowledgeDocument.deleted_at.is_(None),
            or_(
                KnowledgeDocument.index_fingerprint.is_(None),
                KnowledgeDocument.index_fingerprint != fingerprint,
            ),
        )
        .order_by(KnowledgeDocument.updated_at.asc())
        .yield_per(500)
    )
    existing = {
        str(row[0])
        for row in (
            db.query(OutboxJob.idempotency_key)
            .filter(
                OutboxJob.job_type == JOB_MILVUS_UPSERT,
                OutboxJob.idempotency_key.like(f"rag-generation:%:{fingerprint}"),
            )
            .all()
        )
    }
    keyed_documents: list[tuple[str, int, str]] = []
    for document_id, user_id in documents:
        key = f"rag-generation:{document_id}:{fingerprint}"
        if key in existing:
            continue
        keyed_documents.append((str(document_id), int(user_id), key))
        if len(keyed_documents) >= limit:
            break
    for document_id, user_id, key in keyed_documents:
        enqueue_milvus_upsert(
            db,
            user_pk=user_id,
            document_id=document_id,
            idempotency_key=key,
        )
    db.commit()
    return len(keyed_documents)


__all__ = ["enqueue_stale_documents"]
