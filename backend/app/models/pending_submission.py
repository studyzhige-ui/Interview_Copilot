from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    Column,
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


class PendingSubmission(Base):
    """Durable user input waiting for Conversation admission.

    A pending row is ingress only: it is not a message or a turn until it is
    claimed while holding the owning Conversation lock.
    """

    __tablename__ = "pending_submissions"
    __table_args__ = (
        CheckConstraint(
            "execution_mode IN ('standard', 'auto')",
            name="ck_pending_submissions_execution_mode",
        ),
        UniqueConstraint(
            "conversation_id",
            "position",
            name="uq_pending_submissions_conversation_position",
        ),
        Index(
            "ix_pending_submissions_conversation_status_position",
            "conversation_id",
            "status",
            "position",
        ),
    )

    # Client-stable idempotency identity. Reusing it with different input is a
    # conflict; retrying the same version returns the original admission.
    id = Column(String(128), primary_key=True)
    conversation_id = Column(
        String,
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version = Column(Integer, nullable=False, default=1)
    position = Column(Integer, nullable=False)
    status = Column(String(16), nullable=False, default="pending")

    message = Column(Text, nullable=False)
    mode = Column(String(16), nullable=False)
    execution_mode = Column(
        String(16), nullable=False, default="standard", server_default="standard"
    )
    question_indexes_json = Column(JSON, nullable=False, default=list)
    attachments_json = Column(JSON, nullable=False, default=list)
    # Closed typed identities explicitly submitted by the user. Business
    # fields are never copied here; claim/execution reread each real owner.
    object_references_json = Column(JSON, nullable=False, default=list)
    source_client_id = Column(String(128), nullable=True)

    error = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now)
    updated_at = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now)
    claimed_at = Column(DateTime, nullable=True)


__all__ = ["PendingSubmission"]
