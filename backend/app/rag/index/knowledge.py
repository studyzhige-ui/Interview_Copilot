"""Knowledge-specific vector index repository."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.models.knowledge import KnowledgeDocument
from app.rag.index.identity import current_index_identity
from app.rag.index.publication import publish_document
from app.rag.ingest.embedding import (
    build_retrieval_passages,
    embed_passages,
    node_id,
)


def replace_document_rows(
    nodes: list[Any],
    passages: list[str],
    vectors: list[list[float]],
    *,
    user_id: int,
    source_kind: str,
    document_id: str,
) -> None:
    """Replace one document inside the active, versioned physical collection."""

    from app.rag import milvus_hybrid

    rows = [
        {
            "id": node_id(node),
            "user_id": int(user_id),
            "source_kind": source_kind,
            "document_id": document_id,
            "text": passage,
            "dense": vector,
        }
        for node, passage, vector in zip(nodes, passages, vectors)
    ]
    milvus_hybrid.delete_by_field(milvus_hybrid.KNOWLEDGE, "document_id", document_id)
    milvus_hybrid.insert(milvus_hybrid.KNOWLEDGE, rows)


def _update_embedding_profiles(db: Session, chunks: list[Any], profile: dict) -> None:
    for chunk in chunks:
        try:
            metadata = json.loads(chunk.metadata_json) if chunk.metadata_json else {}
        except (TypeError, json.JSONDecodeError):
            metadata = {}
        metadata["embedding_profile"] = profile
        chunk.metadata_json = json.dumps(metadata, ensure_ascii=False)
        db.add(chunk)


def reindex_document(
    db: Session,
    document_id: str,
    *,
    embed_model: Any | None = None,
) -> int:
    """Rebuild a document from Postgres facts into the active index generation."""

    from app.rag import milvus_hybrid
    from app.rag.document_chunk_service import read_indexable_chunks

    document = (
        db.query(KnowledgeDocument)
        .filter(
            KnowledgeDocument.id == document_id,
            KnowledgeDocument.deleted_at.is_(None),
        )
        .first()
    )
    chunks = read_indexable_chunks(db, document_id)
    if not chunks:
        milvus_hybrid.delete_by_field(
            milvus_hybrid.KNOWLEDGE, "document_id", document_id
        )
        if document is not None:
            document.index_fingerprint = current_index_identity().fingerprint
            db.add(document)
            db.commit()
        return 0
    passages = build_retrieval_passages(
        chunks,
        document_title=document.title if document is not None else None,
    )
    batch = embed_passages(passages, embed_model=embed_model)
    replace_document_rows(
        chunks,
        passages,
        batch.vectors,
        user_id=int(chunks[0].user_id),
        source_kind=chunks[0].source_kind or "",
        document_id=document_id,
    )
    _update_embedding_profiles(db, chunks, batch.profile)
    publish_document(db, document_id, commit=False)
    if document is not None:
        document.index_fingerprint = current_index_identity().fingerprint
        db.add(document)
    db.commit()
    return len(chunks)


__all__ = ["reindex_document", "replace_document_rows"]
