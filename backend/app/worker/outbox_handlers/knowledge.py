"""Worker handlers for knowledge-index synchronization."""

from sqlalchemy.orm import Session

from app.models.outbox_job import OutboxJob
from app.rag.application.library.index_jobs import JOB_RETRIEVAL_DELETE
from app.rag.application.library.index_jobs import JOB_RETRIEVAL_UPSERT
from app.platform.outbox import register_handler


def handle_retrieval_upsert(db: Session, job: OutboxJob) -> None:
    from app.rag.index.knowledge import reindex_document
    from app.rag.application.library.knowledge_service import mark_document_index_failed
    from app.rag.application.library.knowledge_service import (
        mark_document_indexed_ready,
    )

    document_id = job.aggregate_id
    if not document_id:
        raise ValueError(f"{JOB_RETRIEVAL_UPSERT}: job {job.id} has no document id")
    from app.models.knowledge import KnowledgeDocument

    owner = (
        db.query(KnowledgeDocument.user_id)
        .filter(KnowledgeDocument.id == document_id)
        .scalar()
    )
    if owner is not None and owner != job.user_id:
        raise PermissionError("knowledge-index job owner does not match document owner")
    idempotency_key = getattr(job, "idempotency_key", None)
    is_generation_job = bool(
        idempotency_key and idempotency_key.startswith("rag-generation:")
    )
    max_attempts = job.max_attempts
    attempts = job.attempts
    db.rollback()  # read-only owner lookup; do not retain a connection across ML
    try:
        reindex_document(document_id)
    except Exception:
        if attempts + 1 >= max_attempts:
            mark_document_index_failed(
                db,
                document_id,
                "向量索引多次重试仍失败，请稍后重新导入该文档。",
                allow_ready=is_generation_job,
            )
        raise
    mark_document_indexed_ready(db, document_id)


def handle_retrieval_delete(db: Session, job: OutboxJob) -> None:
    from app.rag import hybrid_index

    document_id = job.aggregate_id
    if not document_id:
        raise ValueError(f"{JOB_RETRIEVAL_DELETE}: job {job.id} has no document id")
    payload = job.payload_json or {}
    if payload.get("user_id") != job.user_id:
        raise PermissionError("knowledge-index job owner does not match payload owner")
    hybrid_index.delete_by_field("document_id", document_id, user_pk=job.user_id)


register_handler(JOB_RETRIEVAL_UPSERT, handle_retrieval_upsert)
register_handler(JOB_RETRIEVAL_DELETE, handle_retrieval_delete)

__all__ = ["handle_retrieval_delete", "handle_retrieval_upsert"]
