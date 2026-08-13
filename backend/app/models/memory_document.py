"""Legacy mixed-memory documents retained only for Stage 2 migration.

Runtime writers, HTTP mutation APIs, Context assembly and Recall must not use
this model. Rows need classification into their canonical owner before any
content may become CareerProfile, CopilotPreference or Long-term Agent Memory.
"""

from __future__ import annotations

import uuid

from sqlalchemy import (
    Column,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from app.db.database import Base
from app.db.types import UTCDateTime as DateTime
from app.db.types import utc_now

# Values present in the legacy table; they are migration classifiers, not
# canonical owners in the target architecture.
DOC_TYPES = ("user_profile", "learning_strategy")


def generate_memory_document_id() -> str:
    return f"mdoc_{uuid.uuid4().hex[:12]}"


class MemoryDocument(Base):
    __tablename__ = "memory_documents"
    __table_args__ = (
        # One document per type per user.
        UniqueConstraint("user_id", "doc_type", name="uq_memory_document_user_type"),
    )

    id = Column(String, primary_key=True, default=generate_memory_document_id)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # user_profile / learning_strategy (see DOC_TYPES).
    doc_type = Column(String, nullable=False)
    # Legacy markdown payload.
    body = Column(Text, nullable=False, default="")
    # Legacy denormalised preview.
    one_liner = Column(String, nullable=False, default="")
    # Last discussion timestamp recorded by the retired producer.
    last_discussed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(
        DateTime,
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )
