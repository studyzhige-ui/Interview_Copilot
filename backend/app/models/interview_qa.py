"""Per-question rows for an InterviewRecord.

Each row is one question + answer + (optional) analysis. Promoted from the
analysis_json JSON blob to a first-class table so the review UI can render,
edit, and re-analyze a single Q&A without rewriting the whole record.
"""
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)

from app.db.database import Base


def _generate_qa_id() -> str:
    return f"qa_{uuid.uuid4().hex[:12]}"


class InterviewQA(Base):
    __tablename__ = "interview_qa"

    id = Column(String, primary_key=True, default=_generate_qa_id)
    record_id = Column(
        String,
        ForeignKey("interview_records.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    order_idx = Column(Integer, nullable=False, default=0)

    phase = Column(String, nullable=False, default="technical")
    phase_label = Column(String, nullable=True)

    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False, default="")
    question_summary = Column(String, nullable=True)
    is_follow_up = Column(Boolean, nullable=False, default=False)
    parent_qa_id = Column(String, ForeignKey("interview_qa.id"), nullable=True)

    # Grounding (which resume highlight / JD requirement this question probes)
    grounding_refs_json = Column(Text, nullable=True)
    follow_up_depth = Column(Integer, nullable=False, default=0)

    # Source segment timestamps (upload only)
    source_segment_start = Column(Float, nullable=True)
    source_segment_end = Column(Float, nullable=True)

    # Voice artifacts (P1+; columns reserved)
    question_audio_url = Column(String, nullable=True)
    answer_audio_url = Column(String, nullable=True)
    answer_input_mode = Column(String, nullable=False, default="text")

    # Analysis result (filled by orchestrator)
    score = Column(Integer, nullable=True)
    critique = Column(Text, nullable=True)
    improved_answer = Column(Text, nullable=True)
    key_points_json = Column(Text, nullable=True)
    analyzed_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
