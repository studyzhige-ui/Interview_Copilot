from sqlalchemy import (
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
from app.db.types import JSONValue as JSON
from app.db.types import UTCDateTime as DateTime
from app.db.types import utc_now


class AgentToolCall(Base):
    __tablename__ = "agent_tool_calls"
    __table_args__ = (
        UniqueConstraint("turn_id", "call_id", name="uq_agent_tool_calls_turn_call"),
        Index(
            "ix_agent_tool_calls_turn_model_order",
            "turn_id",
            "model_call_order",
        ),
        Index(
            "ix_agent_tool_calls_turn_completion",
            "turn_id",
            "completion_sequence",
        ),
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
    # Stable model-issued order is separate from real handler completion order.
    # Historical rows remain null because that order cannot be reconstructed.
    model_step = Column(Integer, nullable=True)
    model_call_index = Column(Integer, nullable=True)
    model_call_order = Column(Integer, nullable=True)
    completion_sequence = Column(Integer, nullable=True)
    # Concrete execution identities are facts captured at call preflight. A
    # missing/unknown Provider or connection stays null rather than guessed.
    handler_identity = Column(String(255), nullable=True)
    provider_identity = Column(String(255), nullable=True)
    connection_identity = Column(String(255), nullable=True)
    # Bounded typed lifecycle events and declared receipt identities remain on
    # the canonical Tool Call; there is no second execution log.
    timeline_json = Column(JSON, nullable=False, default=list)
    receipt_refs_json = Column(JSON, nullable=False, default=list)
    # Canonical, bounded ``type:value`` resources touched by this call.  This
    # stays on the ToolCall owner so unresolved side effects can fence later
    # calls across Turns and Conversations without a second resource registry.
    resource_identities_json = Column(JSON, nullable=False, default=list)
    result_json = Column(JSON, nullable=True)
    error = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=False, default=utc_now)
    completed_at = Column(DateTime, nullable=True)
    duration_ms = Column(Float, nullable=True)
