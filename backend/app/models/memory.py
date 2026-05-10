import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, Float, Integer, String, Text

from app.db.database import Base


def _generate_memory_id() -> str:
    return f"mem_{uuid.uuid4().hex[:12]}"


class MemoryItem(Base):
    __tablename__ = "memory_items"

    id = Column(String, primary_key=True, default=_generate_memory_id, index=True)
    user_id = Column(String, index=True, nullable=False)
    type = Column(String, index=True, nullable=False)
    scope = Column(String, index=True, default="user", nullable=False)
    description = Column(String, nullable=False)
    normalized_key = Column(String, index=True, nullable=False)
    content = Column(Text, nullable=False)
    confidence = Column(Float, default=0.0)
    importance = Column(Float, default=0.5)
    source_session_id = Column(String, nullable=True)
    last_evidence_seq = Column(Integer, nullable=True)
    recall_count = Column(Integer, default=0)
    last_accessed_at = Column(DateTime, nullable=True)
    embedding_status = Column(String, default="pending", nullable=False)
    embedding_model = Column(String, nullable=True)
    embedded_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    VALID_TYPES = {"user_profile", "interview_fact"}
    MAX_CONTENT_BYTES = 4096
