"""Legacy mixed-memory audit rows retained only as migration provenance.

Stage 0 has no runtime producer or public audit API for this table. Stage 2 may
read it while classifying old data, but it is not Interaction History and is
never a Context or Recall source.
"""

from __future__ import annotations

import uuid

from sqlalchemy import (
    Column,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)

from app.db.database import Base
from app.db.types import JSONValue, utc_now
from app.db.types import UTCDateTime as DateTime

# Historical values emitted by the retired writers. They remain only so Stage
# 2 can interpret old audit rows during migration.
CHANGE_TYPES = (
    "patch_realtime",
    "patch_dreaming",
    "user_edit",
    "user_delete",
    "compaction_rewrite",
)


def generate_audit_id() -> str:
    return f"aud_{uuid.uuid4().hex[:12]}"


class MemoryAuditEntry(Base):
    __tablename__ = "memory_audit_logs"
    __table_args__ = (
        # "Browse my history" — filter by user, newest first.
        Index("ix_memory_audit_logs_user_created", "user_id", "created_at"),
        # Idempotency: a retried job's key collides and the second apply is
        # skipped. NULLs are distinct (multiple un-keyed entries allowed).
        Index("uq_memory_audit_logs_idem", "idempotency_key", unique=True),
    )

    id = Column(String, primary_key=True, default=generate_audit_id)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Typed link to the touched row (exactly one is set for a normal patch).
    # SET NULL so deleting a document/state keeps its audit history.
    memory_document_id = Column(
        String,
        ForeignKey("memory_documents.id", ondelete="SET NULL"),
        nullable=True,
    )
    memory_ability_state_id = Column(
        String,
        ForeignKey("memory_ability_states.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Redundant snapshots for cheap audit-query filtering.
    doc_type = Column(String, nullable=True)
    topic = Column(String, nullable=True)

    # Historical producer action.
    change_type = Column(String, nullable=False)

    # Provenance of the change.
    source_conversation_id = Column(String, nullable=True)
    source_interview_record_id = Column(String, nullable=True)
    # JSON {"start": seq, "end": seq} of the source message range, when known.
    source_message_range_json = Column(JSONValue, nullable=True)

    # Historical writer idempotency key.
    idempotency_key = Column(String, nullable=True)

    # Snapshots around the change (the document body, or — for an ability
    # state — its summary text).
    before_body = Column(Text, nullable=True)
    after_body = Column(Text, nullable=True)
    summary = Column(String, nullable=True)

    created_at = Column(DateTime, default=utc_now, nullable=False)
