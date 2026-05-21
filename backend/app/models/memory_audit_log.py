"""Append-only audit trail of every memory mutation.

Captures who/what/when/why so a user can browse "what changed about my
memory recently" and ops can debug "why is this fact in here". Also
needed to support the future undo / history-view UI.

This table is write-heavy and read-rarely (mostly for the UI). Indexes
are minimal — user_id + created_at + doc_type — to keep writes cheap.

Retention isn't enforced at the model level. A future cleanup job can
drop rows older than N days if the table grows too large.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, Index, String, Text

from app.db.database import Base


def _generate_audit_id() -> str:
    return f"aud_{uuid.uuid4().hex[:12]}"


class MemoryAuditLog(Base):
    __tablename__ = "memory_audit_log"

    id = Column(String, primary_key=True, default=_generate_audit_id)
    user_id = Column(String, nullable=False, index=True)

    # Which doc was touched:
    #   user_profile / knowledge / strategy / habit
    doc_type = Column(String, nullable=False, index=True)
    # For knowledge_doc, the topic name (e.g. "Redis"). NULL for single-doc types.
    topic = Column(String, nullable=True)

    # What kind of change:
    #   patch_realtime  — realtime extraction wrote
    #   patch_dreaming  — dreaming worker wrote
    #   user_edit       — user manually edited via API
    #   user_delete     — user deleted (knowledge doc topic)
    #   migration       — historical migration script wrote
    change_type = Column(String, nullable=False)

    # Source record for dreaming / per-interview attribution. NULL for
    # everything else.
    source_record_id = Column(String, nullable=True, index=True)
    source_session_id = Column(String, nullable=True)

    # Full body before/after the change. Bounded by doc size which we
    # already cap. Empty string when not applicable (e.g. create).
    before_body = Column(Text, nullable=True)
    after_body = Column(Text, nullable=True)

    # Human-readable one-liner describing the change (e.g. "added 1
    # fact, updated 2"). Surfaced in the UI history view.
    summary = Column(String, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        # Compound index for the "browse my history" view that filters
        # by user and orders newest-first.
        Index("ix_memory_audit_user_created", "user_id", "created_at"),
    )
