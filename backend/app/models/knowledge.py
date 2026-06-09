import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import relationship

from app.db.database import Base


def generate_document_id() -> str:
    return f"kdoc_{uuid.uuid4().hex}"


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"
    # Composite — library list filters by user + category. NB the
    # index is named ``ix_knowledge_docs_user_category`` despite living
    # on the ``knowledge_documents`` table (legacy from when the table
    # was named ``knowledge_docs``). See alembic 0001_baseline:318.
    __table_args__ = (
        Index("ix_knowledge_docs_user_category", "user_id", "category"),
    )

    id = Column(String, primary_key=True, default=generate_document_id, index=True)
    # Stable users.id FK (CLEANUP #2). The library API resolves the caller's
    # username via resolve_user_pk; the same pk is the Milvus / document_chunks
    # retrieval-scope key.
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False,
    )
    # Source file, if any. NULL for improved_qa / manual_text (no uploaded file).
    file_asset_id = Column(String, ForeignKey("file_assets.id"), index=True, nullable=True)
    title = Column(String, nullable=False)
    category = Column(String, index=True, default="默认", nullable=False)
    # System source kind: user_upload | improved_qa | manual_text.
    source_kind = Column(String, index=True, nullable=False)
    # Provenance for non-file docs (improved_qa): which business object produced
    # this doc — e.g. source_ref_type='interview_qa', source_ref_id=interview_qa.id.
    source_ref_type = Column(String, nullable=True)
    source_ref_id = Column(String, index=True, nullable=True)
    source_interview_record_id = Column(String, index=True, nullable=True)
    # Document body — display / chunking / reindex. Set directly for improved_qa
    # / manual_text; for file docs the body also lives in document_chunks.
    content_text = Column(Text, nullable=True)
    # Storage location — NULL for fileless docs (improved_qa / manual_text).
    storage_uri = Column(String, nullable=True)
    object_key = Column(String, nullable=True, index=True)
    status = Column(String, index=True, default="processing", nullable=False)
    task_id = Column(String, nullable=True)
    chunk_count = Column(Integer, default=0, nullable=False)
    # Deletes go by document_id (milvus_hybrid.delete_by_field + the
    # document_chunks rows) — nothing reads node ids back for deletion anymore.
    # ``ref_doc_ids`` records the LlamaIndex ref-doc ids from the last ingest as
    # a diagnostic/audit field; it is NOT read for retrieval or deletion.
    ref_doc_ids = Column(Text, default="[]", nullable=False)
    error_message = Column(Text, nullable=True)
    # Soft delete — read paths exclude deleted_at IS NOT NULL immediately, even
    # before the async Milvus index delete completes.
    deleted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    upload = relationship("FileAsset")
