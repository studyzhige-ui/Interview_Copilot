"""Reconcile Postgres documents into the active semantic index generation."""

from __future__ import annotations

from sqlalchemy import or_, exists, select, literal
from sqlalchemy.orm import Session

from app.models.knowledge import KnowledgeDocument
from app.models.outbox_job import OutboxJob
from app.rag.index.identity import current_index_identity
from app.rag.application.library.index_jobs import JOB_RETRIEVAL_UPSERT
from app.rag.application.library.index_jobs import enqueue_retrieval_upsert


def enqueue_stale_documents(db: Session, *, limit: int = 100) -> int:
    """Enqueue each ready document missing from the active generation once."""

    fingerprint = current_index_identity().fingerprint
    if type(limit) is not int or not 1 <= limit <= 1000:
        raise ValueError("reconciliation batch must be 1..1000")
    key_expr = (
        literal("rag-generation:") + KnowledgeDocument.id + literal(":" + fingerprint)
    )
    already_enqueued = exists(
        select(OutboxJob.id).where(
            OutboxJob.job_type == JOB_RETRIEVAL_UPSERT,
            OutboxJob.idempotency_key == key_expr,
        )
    )
    documents = db.execute(
        select(KnowledgeDocument.id, KnowledgeDocument.user_id)
        .where(
            KnowledgeDocument.status == "ready",
            KnowledgeDocument.source_kind != "chat_attachment",
            KnowledgeDocument.conversation_id.is_(None),
            KnowledgeDocument.deleted_at.is_(None),
            or_(
                KnowledgeDocument.index_fingerprint.is_(None),
                KnowledgeDocument.index_fingerprint != fingerprint,
            ),
            ~already_enqueued,
        )
        .order_by(KnowledgeDocument.updated_at, KnowledgeDocument.id)
        .limit(limit)
    ).all()
    keyed_documents = [
        (document_id, user_id, f"rag-generation:{document_id}:{fingerprint}")
        for document_id, user_id in documents
    ]
    for document_id, user_id, key in keyed_documents:
        enqueue_retrieval_upsert(
            db,
            user_pk=user_id,
            document_id=document_id,
            idempotency_key=key,
        )
    db.commit()
    return len(keyed_documents)


__all__ = ["enqueue_stale_documents"]
