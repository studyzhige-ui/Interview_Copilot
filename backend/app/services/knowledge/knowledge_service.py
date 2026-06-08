import json
import logging
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.models.file_asset import FileAsset
from app.models.knowledge import KnowledgeDocument
from app.services.storage_service import delete_s3_object, parse_s3_uri

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


def delete_document_vectors_and_chunks(db: Session, document: KnowledgeDocument) -> None:
    """Delete a document's chunk facts (Postgres ``document_chunks``) and its
    Milvus index entries (the native hybrid collection, keyed by document_id)."""
    from app.rag import milvus_hybrid
    from app.services.knowledge.document_chunk_service import delete_document_chunks

    delete_document_chunks(db, document.id)
    milvus_hybrid.delete_by_document(document.id)


def hard_delete_knowledge_document(db: Session, document: KnowledgeDocument) -> None:
    # document.user_id is the stable users.id (CLEANUP #2) — the FileAsset's
    # owner — and object_key is namespaced by it, so use it directly.
    owner_pk = document.user_id
    expected_prefix = f"uploads/{owner_pk}/{document.upload_id}/"
    _, storage_key = parse_s3_uri(document.storage_uri)
    if document.object_key != storage_key or not document.object_key.startswith(expected_prefix):
        raise ValueError("Refusing to delete knowledge object outside the owned upload prefix")

    document.status = "deleting"
    document.updated_at = datetime.utcnow()
    db.add(document)
    db.commit()

    try:
        delete_document_vectors_and_chunks(db, document)
        delete_s3_object(document.storage_uri)
    except Exception as exc:
        document.status = "delete_failed"
        document.error_message = str(exc)
        document.updated_at = datetime.utcnow()
        db.add(document)
        db.commit()
        raise

    upload = document.upload
    db.delete(document)
    if upload is not None:
        db.delete(upload)
    db.commit()
