from __future__ import annotations

import uuid

from sqlalchemy import CheckConstraint, Column, ForeignKey, Index, Integer, String, text

from app.db.database import Base
from app.db.types import JSONValue as JSON
from app.db.types import UTCDateTime as DateTime
from app.db.types import utc_now


class AgentInteraction(Base):
    """One durable user decision/input awaited by an active Turn.

    Ownership is deliberately not copied onto this row.  The owning user and
    Conversation are authoritative on ``ConversationTurn`` and are checked by
    the service when the Interaction is read or resolved.
    """

    __tablename__ = "agent_interactions"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('clarification', 'connection', 'approval', 'client_readiness')",
            name="ck_agent_interactions_kind",
        ),
        CheckConstraint(
            "status IN ('pending', 'resolved', 'rejected', 'cancelled')",
            name="ck_agent_interactions_status",
        ),
        Index(
            "uq_agent_interactions_pending_turn",
            "turn_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
            sqlite_where=text("status = 'pending'"),
        ),
    )

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    turn_id = Column(
        String,
        ForeignKey("conversation_turns.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # The model-visible call identity (AgentToolCall.call_id), not its numeric
    # storage primary key.  Clarifications outside a Tool Call leave it NULL.
    tool_call_id = Column(String(128), nullable=True)
    kind = Column(String(32), nullable=False)
    status = Column(String(16), nullable=False, default="pending")
    request_json = Column(JSON, nullable=False)
    resolution_json = Column(JSON, nullable=True)
    version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, nullable=False, default=utc_now)
    resolved_at = Column(DateTime, nullable=True)


__all__ = ["AgentInteraction"]
