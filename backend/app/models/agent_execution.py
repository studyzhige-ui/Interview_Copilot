from sqlalchemy import (
    Column,
    Float,
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


class AgentToolCall(Base):
    __tablename__ = "agent_tool_calls"
    __table_args__ = (
        UniqueConstraint("turn_id", "call_id", name="uq_agent_tool_calls_turn_call"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    call_id = Column(String(128), nullable=False)
    turn_id = Column(
        String,
        ForeignKey("conversation_turns.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    session_id = Column(
        String,
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tool_name = Column(String(128), nullable=False)
    effect = Column(String(32), nullable=False, default="unknown")
    arguments_json = Column(JSON, nullable=False, default=dict)
    timeout_seconds = Column(Float, nullable=False)
    status = Column(String(16), nullable=False, default="running")
    dispatch_generation = Column(Integer, nullable=False, default=1)
    policy_decision = Column(String(16), nullable=False, default="ask")
    policy_reason = Column(String(128), nullable=False, default="unknown_effect")
    result_json = Column(JSON, nullable=True)
    error = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=False, default=utc_now)
    completed_at = Column(DateTime, nullable=True)
    duration_ms = Column(Float, nullable=True)
