"""``mock_interview_runtime``: the live state of an in-progress mock interview.

A mock interview is a stateful flow that reuses the conversation message stream
for its turns. This table holds ONLY the in-flight runtime — where the
interview is right now (stage, plan, current question) — not the final scored
QA (that's ``interview_qa``) and not the chat transcript (that's the
conversation messages). It is the single home for the live mock runtime
(superseding the dropped ``conversations.mock_interview_state`` JSON blob and
the deprecated ``mock_interview_sessions`` archive table).

Lifecycle: the mock-start flow atomically creates an ``interview_records`` row
(``status="mock_in_progress"``), a ``conversations`` row
(``type="mock_interview"``), and one of these runtime rows
(``status="in_progress"``). On finish, the *record* advances
``processing_review`` → ``review_ready`` and the structured QA is frozen into
``interview_qa``; this *runtime* row carries its own status set (see below).

``user_id`` is the stable ``users.id`` FK; the runtime service resolves the
caller's username via ``app.core.user_identity.resolve_user_pk``.
"""
import uuid
from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)

from app.db.database import Base


def generate_runtime_id() -> str:
    return f"mir_{uuid.uuid4().hex[:12]}"


class MockInterviewRuntime(Base):
    __tablename__ = "mock_interview_runtime"
    __table_args__ = (
        # Resume the user's most recent in-progress mock after a refresh.
        Index("ix_mock_runtime_user_status", "user_id", "status"),
    )

    id = Column(String, primary_key=True, default=generate_runtime_id, index=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False,
    )
    interview_record_id = Column(
        String,
        ForeignKey("interview_records.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    conversation_id = Column(
        String, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=True,
    )
    # Runtime status: in_progress (live) → processing_review → completed,
    # or review_failed if scoring errors out.
    status = Column(String, index=True, nullable=False, default="in_progress")
    current_stage_key = Column(String, nullable=True)
    stage_index = Column(Integer, nullable=False, default=0)
    current_question_text = Column(Text, nullable=True)
    # The conversation message id of the question awaiting an answer — used to
    # reliably merge the QA pair when the interview ends.
    current_question_message_id = Column(Integer, nullable=True)
    # Frozen stage plan for THIS run (a template change can't affect a started
    # interview). Phase-1 template: self_intro / resume_project_deep_dive /
    # role_technical_assessment / candidate_questions.
    plan_json = Column(Text, nullable=True)
    plan_template_key = Column(String, nullable=False, default="general")
    interviewer_style = Column(String, nullable=False, default="professional")
    voice_mode = Column(String, nullable=False, default="hybrid")
    # started_at is the row's creation instant (the runtime is created at
    # mock-start); ended_at pairs with it for total duration. No separate
    # created_at — it would be identical to started_at for this table.
    started_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    ended_at = Column(DateTime, nullable=True)
    # Bumped on every answer (advance_runtime); drives "resume most-recent".
    last_activity_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False,
    )
