"""``document_chunks``: the Postgres fact source for knowledge-base chunks.

Postgres owns the chunk TEXT (this table). Milvus owns the retrieval INDEX
(dense vector + — going forward — BM25 sparse). Milvus stores a copy of the
text only as a BM25/full-text index field; the authoritative chunk text lives
here. This replaces the LlamaIndex ``PostgresDocumentStore`` as the project's
chunk store: full-text reconstruction (``read_full_text_from_docstore``) and
the keyword (BM25) source both read this table now.

A row is one chunk:
  * knowledge-document chunk -> ``document_id`` set (FK to knowledge_documents);
  * personal_memory chunk    -> ``document_id`` NULL (no knowledge_documents
    row), identified by ``source_type='personal_memory'`` + ``user_id``.

``user_id`` / ``source_type`` are denormalised so the keyword + diagnostics
scoped reads don't need a join. (``user_id`` mirrors ``knowledge_documents``'s
current username key; it migrates to the stable id with that table.)
"""
import uuid
from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)

from app.db.database import Base


def generate_chunk_id() -> str:
    return f"dch_{uuid.uuid4().hex}"


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    __table_args__ = (
        # Keyword (BM25) + diagnostics scoped scan: a user's chunks of a kind.
        Index("ix_document_chunks_user_source", "user_id", "source_type"),
        # Ordered reconstruction of one document's chunks.
        Index("ix_document_chunks_doc_order", "document_id", "chunk_index"),
    )

    id = Column(String, primary_key=True, default=generate_chunk_id, index=True)
    # NULL for personal_memory chunks (no knowledge_documents row).
    document_id = Column(
        String,
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"),
        index=True,
        nullable=True,
    )
    # Milvus node id this chunk is indexed under — used to delete the matching
    # vector when the chunk is removed.
    node_id = Column(String, index=True, nullable=True)
    user_id = Column(String, index=True, nullable=False)
    source_type = Column(String, nullable=False)
    chunk_index = Column(Integer, nullable=False, default=0)
    text = Column(Text, nullable=False)
    # Content hash for idempotency / change detection on re-ingest.
    text_hash = Column(String, nullable=True)
    metadata_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False,
    )
