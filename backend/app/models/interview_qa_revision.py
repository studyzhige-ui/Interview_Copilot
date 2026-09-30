"""Append-only correction receipts; deleted with the owning interview."""

import uuid
from sqlalchemy import Column, ForeignKey, Index, Integer, String
from app.db.database import Base
from app.db.types import JSONValue, UTCDateTime, utc_now


class InterviewQARevision(Base):
    __tablename__ = "interview_qa_revisions"
    __table_args__ = (
        Index("ix_interview_qa_revisions_record_created", "record_id", "created_at"),
    )
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    record_id = Column(
        String, ForeignKey("interview_records.id", ondelete="CASCADE"), nullable=False
    )
    # QA identity remains auditable when a later explicit re-extraction drops it.
    qa_id = Column(String, nullable=False)
    author_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    previous_version = Column(Integer, nullable=False)
    new_version = Column(Integer, nullable=False)
    before_json = Column(JSONValue, nullable=False)
    after_json = Column(JSONValue, nullable=False)
    invalidated_review_json = Column(JSONValue, nullable=True)
    created_at = Column(UTCDateTime, nullable=False, default=utc_now)
