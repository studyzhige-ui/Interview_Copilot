"""Durable composer drafts and immutable Conversation attachment references.

These rows model attachment *ingress*, not parsed documents or retrieval
sources.  Selecting a device file creates a draft that points at the existing
``FileAsset`` owner.  Only Conversation admission/claim creates an
``AttachmentRef`` tied to the accepted Turn.  Neither row grants RAG scope by
itself and neither duplicates file bytes or parsed content.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Column, ForeignKey, Index, Integer, String, UniqueConstraint

from app.db.database import Base
from app.db.types import UTCDateTime as DateTime
from app.db.types import utc_now


def generate_attachment_draft_id() -> str:
    return f"ad_{uuid.uuid4().hex}"


def generate_attachment_ref_id() -> str:
    return f"ar_{uuid.uuid4().hex}"


class ConversationAttachmentDraft(Base):
    """A durable Composer selection that has not entered Conversation scope.

    The draft owns no blob.  Removing it only revokes this selection; the
    referenced ``FileAsset`` keeps its independent lifecycle.
    """

    __tablename__ = "conversation_attachment_drafts"
    __table_args__ = (
        Index(
            "ix_attachment_drafts_conversation_removed",
            "conversation_id",
            "removed_at",
        ),
    )

    # May be supplied by the client as a stable retry identity.
    id = Column(String(128), primary_key=True, default=generate_attachment_draft_id)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    conversation_id = Column(
        String,
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    file_asset_id = Column(
        String,
        ForeignKey("file_assets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_document_id = Column(
        String,
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    created_at = Column(DateTime, nullable=False, default=utc_now)
    updated_at = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now)
    removed_at = Column(DateTime, nullable=True)


class ConversationAttachmentRef(Base):
    """Immutable attachment identity frozen by one successful Turn claim.

    ``conversation_id`` is the complete scope identity for this Stage; there
    is deliberately no polymorphic scope registry.  ``file_asset_version`` is
    a stable version token captured at claim time while ``file_asset_id``
    remains the real asset owner.
    """

    __tablename__ = "conversation_attachment_refs"
    __table_args__ = (
        UniqueConstraint("draft_id", name="uq_attachment_refs_draft"),
        UniqueConstraint(
            "conversation_id",
            "submission_id",
            "position",
            name="uq_attachment_refs_submission_position",
        ),
        UniqueConstraint(
            "turn_id",
            "position",
            name="uq_attachment_refs_turn_position",
        ),
        Index(
            "ix_attachment_refs_conversation_turn",
            "conversation_id",
            "turn_id",
        ),
        Index(
            "ix_attachment_refs_conversation_removed",
            "conversation_id",
            "removed_at",
        ),
    )

    id = Column(String(128), primary_key=True, default=generate_attachment_ref_id)
    # Admission idempotency/provenance identity, not a lifecycle dependency.
    # A claimed ref must survive later cleanup of its transient draft row.
    draft_id = Column(String(128), nullable=False)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    conversation_id = Column(
        String,
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    turn_id = Column(
        String,
        ForeignKey("conversation_turns.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Stable admission/input identity.  It intentionally is not a FK to
    # pending_submissions because an idle Conversation can admit directly.
    submission_id = Column(String(128), nullable=False, index=True)
    position = Column(Integer, nullable=False)
    file_asset_id = Column(
        String,
        ForeignKey("file_assets.id"),
        nullable=False,
        index=True,
    )
    source_document_id = Column(
        String,
        ForeignKey("knowledge_documents.id"),
        nullable=False,
        index=True,
    )
    file_asset_version = Column(String(96), nullable=False)
    display_name = Column(String(512), nullable=False)
    created_at = Column(DateTime, nullable=False, default=utc_now)
    # Revokes only this Conversation scope while retaining the immutable
    # claim/version identity for History.  It is used when a user explicitly
    # removes a failed source from a waiting Turn and continues without it.
    removed_at = Column(DateTime, nullable=True)


__all__ = [
    "ConversationAttachmentDraft",
    "ConversationAttachmentRef",
    "generate_attachment_draft_id",
    "generate_attachment_ref_id",
]
