"""Append-only command receipts; old evidence and dependent QA remain auditable."""

from sqlalchemy import Column, ForeignKey, Index, Integer, String, UniqueConstraint
from app.db.database import Base
from app.db.types import JSONValue, UTCDateTime, utc_now


class TranscriptCorrection(Base):
    __tablename__ = "transcript_corrections"
    __table_args__ = (
        UniqueConstraint(
            "record_id", "request_id", name="uq_transcript_correction_request"
        ),
        Index(
            "ix_transcript_correction_history", "record_id", "created_at", "request_id"
        ),
    )
    id = Column(String(36), primary_key=True)
    record_id = Column(
        String, ForeignKey("interview_records.id", ondelete="CASCADE"), nullable=False
    )
    author_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    request_id = Column(String(36), nullable=False)
    # Soft IDs: audit survives an explicit re-extraction; all data shares record ownership.
    previous_transcript_id = Column(String, nullable=False)
    transcript_id = Column(String, nullable=False)
    command_sha256 = Column(String(64), nullable=False)
    command_json = Column(JSONValue, nullable=False)
    confirmed_roles_json = Column(JSONValue, nullable=False)
    invalidated_review_json = Column(JSONValue, nullable=False)
    review_generation = Column(Integer, nullable=False)
    created_at = Column(UTCDateTime, nullable=False, default=utc_now)
