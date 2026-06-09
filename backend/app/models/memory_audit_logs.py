"""``memory_audit_logs``: append-only audit trail of every memory mutation.

The v3 successor to ``memory_audit_log`` (singular). Captures who/what/when/why
for both memory documents and ability states so a user can browse "what
changed about my memory" and ops can debug "why is this in here".

Two things it adds over the old table:

* Typed links to the touched row — ``memory_document_id`` /
  ``memory_ability_state_id`` (SET NULL on delete so history outlives the row).
* ``idempotency_key`` — so a retried extraction job can detect it already
  applied a patch and neither re-apply it nor double-write the audit trail.

``doc_type`` / ``topic`` are redundant snapshots kept for cheap filtering.

Write-heavy, read-rarely (the history UI). ``user_id`` is the stable
``users.id``.
"""
from __future__ import annotations

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

# Valid change provenances.
CHANGE_TYPES = ("patch_realtime", "patch_dreaming", "user_edit", "user_delete")


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
        String, ForeignKey("memory_documents.id", ondelete="SET NULL"), nullable=True,
    )
    memory_ability_state_id = Column(
        String,
        ForeignKey("memory_ability_states.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Redundant snapshots for cheap audit-query filtering.
    doc_type = Column(String, nullable=True)
    topic = Column(String, nullable=True)

    # patch_realtime / patch_dreaming / user_edit / user_delete.
    change_type = Column(String, nullable=False)

    # Provenance of the change.
    source_conversation_id = Column(String, nullable=True)
    source_interview_record_id = Column(String, nullable=True)
    # JSON {"start": seq, "end": seq} of the source message range, when known.
    source_message_range_json = Column(Text, nullable=True)

    # Dedup key for a memory write job (NULL for user edits / un-keyed writes).
    idempotency_key = Column(String, nullable=True)

    # Snapshots around the change (the document body, or — for an ability
    # state — its summary text).
    before_body = Column(Text, nullable=True)
    after_body = Column(Text, nullable=True)
    summary = Column(String, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
