"""Optional plan-execute state for one complex Conversation Turn.

AgentTask is runtime plan visibility, not a product-domain task or a second
Turn outcome.  Exact Tool calls, application results, and Artifact contents
remain with their authoritative owners; phase references contain identities
only.
"""

from __future__ import annotations

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


def _task_id() -> str:
    return f"at_{uuid.uuid4().hex}"


class AgentTask(Base):
    """The single optional flat plan owned by a complex Turn."""

    __tablename__ = "agent_tasks"
    __table_args__ = (
        CheckConstraint("version >= 1", name="ck_agent_tasks_version_positive"),
        UniqueConstraint("turn_id", name="uq_agent_tasks_turn"),
    )

    id = Column(String(35), primary_key=True, default=_task_id)
    turn_id = Column(
        String,
        ForeignKey("conversation_turns.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    objective = Column(Text, nullable=False)
    completion_conditions_json = Column(JSON, nullable=False)
    phases_json = Column(JSON, nullable=False)
    version = Column(Integer, nullable=False, default=1)
    creation_idempotency_key = Column(String(200), nullable=False)
    creation_fingerprint = Column(String(64), nullable=False)
    created_at = Column(DateTime, nullable=False, default=utc_now)
    updated_at = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now)
    frozen_at = Column(DateTime, nullable=True)


class AgentTaskRevision(Base):
    """Small append-only CAS/idempotency record for a plan revision.

    This does not duplicate a plan snapshot.  Exact model/tool interactions
    remain Interaction Records; the row proves which plan version a mutation
    produced and which phase identities it declared changed.
    """

    __tablename__ = "agent_task_revisions"
    __table_args__ = (
        CheckConstraint(
            "from_version >= 1 AND to_version = from_version + 1",
            name="ck_agent_task_revisions_version_step",
        ),
        UniqueConstraint(
            "agent_task_id",
            "idempotency_key",
            name="uq_agent_task_revisions_idempotency",
        ),
        UniqueConstraint(
            "agent_task_id",
            "to_version",
            name="uq_agent_task_revisions_to_version",
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_task_id = Column(
        String(35),
        ForeignKey("agent_tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    idempotency_key = Column(String(200), nullable=False)
    request_fingerprint = Column(String(64), nullable=False)
    from_version = Column(Integer, nullable=False)
    to_version = Column(Integer, nullable=False)
    reason = Column(Text, nullable=False)
    changed_phase_ids_json = Column(JSON, nullable=False)
    created_at = Column(DateTime, nullable=False, default=utc_now)


__all__ = ["AgentTask", "AgentTaskRevision"]
