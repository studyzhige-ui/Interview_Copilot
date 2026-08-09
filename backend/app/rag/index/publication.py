"""Atomic Postgres publication state for an external vector-index write."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.document_chunk import DocumentChunk
from app.models.knowledge import KnowledgeDocument
from app.rag.index.identity import current_index_identity


def publish_document(db: Session, document_id: str, *, commit: bool = True) -> int:
    """Mark chunks and their owning document as one active index generation."""

    fingerprint = current_index_identity().fingerprint
    updated = (
        db.query(DocumentChunk)
        .filter(
            DocumentChunk.document_id == document_id,
            DocumentChunk.index_status == "pending",
        )
        .update(
            {DocumentChunk.index_status: "indexed"},
            synchronize_session=False,
        )
    )
    db.query(KnowledgeDocument).filter(
        KnowledgeDocument.id == document_id,
    ).update(
        {KnowledgeDocument.index_fingerprint: fingerprint},
        synchronize_session=False,
    )
    if commit:
        db.commit()
    return updated


__all__ = ["publish_document"]
