import json
import logging
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.models.file_asset import FileAsset
from app.models.knowledge import KnowledgeDocument
from app.core.storage import parse_s3_uri

logger = logging.getLogger(__name__)


def dump_json_list(values: list[str]) -> str:
    return json.dumps(values, ensure_ascii=False)


def default_title(upload: FileAsset) -> str:
    return Path(upload.original_filename).stem or upload.original_filename


def delete_document_vectors_and_chunks(
    db: Session, document: KnowledgeDocument
) -> None:
    """Delete chunk facts and enqueue the external index cleanup atomically."""
    from app.rag.document_chunk_service import delete_document_chunks
    from app.services.knowledge.index_jobs import enqueue_milvus_delete

    delete_document_chunks(db, document.id)
    enqueue_milvus_delete(db, user_pk=document.user_id, document_id=document.id)


def mark_document_indexed_ready(db: Session, document_id: str) -> None:
    """The async Milvus index write landed — graduate an index-queued document
    to ``ready`` (plan §4.6.3 / C2). Only flips a doc still in ``processing`` so
    a delete that happened while the upsert was queued is never resurrected."""
    doc = (
        db.query(KnowledgeDocument).filter(KnowledgeDocument.id == document_id).first()
    )
    if doc is None or doc.status != "processing":
        return
    doc.status = "ready"
    doc.error_message = None
    doc.updated_at = datetime.utcnow()
    db.add(doc)
    db.commit()


def mark_document_index_failed(db: Session, document_id: str, message: str) -> None:
    """The async Milvus index retries were exhausted — terminal failure so an
    index-queued document never stays ``processing`` forever. Only flips a doc
    still in ``processing`` (leaves a concurrent delete alone)."""
    doc = (
        db.query(KnowledgeDocument).filter(KnowledgeDocument.id == document_id).first()
    )
    if doc is None or doc.status != "processing":
        return
    doc.status = "failed"
    doc.error_message = message[:500]
    doc.updated_at = datetime.utcnow()
    db.add(doc)
    db.commit()


def hard_delete_knowledge_document(db: Session, document: KnowledgeDocument) -> None:
    # Fileless docs (improved_qa / manual_text) have no S3 object — only chunks +
    # Milvus index to drop. File docs validate the owned-prefix before any delete.
    has_object = bool(
        document.file_asset_id and document.storage_uri and document.object_key
    )
    if has_object:
        # document.user_id is the stable users.id (CLEANUP #2) — the FileAsset's
        # owner — and object_key is namespaced by it, so use it directly.
        owner_pk = document.user_id
        expected_prefix = f"uploads/{owner_pk}/{document.file_asset_id}/"
        _, storage_key = parse_s3_uri(document.storage_uri)
        if document.object_key != storage_key or not document.object_key.startswith(
            expected_prefix
        ):
            raise ValueError(
                "Refusing to delete knowledge object outside the owned upload prefix"
            )

    # Facts disappear and both external cleanups enter the outbox in one
    # transaction. A crash is therefore all-or-nothing from the application's
    # perspective; Milvus/object-store outages only delay cleanup.
    delete_document_vectors_and_chunks(db, document)
    if has_object:
        from app.services.outbox import enqueue_job

        enqueue_job(
            db,
            user_pk=document.user_id,
            job_type="delete_object",
            aggregate_type="knowledge_document",
            aggregate_id=document.id,
            payload={
                "storage_uri": document.storage_uri,
                "user_id": document.user_id,
            },
            idempotency_key=f"delete_object:kdoc:{document.id}",
        )
    upload = document.upload
    db.delete(document)
    if upload is not None:
        db.delete(upload)
    db.commit()
