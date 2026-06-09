import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, Text

from app.db.database import Base


def _generate_record_id() -> str:
    return f"ir_{uuid.uuid4().hex[:12]}"


class InterviewRecord(Base):
    """A complete record of one interview (real upload or mock simulation).

    Unified data model that covers both:
      - source='upload': user-uploaded audio/video that goes through ASR +
        diarization + LLM analysis.
      - source='mock'  : AI-driven mock interview with structured Q&A. Skips
        ASR; the QA is composed from the session buffer.

    Per-question rows live in InterviewQA. analysis_json holds only the
    top-level summary (overall + phase_summary).
    """

    __tablename__ = "interview_records"
    # Composite indexes serving the two list paths:
    #   * user_created — record list ordered by created_at desc
    #   * user_last_dreamed — dreaming-worker selection
    # See alembic 0001_baseline:96 and 0002_memory_v3_schema:162.
    __table_args__ = (
        Index("ix_interview_records_user_created", "user_id", "created_at"),
        Index(
            "ix_interview_records_user_last_dreamed",
            "user_id",
            "last_dreamed_at",
        ),
    )

    id = Column(String, primary_key=True, default=_generate_record_id, index=True)
    # Stable users.id FK (CLEANUP #2). The API + record service resolve the
    # caller's username via resolve_user_pk; the dreaming worker bridges this
    # back to the username for the memory dispatch (memory keys on username).
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False,
    )
    source = Column(String, nullable=False)  # "upload" | "mock"

    title = Column(String, default="未命名面试")
    # Primary interview category (后端/算法/系统设计…) for list filtering/display.
    category = Column(String, nullable=True)
    tag = Column(String(32), nullable=True)

    # File-asset references (all → file_assets.id). Renamed from the legacy
    # *_upload_id naming when the upload domain unified on file_assets.
    audio_file_asset_id = Column(String, nullable=True)
    # Ad-hoc resume file uploaded just for THIS interview's context (NOT a
    # personal `resumes` entity). See resume_source to disambiguate.
    resume_file_asset_id = Column(String, nullable=True)
    jd_file_asset_id = Column(String, nullable=True)

    # Personal-resume linkage. ``resume_id`` references the `resumes` entity
    # used as context; ``resume_source`` records where the resume came from.
    # History reads the *_snapshot fields below — never re-reads `resumes`, so
    # editing/deleting a personal resume can't rewrite a past interview.
    resume_id = Column(String, ForeignKey("resumes.id", ondelete="SET NULL"), nullable=True)
    resume_source = Column(String, nullable=True)  # personal_resume | context_upload | none
    resume_title_snapshot = Column(String, nullable=True)

    # Snapshots (immutable; survive source file/resume deletion)
    resume_text_snapshot = Column(Text, nullable=True)
    jd_text_snapshot = Column(Text, nullable=True)
    resume_structured_snapshot_json = Column(Text, nullable=True)  # ResumeEvidence w/ ref_ids
    jd_structured_json = Column(Text, nullable=True)               # JDRequirements w/ ref_ids

    # Current transcript reference — full text/segments live in the dedicated
    # interview_transcripts table (soft ref; the hard FK is on that table).
    transcript_id = Column(String, index=True, nullable=True)
    interview_plan = Column(Text, nullable=True)            # generate_plan() output (mock only)

    # Top-level analysis result (per-question rows in interview_qa)
    analysis_json = Column(Text, nullable=True)
    analysis_schema_version = Column(Integer, nullable=False, default=2)

    # 200-400 字浓缩摘要，由分析 pipeline 末尾的 LLM 生成。注入到
    # debrief 类 chat session 的 record_context 槽，作为该 record 下
    # 每条 session 的恒定前导上下文。在 record 生命周期内不变 → 命中
    # prompt cache。NULL = 该 record 还没跑完分析（mock 模式或者上传
    # 后被取消的 record）。
    debrief_summary = Column(Text, nullable=True)

    # Status & progress. Upload: pending→transcribing→analyzing→completed/failed.
    # Mock (wired in CONVERSATION-MOCK): mock_in_progress→processing_review→
    # review_ready/review_failed; cancelled on abandon.
    status = Column(String, index=True, default="pending", nullable=False)
    analyzed_qa_count = Column(Integer, nullable=False, default=0)
    celery_task_id = Column(String, nullable=True)
    error_message = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)

    # Dreaming cursor: when the dreaming worker last distilled this
    # record's debrief sessions into long-term memory docs. NULL = never
    # dreamed yet. Workers skip records where ``updated_at <=
    # last_dreamed_at`` (no new content since last dream). See
    # ``app.services.memory.dreaming_worker`` for the selection logic.
    last_dreamed_at = Column(DateTime, nullable=True)
