"""File-source membership owned by one existing InterviewRecord.

The row is the explicit scope grant behind the product's "add to this
debrief" action.  It does not own file bytes, parsed text, or a generic
Project/Source lifecycle: those remain on ``FileAsset`` and
``KnowledgeDocument``.  Origin identities are retained as immutable strings
so deleting the source Conversation cannot rewrite the promoted source's
provenance.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Column, ForeignKey, Index, Integer, String, UniqueConstraint

from app.db.database import Base
from app.db.types import UTCDateTime as DateTime
from app.db.types import utc_now


def generate_interview_source_ref_id() -> str:
    return f"isr_{uuid.uuid4().hex}"


class InterviewSourceRef(Base):
    """One FileAsset/version explicitly visible to a Debrief Project scope."""

    __tablename__ = "interview_source_refs"
    __table_args__ = (
        UniqueConstraint(
            "interview_record_id",
            "file_asset_id",
            "file_asset_version",
            name="uq_interview_source_refs_record_asset_version",
        ),
        Index(
            "ix_interview_source_refs_record_removed",
            "interview_record_id",
            "removed_at",
        ),
    )

    id = Column(String(128), primary_key=True, default=generate_interview_source_ref_id)
    interview_record_id = Column(
        String,
        ForeignKey("interview_records.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    file_asset_id = Column(
        String,
        ForeignKey("file_assets.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    source_document_id = Column(
        String,
        ForeignKey("knowledge_documents.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    file_asset_version = Column(String(96), nullable=False)
    display_name = Column(String(512), nullable=False)

    # Deliberately not cascading foreign keys.  They answer where the grant
    # came from after that local Conversation/AttachmentRef has been deleted.
    origin_conversation_id = Column(String(128), nullable=False)
    origin_attachment_ref_id = Column(String(128), nullable=False)

    created_at = Column(DateTime, nullable=False, default=utc_now)
    removed_at = Column(DateTime, nullable=True)


__all__ = ["InterviewSourceRef", "generate_interview_source_ref_id"]
