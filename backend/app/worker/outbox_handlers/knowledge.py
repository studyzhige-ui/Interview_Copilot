"""Worker handlers for knowledge-index synchronization."""

from sqlalchemy.orm import Session

from app.models.outbox_job import OutboxJob
from app.services.knowledge.index_jobs import JOB_MILVUS_DELETE, JOB_MILVUS_UPSERT
from app.services.outbox import register_handler


def handle_milvus_upsert(db: Session, job: OutboxJob) -> None:
    from app.rag.ingestion import reindex_document
    from app.services.knowledge.knowledge_service import (
        mark_document_index_failed,
        mark_document_indexed_ready,
    )

    document_id = job.aggregate_id
    if not document_id:
        raise ValueError(f"{JOB_MILVUS_UPSERT}: job {job.id} has no document id")
    from app.models.knowledge import KnowledgeDocument

    owner = (
        db.query(KnowledgeDocument.user_id)
        .filter(KnowledgeDocument.id == document_id)
        .scalar()
    )
    if owner is not None and owner != job.user_id:
        raise PermissionError("knowledge-index job owner does not match document owner")
    try:
        reindex_document(db, document_id)
    except Exception:
        if job.attempts + 1 >= job.max_attempts:
            mark_document_index_failed(
                db,
                document_id,
                "向量索引多次重试仍失败，请稍后重新导入该文档。",
            )
        raise
    mark_document_indexed_ready(db, document_id)


def handle_milvus_delete(db: Session, job: OutboxJob) -> None:
    from app.rag import milvus_hybrid

    document_id = job.aggregate_id
    if not document_id:
        raise ValueError(f"{JOB_MILVUS_DELETE}: job {job.id} has no document id")
    payload = job.payload_json or {}
    if payload.get("user_id") != job.user_id:
        raise PermissionError("knowledge-index job owner does not match payload owner")
    milvus_hybrid.delete_by_field(milvus_hybrid.KNOWLEDGE, "document_id", document_id)


register_handler(JOB_MILVUS_UPSERT, handle_milvus_upsert)
register_handler(JOB_MILVUS_DELETE, handle_milvus_delete)

__all__ = ["handle_milvus_delete", "handle_milvus_upsert"]
