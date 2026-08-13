import uuid

from sqlalchemy import CheckConstraint, Column, ForeignKey, Index, Integer, String, Text

from app.db.database import Base
from app.db.types import UTCDateTime as DateTime
from app.db.types import utc_now


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
    top-level report (overall, phase summary, radar and metadata).
    """

    __tablename__ = "interview_records"
    # Record list ordered by creation time.
    __table_args__ = (
        Index("ix_interview_records_user_created", "user_id", "created_at"),
        CheckConstraint(
            "debrief_guidance_version >= 0",
            name="ck_interview_records_debrief_guidance_version",
        ),
        CheckConstraint(
            "ability_signal_generation >= 0",
            name="ck_interview_records_ability_signal_generation",
        ),
    )

    id = Column(String, primary_key=True, default=_generate_record_id)
    # Stable users.id FK (CLEANUP #2). The API + record service resolve the
    # caller's username via resolve_user_pk.
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    source = Column(String, nullable=False)  # "upload" | "mock"

    # Real interviews usually belong to one concrete hiring process; mocks
    # may either practice for one process or remain general training.
    job_opportunity_id = Column(
        String(35),
        ForeignKey("job_opportunities.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

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
    resume_id = Column(
        String, ForeignKey("resumes.id", ondelete="SET NULL"), nullable=True
    )
    # Canonical personal-resume link. New writes use Artifact(kind=resume);
    # ``resume_id`` above remains only for immutable legacy references.
    resume_artifact_id = Column(
        String(128),
        ForeignKey("artifacts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    resume_artifact_version_id = Column(
        String(128),
        ForeignKey("artifact_versions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    resume_source = Column(
        String, nullable=True
    )  # personal_resume | context_upload | none
    resume_title_snapshot = Column(String, nullable=True)

    # Snapshots (immutable; survive source file/resume deletion)
    resume_text_snapshot = Column(Text, nullable=True)
    jd_text_snapshot = Column(Text, nullable=True)
    resume_structured_snapshot_json = Column(
        Text, nullable=True
    )  # Structured resume snapshot with exact source ref_ids.
    jd_structured_json = Column(Text, nullable=True)  # JDRequirements w/ ref_ids

    # Current transcript reference — full text/segments live in the dedicated
    # interview_transcripts table (soft ref; the hard FK is on that table).
    transcript_id = Column(String, index=True, nullable=True)

    # Top-level analysis result (per-question rows in interview_qa)
    analysis_json = Column(Text, nullable=True)
    analysis_schema_version = Column(Integer, nullable=False, default=3)
    ability_signal_generation = Column(Integer, nullable=False, default=0)

    # User-visible guidance shared only by debrief Conversations bound to this
    # record. It is owned here rather than in a generic Project/Preference
    # registry and does not grant Tool permission.
    debrief_guidance_text = Column(Text, nullable=True)
    debrief_guidance_source_message_id = Column(Integer, nullable=True)
    debrief_guidance_version = Column(Integer, nullable=False, default=0)

    # Status & progress. Upload: pending→transcribing→analyzing→completed/failed.
    # Mock (wired in CONVERSATION-MOCK): mock_in_progress→processing_review→
    # review_ready/review_failed; cancelled on abandon.
    status = Column(String, index=True, default="pending", nullable=False)
    analyzed_qa_count = Column(Integer, nullable=False, default=0)
    celery_task_id = Column(String, nullable=True)
    error_message = Column(Text, nullable=True)

    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)
    completed_at = Column(DateTime, nullable=True)
