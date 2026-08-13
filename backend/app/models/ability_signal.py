"""Inferred ability state grounded in direct references to real owners."""

from __future__ import annotations

import uuid

from sqlalchemy import (
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
from app.db.types import UTCDateTime as DateTime
from app.db.types import utc_now


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


class AbilitySignal(Base):
    """A time-bound, uncertain inference; never a Profile fact or Memory."""

    __tablename__ = "ability_signals"
    __table_args__ = (
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_ability_signals_confidence_range",
        ),
        CheckConstraint(
            "status IN ('active', 'disputed', 'invalidated', 'superseded')",
            name="ck_ability_signals_status",
        ),
        CheckConstraint("version >= 1", name="ck_ability_signals_version"),
        CheckConstraint(
            "scope_kind IN ('general', 'career_direction', "
            "'job_opportunity', 'interview_record')",
            name="ck_ability_signals_scope_kind",
        ),
        CheckConstraint(
            "(scope_kind = 'general' AND scope_ref_id IS NULL) OR "
            "(scope_kind <> 'general' AND scope_ref_id IS NOT NULL)",
            name="ck_ability_signals_scope_shape",
        ),
        Index(
            "ix_ability_signals_user_status_formed",
            "user_id",
            "status",
            "formed_at",
        ),
        Index(
            "ix_ability_signals_user_topic_type",
            "user_id",
            "topic",
            "signal_type",
        ),
    )

    id = Column(String(35), primary_key=True, default=lambda: _id("as"))
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    topic = Column(String(200), nullable=False)
    signal_type = Column(String(64), nullable=False)
    level = Column(String(64), nullable=True)
    score = Column(Float, nullable=True)
    summary = Column(Text, nullable=False)
    confidence = Column(Float, nullable=True)
    limitations = Column(Text, nullable=True)
    scope_kind = Column(String(32), nullable=False, default="general")
    scope_ref_id = Column(String(128), nullable=True)
    formed_at = Column(DateTime, nullable=False)
    rubric_version = Column(String(64), nullable=True)
    status = Column(String(16), nullable=False, default="active")
    status_reason = Column(Text, nullable=True)
    supersedes_signal_id = Column(
        String(35),
        ForeignKey("ability_signals.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, nullable=False, default=utc_now)
    updated_at = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now)
    status_changed_at = Column(DateTime, nullable=False, default=utc_now)


class AbilitySignalSourceRef(Base):
    """AbilitySignal-owned links; not a reusable Source/Evidence registry."""

    __tablename__ = "ability_signal_source_refs"
    __table_args__ = (
        CheckConstraint(
            "source_kind IN ('interview_record', 'interview_qa', "
            "'conversation_message', 'agent_tool_call', 'process_event', "
            "'artifact_version')",
            name="ck_ability_signal_sources_kind",
        ),
        UniqueConstraint(
            "ability_signal_id",
            "source_kind",
            "source_id",
            name="uq_ability_signal_sources_identity",
        ),
        Index(
            "ix_ability_signal_sources_owner",
            "source_kind",
            "source_id",
        ),
    )

    id = Column(String(37), primary_key=True, default=lambda: _id("assr"))
    ability_signal_id = Column(
        String(35),
        ForeignKey("ability_signals.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_kind = Column(String(32), nullable=False)
    source_id = Column(String(128), nullable=False)
    # A real version/revision token from the source owner, when it has one.
    source_version = Column(String(128), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now)


__all__ = ["AbilitySignal", "AbilitySignalSourceRef"]
