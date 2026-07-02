"""Session-scoped task tracking (Claude Code V2 TaskCreate/Update alignment).

Each task belongs to a conversation session and tracks a discrete unit of
work the agent plans to complete.  Tasks persist across turns within a
session so the agent (and user) can see progress over multi-turn workflows.
"""
from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from app.db.database import Base


class SessionTask(Base):
    __tablename__ = "session_tasks"
    __table_args__ = (
        UniqueConstraint("session_id", "task_id", name="uq_session_tasks_session_task"),
        Index("ix_session_tasks_session_status", "session_id", "status"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(
        String,
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    task_id = Column(Integer, nullable=False)
    subject = Column(String, nullable=False)
    description = Column(Text, nullable=False, default="")
    status = Column(String, nullable=False, default="pending")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
