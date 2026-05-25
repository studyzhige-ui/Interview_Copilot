"""Per-question rows for an InterviewRecord.

Each row is one question + answer + (optional) analysis. Promoted from the
analysis_json JSON blob to a first-class table so the review UI can render,
edit, and re-analyze a single Q&A without rewriting the whole record.
"""
import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)

from app.db.database import Base


def _generate_qa_id() -> str:
    return f"qa_{uuid.uuid4().hex[:12]}"


class InterviewQA(Base):
    __tablename__ = "interview_qa"
    # Composite — QAPanel renders QA list ordered by order_idx for one
    # record. See alembic 0001_baseline:277.
    __table_args__ = (
        Index("ix_interview_qa_record_order", "record_id", "order_idx"),
    )

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

    # Runtime Director metadata (filled live each turn during mock interview)
    # — `action`: which of the 7 director actions classified this turn
    # — `topic`:  snake_case topic tag for coverage tracking / review dedup
    # — `answer_quality_json`: { level, reason } as prior for finish analyzer
    # Index on topic is declared in alembic 0009; don't redeclare with index=True
    # here or autogenerate will produce a duplicate ix.
    action = Column(String(32), nullable=True)
    topic = Column(String(80), nullable=True)
    answer_quality_json = Column(JSON, nullable=True)

    # Analysis result (filled by orchestrator)
    score = Column(Integer, nullable=True)
    critique = Column(Text, nullable=True)
    improved_answer = Column(Text, nullable=True)
    key_points_json = Column(Text, nullable=True)
    analyzed_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
