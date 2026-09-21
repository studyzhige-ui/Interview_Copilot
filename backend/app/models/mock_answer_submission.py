"""Durable per-intent receipts; reconnect is not authorization to regenerate."""

from sqlalchemy import CheckConstraint, Column, ForeignKey, Integer, String
from app.db.database import Base
from app.db.types import JSONValue, UTCDateTime, utc_now


class MockAnswerSubmission(Base):
    __tablename__ = "mock_answer_submissions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('in_progress', 'completed', 'unknown')",
            name="ck_mock_answer_submission_status",
        ),
    )
    record_id = Column(
        String, ForeignKey("interview_records.id", ondelete="CASCADE"), primary_key=True
    )
    request_id = Column(String(36), primary_key=True)
    question_message_id = Column(Integer, nullable=False)
    command_sha256 = Column(String(64), nullable=False)
    claim_generation = Column(Integer, nullable=False)
    status = Column(String(20), nullable=False)
    response_json = Column(JSONValue, nullable=True)
    created_at = Column(UTCDateTime, nullable=False, default=utc_now)
    updated_at = Column(UTCDateTime, nullable=False, default=utc_now, onupdate=utc_now)
