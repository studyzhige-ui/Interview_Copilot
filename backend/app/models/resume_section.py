import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, String, Text

from app.db.database import Base


def _generate_section_id() -> str:
    return f"rs_{uuid.uuid4().hex[:12]}"


class ResumeSection(Base):
    """A structured paragraph/section extracted from a resume."""

    __tablename__ = "resume_sections"

    id = Column(String, primary_key=True, default=_generate_section_id, index=True)
    user_id = Column(String, index=True, nullable=False)
    upload_id = Column(String, index=True, nullable=False)
    section_type = Column(String, index=True, nullable=False)  # "summary"|"project"|"education"|"skill"
    title = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    metadata_json = Column(Text, nullable=True)
    embedding_status = Column(String, default="pending", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
