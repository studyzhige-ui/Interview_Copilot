"""Transient in-progress state for a mock interview.

Lifecycle:
  - status='in_progress' while the user is answering questions
  - status='finished'    when the user clicks "End interview" — interview record
                          is then handed to the analysis orchestrator
  - status='abandoned'   when the user drops the session (or the system reaps
                          stale ones after a few days)

Final answers + analysis live in InterviewRecord + InterviewQA. This table is
purely the in-flight scratchpad.
"""
import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text

from app.db.database import Base


def _generate_session_id() -> str:
    return f"mis_{uuid.uuid4().hex[:12]}"


class MockInterviewSession(Base):
    __tablename__ = "mock_interview_sessions"

    id = Column(String, primary_key=True, default=_generate_session_id)
    # Stable users.id FK; the mock-finish writer resolves the caller's username
    # via app.core.user_identity.resolve_user_pk.
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False,
    )
    interview_record_id = Column(
        String,
        ForeignKey("interview_records.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    status = Column(String, index=True, nullable=False, default="in_progress")

    # Progress
    current_phase = Column(String, nullable=True)
    current_question_idx = Column(Integer, nullable=False, default=0)
    qa_buffer_json = Column(Text, nullable=True)       # JSON list of {question, answer, phase}
    plan_snapshot_json = Column(Text, nullable=True)   # JSON copy of generated plan

    # Configuration
    interviewer_style = Column(String, nullable=False, default="professional")
    voice_mode = Column(String, nullable=False, default="hybrid")

    last_activity_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    archived_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
