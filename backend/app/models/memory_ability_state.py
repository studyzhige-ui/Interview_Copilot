"""Legacy inferred ability rows retained for Stage 2 AbilitySignal migration.

The old automatic Memory writers and search index are disabled. A bounded
direct read may keep existing diagnostics visible during migration, but these
rows are not Long-term Agent Memory and never enter Context or Recall.
"""

from __future__ import annotations

import uuid

from sqlalchemy import (
    Column,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)

from app.db.database import Base
from app.db.types import JSONValue, utc_now
from app.db.types import UTCDateTime as DateTime

# Kind of ability the topic represents.
SKILL_TYPES = (
    "knowledge_topic",
    "system_design",
    "behavioral",
    "communication",
    "project_deep_dive",
)
# Mastery ladder, weakest → strongest.
MASTERY_LEVELS = ("weak", "improving", "stable", "strong")


def generate_ability_state_id() -> str:
    return f"mas_{uuid.uuid4().hex[:12]}"


class MemoryAbilityState(Base):
    __tablename__ = "memory_ability_states"
    __table_args__ = (
        # "One active state per (user, topic, skill_type)" — uniqueness applies
        # only to live rows; archived rows keep the history and are excluded.
        Index(
            "uq_ability_state_active",
            "user_id",
            "topic",
            "skill_type",
            unique=True,
            postgresql_where=text("archived_at IS NULL"),
            sqlite_where=text("archived_at IS NULL"),
        ),
        # "Show me this user's weak/improving topics" — the diagnostics read.
        Index("ix_ability_state_user_mastery", "user_id", "mastery_level"),
    )

    id = Column(String, primary_key=True, default=generate_ability_state_id)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Free-text subject, e.g. "Redis 缓存穿透", "MySQL 索引", "项目深挖".
    topic = Column(String, nullable=False)
    # knowledge_topic / system_design / behavioral / communication /
    # project_deep_dive (see SKILL_TYPES).
    skill_type = Column(String, nullable=False)
    # weak / improving / stable / strong (see MASTERY_LEVELS). Always set by
    # the retired extraction pipeline; the default was a placeholder for a
    # partial write.
    mastery_level = Column(String, nullable=False, default="improving")
    # Evidence-derived continuous score. NULL means the state predates the
    # continuous rubric or has no assessable performance evidence; it must not
    # be silently replaced with a mastery-level midpoint.
    ability_score = Column(Float, nullable=True)
    score_version = Column(String(32), nullable=True)
    # Short prose describing the user's current state and main gaps. NOT a full
    # knowledge answer.
    summary = Column(Text, nullable=True)
    # JSON list of evidence pointers, e.g.
    # ``[{"type": "interview_qa", "id": "qa_x"}]``. Cleaned/anonymised when the
    # referenced business record is deleted (the state itself survives).
    evidence_refs_json = Column(JSONValue, nullable=True)
    # Legacy text formerly copied to a Milvus index; no active index writer.
    search_text = Column(Text, nullable=True)
    # Most recent evidence timestamp — drives staleness.
    last_evidence_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(
        DateTime,
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )
    # Set when the state is retired (superseded or no longer relevant); NULL =
    # active. Archiving (not hard delete) keeps the audit trail coherent.
    archived_at = Column(DateTime, nullable=True)
