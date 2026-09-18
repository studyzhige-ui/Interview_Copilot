"""Durable, user-isolated jobs and read receipts for the memory lifecycle."""

from sqlalchemy import Column, ForeignKey, Integer, String, Text

from app.db.database import Base
from app.db.types import JSONValue as JSON, UTCDateTime as DateTime, utc_now


class MemoryExtraction(Base):
    __tablename__ = "memory_extractions"

    # Identity survives source deletion; payload does not.
    turn_id = Column(String, primary_key=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    conversation_id = Column(String, nullable=False, index=True)
    status = Column(String(24), nullable=False, default="pending", index=True)
    lease_token = Column(String(36), nullable=True)
    lease_until = Column(DateTime, nullable=True)
    attempts = Column(Integer, nullable=False, default=0)
    retry_at = Column(DateTime, nullable=True)
    error_code = Column(String(80), nullable=True)
    source_hash = Column(String(64), nullable=False)
    summary = Column(Text, nullable=False, default="")
    candidates_json = Column(JSON, nullable=False, default=list)
    observed_at = Column(DateTime, nullable=False)
    generated_at = Column(DateTime, nullable=False, default=utc_now)


class MemoryWorkspace(Base):
    __tablename__ = "memory_workspaces"

    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    lease_token = Column(String(36), nullable=True)
    lease_until = Column(DateTime, nullable=True)
    status = Column(String(24), nullable=False, default="pending")
    attempts = Column(Integer, nullable=False, default=0)
    retry_at = Column(DateTime, nullable=True)
    error_code = Column(String(80), nullable=True)
    input_hash = Column(String(64), nullable=False, default="")
    revision = Column(Integer, nullable=False, default=0)
    # A generated navigation index, never an authoritative user profile.
    index_json = Column(JSON, nullable=False, default=list)
    updated_at = Column(DateTime, nullable=False, default=utc_now)


class MemoryReadReceipt(Base):
    __tablename__ = "memory_read_receipts"

    id = Column(String(36), primary_key=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    turn_id = Column(
        String,
        ForeignKey("conversation_turns.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    memory_id = Column(
        String(36),
        ForeignKey("long_term_agent_memories.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    memory_version = Column(Integer, nullable=False)
    # Exposure, model citation, and explicit feedback are separate signals.
    cited_at = Column(DateTime, nullable=True)
    feedback = Column(String(16), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now)
