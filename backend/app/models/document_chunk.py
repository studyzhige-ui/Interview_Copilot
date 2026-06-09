"""``document_chunks``: the Postgres fact source for knowledge-base chunks.

Postgres owns the chunk TEXT (this table); Milvus owns the retrieval INDEX —
dense vector + native server-side BM25 sparse over the chunk text (see
``app.rag.milvus_hybrid``). The authoritative chunk text lives here. This
replaced the LlamaIndex ``PostgresDocumentStore`` as the project's chunk store:
full-text reconstruction (``document_chunk_service.read_document_text``) reads
this table; BM25 retrieval is now served by Milvus, not from here.

A row is one chunk:
  * knowledge-document chunk -> ``document_id`` set (FK to knowledge_documents);
  * personal_memory chunk    -> ``document_id`` NULL (no knowledge_documents
    row), identified by ``source_kind='personal_memory'`` + ``user_id``.

``user_id`` / ``source_kind`` are denormalised so the keyword + diagnostics
scoped reads don't need a join. ``user_id`` here is the stable ``users.id`` FK —
the same value used as the Milvus retrieval-scope key. CLEANUP #2 moved the whole
RAG scope key from username to ``users.id``; ingestion writes the pk to both the
Milvus node metadata and this column, and retrieval filters both by the pk.
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
        Index("ix_document_chunks_user_source", "user_id", "source_kind"),
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
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    source_kind = Column(String, nullable=False)
    chunk_index = Column(Integer, nullable=False, default=0)
    text = Column(Text, nullable=False)
    # Content hash for idempotency / change detection on re-ingest.
    text_hash = Column(String, nullable=True)
    metadata_json = Column(Text, nullable=True)
    # Index lifecycle: pending -> indexed (Milvus written) / failed / deleted.
    index_status = Column(String, nullable=False, default="pending")
    # Optional BM25/full-text external index reference (reserved).
    lexical_index_id = Column(String, nullable=True)
    # Soft delete — read paths exclude deleted_at IS NOT NULL / index_status=
    # 'deleted' immediately, so a not-yet-completed Milvus delete can't leak a
    # removed chunk back into RAG context.
    deleted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False,
    )
