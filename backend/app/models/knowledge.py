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
    # username via resolve_user_pk; ingestion bridges this back to the username
    # for the Milvus / document_chunks index copies (which key on the username).
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False,
    )
    upload_id = Column(String, ForeignKey("file_assets.id"), index=True, nullable=False)
    title = Column(String, nullable=False)
    category = Column(String, index=True, default="默认", nullable=False)
    source_kind = Column(String, index=True, nullable=False)
    storage_uri = Column(String, nullable=False)
    object_key = Column(String, nullable=False, index=True)
    status = Column(String, index=True, default="processing", nullable=False)
    task_id = Column(String, nullable=True)
    chunk_count = Column(Integer, default=0, nullable=False)
    # Deletes go by document_id (milvus_hybrid.delete_by_document + the
    # document_chunks rows) — nothing reads node ids back for deletion anymore.
    # ``ref_doc_ids`` records the LlamaIndex ref-doc ids from the last ingest as
    # a diagnostic/audit field; it is NOT read for retrieval or deletion.
    ref_doc_ids = Column(Text, default="[]", nullable=False)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    upload = relationship("FileAsset")
