"""Durable replacement histories; raw transcript is never deleted."""

from sqlalchemy import Column, ForeignKey, Integer, String
from app.db.database import Base
from app.db.types import JSONValue, UTCDateTime, utc_now


class ContextCheckpoint(Base):
    __tablename__ = "context_checkpoints"
    conversation_id = Column(
        String, ForeignKey("conversations.id", ondelete="CASCADE"), primary_key=True
    )
    # Empty scope = completed conversation window; turn id = in-flight window.
    scope = Column(String, primary_key=True, default="")
    version = Column(Integer, nullable=False, default=1)
    through_seq = Column(Integer, nullable=False, default=0)
    dispatch_generation = Column(Integer, nullable=False, default=0)
    window_id = Column(String(36), nullable=False)
    previous_window_id = Column(String(36), nullable=True)
    state = Column(JSONValue, nullable=False)
    updated_at = Column(UTCDateTime, nullable=False, default=utc_now)
