"""Operational model-call fence and durable partial-output record.

This is controller state, not a Product Context Source.  It is never injected
into prompts or Memory; it only lets recovery distinguish a late/duplicate
provider stream from the currently owned Turn generation.
"""

import uuid

from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from app.db.database import Base
from app.db.types import JSONValue as JSON
from app.db.types import UTCDateTime as DateTime
from app.db.types import utc_now


class AgentModelDispatch(Base):
    __tablename__ = "agent_model_dispatches"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running','completed','failed','cancelled','unknown')",
            name="ck_agent_model_dispatches_status",
        ),
        UniqueConstraint(
            "turn_id",
            "call_id",
            name="uq_agent_model_dispatches_turn_call",
        ),
    )

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    call_id = Column(String(128), nullable=False)
    turn_id = Column(
        String,
        ForeignKey("conversation_turns.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    dispatch_generation = Column(Integer, nullable=False)
    provider = Column(String(64), nullable=False)
    model = Column(String(255), nullable=False)
    request_fingerprint = Column(String(64), nullable=False)
    status = Column(String(16), nullable=False, default="running")
    partial_text = Column(Text, nullable=False, default="")
    usage_json = Column(JSON, nullable=False, default=dict)
    error_code = Column(String(128), nullable=True)
    started_at = Column(DateTime, nullable=False, default=utc_now)
    updated_at = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now)
    completed_at = Column(DateTime, nullable=True)
