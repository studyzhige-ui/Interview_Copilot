"""Minimal reconciliation tombstones for deleted Conversation Tool calls.

Deleting a Conversation removes its prompt, messages, Turn state, attachments,
and ordinary Tool history.  A side-effecting call whose outcome is still
unknown is the one exception: its call identity and provider receipt
correlation must survive long enough to reconcile a late result.  This table is
deliberately *not* a recoverable Conversation or a second History store.
"""

from __future__ import annotations


import uuid

from sqlalchemy import Column, ForeignKey, Index, Integer, String, UniqueConstraint

from app.db.database import Base
from app.db.types import JSONValue as JSON
from app.db.types import UTCDateTime as DateTime
from app.db.types import utc_now


class ConversationDeletionReceipt(Base):
    __tablename__ = "conversation_deletion_receipts"

    __table_args__ = (
        UniqueConstraint(
            "deleted_conversation_id",
            "turn_id",
            "call_id",
            name="uq_conversation_deletion_receipt_call",
        ),
        Index(
            "ix_conversation_deletion_receipts_user_status",
            "user_id",
            "status",
            "created_at",
        ),
    )

    id = Column(String(64), primary_key=True, default=lambda: f"cdr_{uuid.uuid4().hex}")
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # These identities intentionally have no FK: their owners are deleted in
    # the same transaction that inserts this bounded tombstone.
    deleted_conversation_id = Column(String(128), nullable=False, index=True)
    turn_id = Column(String(128), nullable=False)
    call_id = Column(String(128), nullable=False)
    tool_name = Column(String(128), nullable=False)
    effect = Column(String(32), nullable=False)
    dispatch_generation = Column(Integer, nullable=False)
    status = Column(String(24), nullable=False, default="unknown", index=True)
    resource_identities_json = Column(JSON, nullable=False, default=list)
    # Whitelisted receipt / request identifiers only.  Never arguments, prompt,
    # full Tool Result, user content, provider secret, or arbitrary error text.
    correlation_json = Column(JSON, nullable=False, default=dict)
    reason = Column(String(64), nullable=False, default="conversation_deleted")
    created_at = Column(DateTime, nullable=False, default=utc_now)
    resolved_at = Column(DateTime, nullable=True)
    retain_until = Column(DateTime, nullable=False, index=True)


__all__ = ["ConversationDeletionReceipt"]
