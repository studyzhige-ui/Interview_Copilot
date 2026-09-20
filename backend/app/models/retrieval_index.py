"""Rebuildable PostgreSQL retrieval projections, not another source of truth.

A generation is the complete semantic identity, never only an embedding width.
Exact search is deliberate for the local, tenant-filtered corpus. ANN needs a
measured recall/capacity decision; it is not silently enabled by an index name.
"""

from pgvector.sqlalchemy import VECTOR
from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    ForeignKey,
    Index,
    CheckConstraint,
    JSON,
)
from sqlalchemy.dialects.postgresql import JSONB, ARRAY
from app.db.database import Base
from app.db.types import UTCDateTime, utc_now


class RetrievalGeneration(Base):
    __tablename__ = "retrieval_generations"
    fingerprint = Column(String(64), primary_key=True)
    identity_json = Column(JSON().with_variant(JSONB, "postgresql"), nullable=False)
    embedding_dim = Column(Integer, nullable=False)
    created_at = Column(UTCDateTime, default=utc_now, nullable=False)
    __table_args__ = (
        CheckConstraint(
            "embedding_dim > 0 AND embedding_dim <= 16000",
            name="ck_retrieval_generation_dim",
        ),
    )


class RetrievalEntry(Base):
    __tablename__ = "retrieval_entries"
    generation = Column(
        String(64),
        ForeignKey("retrieval_generations.fingerprint", ondelete="CASCADE"),
        primary_key=True,
    )
    chunk_id = Column(
        String, ForeignKey("document_chunks.id", ondelete="CASCADE"), primary_key=True
    )
    node_id = Column(String, nullable=False)
    document_id = Column(
        String, ForeignKey("knowledge_documents.id", ondelete="CASCADE"), nullable=False
    )
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    source_kind = Column(String, nullable=False)
    source_hash = Column(String(64), nullable=False)
    # Prefix-bearing retrieval text; rendering continues to hydrate canonical text.
    passage = Column(Text, nullable=False)
    embedding = Column(VECTOR().with_variant(JSON, "sqlite"), nullable=False)
    term_counts = Column(JSON().with_variant(JSONB, "postgresql"), nullable=False)
    lexical_terms = Column(ARRAY(Text).with_variant(JSON, "sqlite"), nullable=False)
    token_count = Column(Integer, nullable=False)
    __table_args__ = (
        Index("ux_retrieval_generation_node", "generation", "node_id", unique=True),
        Index(
            "ix_retrieval_user_generation_document",
            "user_id",
            "generation",
            "document_id",
        ),
        Index("ix_retrieval_document", "document_id"),
        Index("ix_retrieval_lexical_terms", "lexical_terms", postgresql_using="gin"),
        CheckConstraint("token_count >= 0", name="ck_retrieval_token_count"),
    )
