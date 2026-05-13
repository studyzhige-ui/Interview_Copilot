import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, String, Text

from app.db.database import Base


def _generate_record_id() -> str:
    return f"ir_{uuid.uuid4().hex[:12]}"


class InterviewRecord(Base):
    """A complete record of one interview (real upload or mock simulation)."""

    __tablename__ = "interview_records"

    id = Column(String, primary_key=True, default=_generate_record_id, index=True)
    user_id = Column(String, index=True, nullable=False)
    source = Column(String, nullable=False)  # "upload" | "mock"
    title = Column(String, default="未命名面试")
    tag = Column(String(32), nullable=True)
    audio_upload_id = Column(String, nullable=True)
    resume_upload_id = Column(String, nullable=True)
    jd_upload_id = Column(String, nullable=True)
    transcript = Column(Text, nullable=True)
    analysis_json = Column(Text, nullable=True)
    interview_plan = Column(Text, nullable=True)
    status = Column(String, index=True, default="processing", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
