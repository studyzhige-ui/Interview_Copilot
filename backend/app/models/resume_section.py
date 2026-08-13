import uuid

from sqlalchemy import Column, ForeignKey, Integer, String, Text

from app.db.database import Base
from app.db.types import UTCDateTime as DateTime
from app.db.types import utc_now


def _generate_section_id() -> str:
    return f"rs_{uuid.uuid4().hex[:12]}"


class ResumeSection(Base):
    """Pre-cut-over parsed section retained for migration/audit only."""

    __tablename__ = "resume_sections"

    id = Column(String, primary_key=True, default=_generate_section_id)
    # Stable historical owner identity retained for migration/audit.
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    # Owning pre-cut-over Resume identity.
    resume_id = Column(
        String,
        ForeignKey("resumes.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    section_type = Column(
        String, index=True, nullable=False
    )  # summary|project|experience|education|skill|other
    title = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    metadata_json = Column(Text, nullable=True)
    order_idx = Column(Integer, nullable=False, default=0)  # display / concat order
    embedding_status = Column(String, default="pending", nullable=False)
    created_at = Column(DateTime, default=utc_now, nullable=False)
