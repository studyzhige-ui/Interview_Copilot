"""Canonical user-confirmed career profile and its owned draft changes.

``CareerProfile`` is the only product owner.  Target directions are physical
children with stable identities, not a second aggregate or Context source.
Draft changes are reviewable writes inside this aggregate; they are not facts
until explicitly accepted and never become a generic candidate system.
"""

from __future__ import annotations

import uuid

from sqlalchemy import (
    CheckConstraint,
    Column,
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


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


class CareerProfile(Base):
    """One user-visible, user-confirmed profile per user."""

    __tablename__ = "career_profiles"
    __table_args__ = (
        CheckConstraint("version >= 1", name="ck_career_profiles_version"),
        UniqueConstraint("user_id", name="uq_career_profiles_user"),
    )

    id = Column(String(35), primary_key=True, default=lambda: _id("cp"))
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    personal_facts_json = Column(JSON, nullable=False, default=list)
    version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, nullable=False, default=utc_now)
    updated_at = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now)


class CareerProfileDirection(Base):
    """A stable child identity inside CareerProfile, never TargetDirection."""

    __tablename__ = "career_profile_directions"
    __table_args__ = (
        CheckConstraint(
            "lifecycle IN ('exploring', 'active', 'paused', 'archived')",
            name="ck_career_profile_directions_lifecycle",
        ),
        CheckConstraint(
            "confirmed_source_kind IN "
            "('user_edit', 'conversation_message', 'draft_acceptance')",
            name="ck_career_profile_directions_confirmed_source",
        ),
        CheckConstraint(
            "priority >= 0",
            name="ck_career_profile_directions_priority",
        ),
        Index(
            "ix_career_profile_directions_profile_lifecycle_priority",
            "career_profile_id",
            "lifecycle",
            "priority",
        ),
    )

    id = Column(String(36), primary_key=True, default=lambda: _id("cpd"))
    career_profile_id = Column(
        String(35),
        ForeignKey("career_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    label = Column(String(160), nullable=False)
    criteria_json = Column(JSON, nullable=False, default=dict)
    lifecycle = Column(String(16), nullable=False, default="exploring")
    priority = Column(Integer, nullable=False, default=0)
    confirmed_source_kind = Column(String(32), nullable=False)
    confirmed_source_id = Column(String(128), nullable=True)
    confirmed_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, nullable=False, default=utc_now)
    updated_at = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now)


class CareerProfileDraftChange(Base):
    """One reviewable, non-canonical change-set owned by CareerProfile."""

    __tablename__ = "career_profile_draft_changes"
    __table_args__ = (
        CheckConstraint(
            "source_kind IN ('resume', 'conversation_message', 'model_inference')",
            name="ck_career_profile_drafts_source_kind",
        ),
        CheckConstraint(
            "status IN ('pending', 'accepted', 'rejected')",
            name="ck_career_profile_drafts_status",
        ),
        CheckConstraint(
            "base_profile_version >= 1 AND version >= 1",
            name="ck_career_profile_drafts_versions",
        ),
        Index(
            "ix_career_profile_drafts_profile_status_created",
            "career_profile_id",
            "status",
            "created_at",
        ),
    )

    id = Column(String(37), primary_key=True, default=lambda: _id("cpdc"))
    career_profile_id = Column(
        String(35),
        ForeignKey("career_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_kind = Column(String(32), nullable=False)
    source_id = Column(String(128), nullable=False)
    base_profile_version = Column(Integer, nullable=False)
    proposed_facts_json = Column(JSON, nullable=False, default=list)
    proposed_directions_json = Column(JSON, nullable=False, default=list)
    status = Column(String(16), nullable=False, default="pending")
    resolution_note = Column(Text, nullable=True)
    version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, nullable=False, default=utc_now)
    resolved_at = Column(DateTime, nullable=True)


__all__ = [
    "CareerProfile",
    "CareerProfileDirection",
    "CareerProfileDraftChange",
]
