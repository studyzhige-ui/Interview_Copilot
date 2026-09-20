import json
import logging
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.storage import parse_s3_uri
from app.db.types import utc_now
from app.models.file_asset import FileAsset
from app.models.knowledge import KnowledgeDocument

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

    delete_document_chunks(db, document.id, commit=False)
    if document.source_kind != "chat_attachment":
        from app.rag.application.library.index_jobs import enqueue_retrieval_delete

        enqueue_retrieval_delete(db, user_pk=document.user_id, document_id=document.id)


def mark_document_indexed_ready(db: Session, document_id: str) -> None:
    """The async retrieval projection index write landed — graduate an index-queued document
    to ``ready`` (plan §4.6.3 / C2). Only flips a doc still in ``processing`` so
    a delete that happened while the upsert was queued is never resurrected."""
    doc = (
        db.query(KnowledgeDocument)
        .filter(KnowledgeDocument.id == document_id)
        .populate_existing()
        .with_for_update()
        .first()
    )
    if doc is None or doc.status != "processing":
        return
    from app.rag.index.identity import current_index_identity

    if doc.index_fingerprint != current_index_identity().fingerprint:
        return
    doc.status = "ready"
    doc.error_message = None
    doc.updated_at = utc_now()
    db.add(doc)
    db.commit()


def mark_document_index_failed(
    db: Session,
    document_id: str,
    message: str,
    *,
    allow_ready: bool = False,
) -> None:
    """Mark an exhausted index build failed without reviving deleted rows.

    Normal retries only transition ``processing`` documents. Generation
    migration jobs may opt into failing a ``ready`` document because its old
    physical collection is intentionally no longer queried.
    """
    doc = (
        db.query(KnowledgeDocument)
        .filter(KnowledgeDocument.id == document_id)
        .populate_existing()
        .with_for_update()
        .first()
    )
    allowed_statuses = {"processing", "ready"} if allow_ready else {"processing"}
    if doc is None or doc.status not in allowed_statuses:
        return
    doc.status = "failed"
    doc.error_message = message[:500]
    doc.updated_at = utc_now()
    db.add(doc)
    db.commit()


def hard_delete_knowledge_document(
    db: Session, document: KnowledgeDocument, *, commit: bool = True
) -> None:
    # Fileless docs (improved_qa / manual_text) have no S3 object — only chunks +
    # retrieval projection index to drop. File docs validate the owned-prefix before any delete.
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
    # perspective; retrieval projection/object-store outages only delay cleanup.
    delete_document_vectors_and_chunks(db, document)
    if has_object:
        from app.platform.outbox import enqueue_job

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
    if commit:
        db.commit()
