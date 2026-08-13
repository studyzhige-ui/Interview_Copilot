"""User-confirmed global Copilot collaboration preferences.

This is the only global preference owner. Conversation guidance remains on
``Conversation`` and debrief guidance remains on ``InterviewRecord``; this
table is deliberately not a polymorphic guidance registry.
"""

from __future__ import annotations

import uuid

from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)

from app.db.database import Base
from app.db.types import JSONValue as JSON
from app.db.types import UTCDateTime as DateTime
from app.db.types import utc_now


class CopilotPreference(Base):
    __tablename__ = "copilot_preferences"
    __table_args__ = (
        CheckConstraint("version >= 1", name="ck_copilot_preferences_version"),
        UniqueConstraint("user_id", name="uq_copilot_preferences_user"),
    )

    id = Column(
        String(35),
        primary_key=True,
        default=lambda: f"pref_{uuid.uuid4().hex}",
    )
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    instructions_json = Column(JSON, nullable=False, default=list)
    version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, nullable=False, default=utc_now)
    updated_at = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now)


__all__ = ["CopilotPreference"]
