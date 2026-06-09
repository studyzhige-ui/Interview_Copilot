"""Resume: a first-class personal-profile entity (NOT a knowledge document).

A resume is the user's own profile asset. It never enters the knowledge base
or general RAG. Each user keeps at most TWO active (``archived_at IS NULL``)
resumes, exactly one of which is the default. Every record has a stable id
unrelated to the source filename — re-uploading the same name makes a NEW
resume, never reusing an old id (history/business snapshots must stay stable).

Lifecycle: a personal-info upload confirms a ``file_assets`` row, then this
table is created/replaced and parsed into ``raw_text_snapshot`` /
``resume_sections``. Business records that USE a resume snapshot its text at
the time of use and never re-read this row, so editing a resume can't rewrite
history.
"""
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)

from app.db.database import Base


def generate_resume_id() -> str:
    return f"rsm_{uuid.uuid4().hex[:12]}"


class Resume(Base):
    __tablename__ = "resumes"
    __table_args__ = (
        # At most ONE default among a user's active resumes. Partial unique
        # index (Postgres + SQLite both support it). The "at most two active"
        # rule is enforced transactionally in the service layer.
        Index(
            "uq_resumes_one_default_per_user",
            "user_id",
            unique=True,
            postgresql_where=text("is_default AND archived_at IS NULL"),
            sqlite_where=text("is_default = 1 AND archived_at IS NULL"),
        ),
        Index("ix_resumes_user_active", "user_id", "archived_at"),
    )

    id = Column(String, primary_key=True, default=generate_resume_id, index=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    # Source upload, if any. NULL allows future pure-text / hand-created resumes.
    file_asset_id = Column(String, ForeignKey("file_assets.id"), nullable=True)
    title = Column(String, nullable=False, default="我的简历")
    is_default = Column(Boolean, nullable=False, default=False)
    # Immutable original-text snapshot (business records snapshot from this).
    raw_text_snapshot = Column(Text, nullable=True)
    structured_json = Column(Text, nullable=True)
    parse_status = Column(String, nullable=False, default="pending")  # pending/ready/failed
    parse_error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False,
    )
    # Soft delete. Only ``archived_at IS NULL`` rows count toward the
    # max-two / default rules and show on the personal-info page.
    archived_at = Column(DateTime, nullable=True)
