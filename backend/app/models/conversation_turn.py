import uuid

from sqlalchemy import CheckConstraint, Column, ForeignKey, Integer, String, Text

from app.db.database import Base
from app.db.types import JSONValue as JSON
from app.db.types import UTCDateTime as DateTime
from app.db.types import utc_now


class ConversationTurn(Base):
    __tablename__ = "conversation_turns"
    __table_args__ = (
        CheckConstraint(
            "execution_mode IN ('standard', 'auto')",
            name="ck_conversation_turns_execution_mode",
        ),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    conversation_id = Column(
        String,
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    submission_id = Column(
        String(128),
        ForeignKey("pending_submissions.id", ondelete="SET NULL"),
        nullable=True,
        unique=True,
    )
    mode = Column(String(16), nullable=False)
    # Immutable policy-mode snapshot for this admitted Turn.
    execution_mode = Column(
        String(16), nullable=False, default="standard", server_default="standard"
    )
    message = Column(Text, nullable=False)
    question_indexes_json = Column(JSON, nullable=False, default=list)
    attachments_json = Column(JSON, nullable=False, default=list)
    # Frozen CurrentTurnAnchor identities. The runtime rereads their current
    # authoritative state instead of treating this transport snapshot as fact.
    object_references_json = Column(JSON, nullable=False, default=list)
    user_message_seq = Column(Integer, nullable=True)
    assistant_message_seq = Column(Integer, nullable=True)
    status = Column(String(16), nullable=False, default="pending")
    # Operational reason for a released waiting Turn.  It is not model
    # context and does not own task direction.
    waiting_reason = Column(String(32), nullable=True)
    # A durable, one-shot request to cancel this Turn and admit exactly one
    # queued submission.  Keeping the target on the active Turn avoids a
    # second interrupt state machine while still surviving worker/browser
    # disconnects.  The terminal handoff validates both identity and version.
    interrupt_submission_id = Column(
        String(128),
        ForeignKey("pending_submissions.id", ondelete="SET NULL"),
        nullable=True,
    )
    interrupt_submission_version = Column(Integer, nullable=True)
    # Incremented before each retry/resume dispatch. Tool completion updates
    # are fenced to this generation so a late worker cannot overwrite a newer
    # execution pass.
    dispatch_generation = Column(Integer, nullable=False, default=1)
    error = Column(Text, nullable=True)
    owner_id = Column(String(128), nullable=True, index=True)
    heartbeat_at = Column(DateTime, nullable=True, index=True)
    tool_snapshot_json = Column(JSON, nullable=False, default=dict)
    loaded_tool_schemas_json = Column(JSON, nullable=False, default=list)
    budget_json = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, default=utc_now)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
