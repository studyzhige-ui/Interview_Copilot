import json
import logging
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.models.file_asset import FileAsset
from app.models.knowledge import KnowledgeDocument
from app.core.storage import parse_s3_uri

logger = logging.getLogger(__name__)


def json_list(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        data = json.loads(value)
    except json.JSONDecodeError:
        return []
    return [str(item) for item in data if item]


def dump_json_list(values: list[str]) -> str:
    return json.dumps(values, ensure_ascii=False)


def default_title(upload: FileAsset) -> str:
    return Path(upload.original_filename).stem or upload.original_filename


def delete_document_vectors_and_chunks(
    db: Session, document: KnowledgeDocument
) -> None:
    """Delete a document's chunk facts (Postgres ``document_chunks``) then its
    Milvus index rows (keyed by document_id).

    Facts go first — the read path is correct the moment they're gone. If the
    Milvus delete fails (outage), it's queued as a ``milvus_delete_document``
    outbox job for reliable retry rather than raising or leaking un-cleaned
    vectors (plan §4.6.3). Visibility is already decided by Postgres state, so
    the queued cleanup never makes a deleted document reappear."""
    from app.rag import milvus_hybrid
    from app.rag.document_chunk_service import delete_document_chunks
    from app.services.knowledge.knowledge_outbox import enqueue_milvus_delete

    delete_document_chunks(db, document.id)
    try:
        milvus_hybrid.delete_by_field(
            milvus_hybrid.KNOWLEDGE, "document_id", document.id
        )
    except Exception as exc:  # noqa: BLE001 — queue a reliable retry, don't fail the delete
        logger.warning(
            "Milvus delete failed for document %s; queuing outbox retry: %s",
            document.id,
            exc,
        )
        enqueue_milvus_delete(db, user_pk=document.user_id, document_id=document.id)
        db.commit()  # facts already committed above; this persists just the retry job


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

    # Mark deleted FIRST so RAG / list read paths exclude this doc immediately,
    # even before the (async-ish) chunk + Milvus deletes below complete.
    document.status = "deleting"
    document.deleted_at = datetime.utcnow()
    document.updated_at = datetime.utcnow()
    db.add(document)
    db.commit()

    try:
        delete_document_vectors_and_chunks(db, document)
    except Exception as exc:
        document.status = "delete_failed"
        document.error_message = str(exc)
        document.updated_at = datetime.utcnow()
        db.add(document)
        db.commit()
        raise

    # Blob delete rides the outbox (UP-2), enqueued only AFTER the vector/
    # chunk delete succeeded and committed together with the row deletes: a
    # vectors failure then parks the doc in delete_failed with its object
    # intact (retryable), and a crash between the vectors delete and this
    # commit leaks a blob (recoverable) instead of stranding a doc row that
    # points at nothing. A storage blip can't park the doc in delete_failed
    # either way — the outbox retries until the object is gone.
    if has_object:
        from app.services.uploads.outbox_service import enqueue_job

        enqueue_job(
            db,
            user_pk=document.user_id,
            job_type="delete_object",
            aggregate_type="knowledge_document",
            aggregate_id=document.id,
            payload={"storage_uri": document.storage_uri},
            idempotency_key=f"delete_object:kdoc:{document.id}",
        )
    upload = document.upload
    db.delete(document)
    if upload is not None:
        db.delete(upload)
    db.commit()
