"""``memory_ability_states``: the user's long-term mastery state per topic.

One *active* row per ``(user, topic, skill_type)``. Replaces the old
``knowledge_docs`` table — but the model is different: knowledge_docs stored a
sectioned markdown body of "facts the user knows"; an ability state stores a
compact *judgement* of how the user is doing on a topic (mastery + a short
summary + evidence pointers), NOT the knowledge content itself (that belongs
to the knowledge base: ``knowledge_documents`` / ``document_chunks``).

It is distilled from interview QA, debrief conversations and general chat, but
never stores files, transcripts or full answers. Postgres is the fact source;
Milvus only holds an index copy of ``search_text`` + metadata so ability-state
retrieval can run as its own hybrid collection, in parallel with (but separate
from) knowledge retrieval.

``user_id`` is the stable ``users.id`` (resolved from the runtime username via
``app.core.user_identity.resolve_user_pk``).
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
    text,
)

from app.db.database import Base

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
            "user_id", "topic", "skill_type",
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
    # the extraction; the default is only a placeholder for a partial write.
    mastery_level = Column(String, nullable=False, default="improving")
    # Short prose describing the user's current state and main gaps. NOT a full
    # knowledge answer.
    summary = Column(Text, nullable=True)
    # JSON list of evidence pointers, e.g.
    # ``[{"type": "interview_qa", "id": "qa_x"}]``. Cleaned/anonymised when the
    # referenced business record is deleted (the state itself survives).
    evidence_refs_json = Column(Text, nullable=True)
    # topic + summary, newline-joined; indexed by the Milvus ability collection.
    search_text = Column(Text, nullable=True)
    # Most recent evidence timestamp — drives staleness.
    last_evidence_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False,
    )
    # Set when the state is retired (superseded or no longer relevant); NULL =
    # active. Archiving (not hard delete) keeps the audit trail coherent.
    archived_at = Column(DateTime, nullable=True)
