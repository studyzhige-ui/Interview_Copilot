"""Ephemeral state for the user's one active mock interview.

The row exists only while the interview can be resumed. ``InterviewRecord``
owns the durable lifecycle, conversation messages own the transcript, and
``InterviewQA`` owns reviewed results. Once the review task is accepted this
row is deleted; a dispatch failure leaves it in place so the interview remains
resumable.
"""

from sqlalchemy import (
    Column,
    ForeignKey,
    Integer,
    String,
)

from app.db.database import Base
from app.db.types import JSONValue
from app.db.types import UTCDateTime as DateTime
from app.db.types import utc_now


class MockInterviewRuntime(Base):
    __tablename__ = "mock_interview_runtime"
    interview_record_id = Column(
        String,
        ForeignKey("interview_records.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    conversation_id = Column(
        String,
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    current_stage_key = Column(String, nullable=False)
    current_question_message_id = Column(Integer, nullable=False)
    # Non-null while one request owns the current question and is generating
    # the next interviewer turn. A timestamp (rather than a boolean) lets a
    # later retry reclaim a lease left behind by a killed API process.
    answer_claimed_at = Column(DateTime, nullable=True)
    # Personalized stage guidance, needed only while generating live turns.
    plan_json = Column(JSONValue, nullable=False)
    interviewer_style = Column(String, nullable=False)
    target_question_count = Column(Integer, nullable=False)
    last_activity_at = Column(DateTime, default=utc_now, nullable=False)
