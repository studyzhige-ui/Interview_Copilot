"""Interview transcript: full text + timestamped segments for one interview.

Split out of ``interview_records`` (RFC §5 / §8): the transcript's bulk and
lifecycle differ from the record's, so it lives in its own table. An
``interview_records`` row points at its current transcript via ``transcript_id``
(a soft reference); the hard FK is here on ``record_id`` (CASCADE) so deleting a
record removes its transcripts.
"""
import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text

from app.db.database import Base


def _generate_transcript_id() -> str:
    return f"it_{uuid.uuid4().hex[:12]}"


class InterviewTranscript(Base):
    __tablename__ = "interview_transcripts"

    id = Column(String, primary_key=True, default=_generate_transcript_id, index=True)
    record_id = Column(
        String,
        ForeignKey("interview_records.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    # Stable users.id FK, redundant for query + safety filtering.
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    provider = Column(String, nullable=True)  # local_whisperx | openai | dashscope | mock_composed
    language = Column(String, nullable=True)
    text = Column(Text, nullable=True)
    segments_json = Column(Text, nullable=True)  # [{start,end,speaker,confidence,text}, ...]
    duration_seconds = Column(Float, nullable=True)
    status = Column(String, nullable=False, default="pending")  # pending|processing|ready|failed
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
