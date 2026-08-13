"""Canonical user-level Long-term Agent Memory.

These rows contain low-authority personalization experience only.  They are
not Profile facts, precise History, instructions, execution state, or a second
Conversation/Project scoped Memory system.
"""

from __future__ import annotations

import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from app.db.database import Base
from app.db.types import JSONValue as JSON
from app.db.types import UTCDateTime as DateTime
from app.db.types import utc_now


class AgentMemorySetting(Base):
    __tablename__ = "agent_memory_settings"
    __table_args__ = (
        CheckConstraint("version >= 1", name="ck_agent_memory_settings_version"),
        UniqueConstraint("user_id", name="uq_agent_memory_settings_user"),
    )

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    recall_enabled = Column(Boolean, nullable=False, default=True)
    contribution_enabled = Column(Boolean, nullable=False, default=False)
    version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, nullable=False, default=utc_now)
    updated_at = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now)


class LongTermAgentMemory(Base):
    __tablename__ = "long_term_agent_memories"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active','invalidated','deleted')",
            name="ck_long_term_agent_memories_status",
        ),
        CheckConstraint(
            "valence IN ('effective','ineffective','mixed')",
            name="ck_long_term_agent_memories_valence",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_long_term_agent_memories_confidence",
        ),
        CheckConstraint("version >= 1", name="ck_long_term_agent_memories_version"),
        UniqueConstraint(
            "user_id",
            "semantic_key",
            name="uq_long_term_agent_memories_user_semantic_key",
        ),
        Index(
            "ix_long_term_agent_memories_user_status_updated",
            "user_id",
            "status",
            "updated_at",
        ),
    )

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    semantic_key = Column(String(120), nullable=False)
    content = Column(Text, nullable=False)
    applicability = Column(Text, nullable=False)
    tags_json = Column(JSON, nullable=False, default=list)
    valence = Column(String(16), nullable=False)
    confidence = Column(Float, nullable=False)
    status = Column(String(16), nullable=False, default="active")
    content_hash = Column(String(64), nullable=False)
    version = Column(Integer, nullable=False, default=1)
    formed_at = Column(DateTime, nullable=False, default=utc_now)
    last_confirmed_at = Column(DateTime, nullable=False, default=utc_now)
    last_recalled_at = Column(DateTime, nullable=True)
    recall_count = Column(Integer, nullable=False, default=0)
    status_reason = Column(Text, nullable=True)
    invalidated_at = Column(DateTime, nullable=True)
    deleted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now)
    updated_at = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now)


class LongTermAgentMemorySource(Base):
    """Provenance edge to exact History; not a generic source/evidence owner."""

    __tablename__ = "long_term_agent_memory_sources"
    __table_args__ = (
        UniqueConstraint(
            "memory_id",
            "source_turn_identity",
            name="uq_long_term_agent_memory_sources_memory_turn",
        ),
        Index(
            "ix_long_term_agent_memory_sources_turn_identity",
            "source_turn_identity",
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    memory_id = Column(
        String(36),
        ForeignKey("long_term_agent_memories.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    turn_id = Column(
        String,
        ForeignKey("conversation_turns.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_turn_identity = Column(String(36), nullable=False)
    source_conversation_identity = Column(String, nullable=False)
    support_quote_hash = Column(String(64), nullable=False)
    observed_at = Column(DateTime, nullable=False)
    source_deleted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now)


__all__ = [
    "AgentMemorySetting",
    "LongTermAgentMemory",
    "LongTermAgentMemorySource",
]
