import json
import logging
from datetime import datetime
from pathlib import Path

from llama_index.vector_stores.milvus import MilvusVectorStore
from llama_index.storage.docstore.postgres import PostgresDocumentStore
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.knowledge import KnowledgeDocument
from app.models.upload import UserUpload
from app.rag.retriever import _milvus_dense_index_config, _milvus_search_config
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


def default_title(upload: UserUpload) -> str:
    return Path(upload.original_filename).stem or upload.original_filename


def delete_document_vectors_and_docstore(document: KnowledgeDocument) -> None:
    node_ids = json_list(document.node_ids)
    ref_doc_ids = json_list(document.ref_doc_ids)

    vector_store = MilvusVectorStore(
        uri=settings.MILVUS_URI,
        collection_name=settings.MILVUS_COLLECTION,
        dim=settings.EMBEDDING_DIM,
        overwrite=False,
        similarity_metric=settings.MILVUS_SIMILARITY_METRIC,
        index_config=_milvus_dense_index_config(),
        search_config=_milvus_search_config(),
    )
    if node_ids:
        vector_store.delete_nodes(node_ids=node_ids)

    docstore = PostgresDocumentStore.from_uri(uri=settings.DATABASE_URL)
    for ref_doc_id in ref_doc_ids:
        docstore.delete_ref_doc(ref_doc_id, raise_error=False)
    for node_id in node_ids:
        docstore.delete_document(node_id, raise_error=False)


def hard_delete_knowledge_document(db: Session, document: KnowledgeDocument) -> None:
    expected_prefix = f"uploads/{document.user_id}/{document.upload_id}/"
    _, storage_key = parse_s3_uri(document.storage_uri)
    if document.object_key != storage_key or not document.object_key.startswith(expected_prefix):
        raise ValueError("Refusing to delete knowledge object outside the owned upload prefix")

    document.status = "deleting"
    document.updated_at = datetime.utcnow()
    db.add(document)
    db.commit()

    try:
        delete_document_vectors_and_docstore(document)
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
