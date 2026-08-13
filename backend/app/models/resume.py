"""Retired Resume rows retained only as migration/rollback/audit data.

``Artifact(kind='resume')`` and ``ArtifactVersion`` are the live identity and
content owners. Rows in this table predate that cut-over; migration keeps them
only for old references and rollback/history. Production code must not create,
replace, parse, archive, or otherwise mutate them.
"""

import uuid

from sqlalchemy import (
    Boolean,
    Column,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)

from app.db.database import Base
from app.db.types import UTCDateTime as DateTime
from app.db.types import utc_now


def generate_resume_id() -> str:
    return f"rsm_{uuid.uuid4().hex[:12]}"


class Resume(Base):
    """Pre-cut-over resume record; never a production write target."""

    __tablename__ = "resumes"
    __table_args__ = (
        # Historical constraints remain so old rows retain their exact shape.
        Index(
            "uq_resumes_one_default_per_user",
            "user_id",
            unique=True,
            postgresql_where=text("is_default AND archived_at IS NULL"),
            sqlite_where=text("is_default = 1 AND archived_at IS NULL"),
        ),
        Index("ix_resumes_user_active", "user_id", "archived_at"),
    )

    id = Column(String, primary_key=True, default=generate_resume_id)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    # Historical source upload identity.
    file_asset_id = Column(String, ForeignKey("file_assets.id"), nullable=True)
    title = Column(String, nullable=False, default="我的简历")
    is_default = Column(Boolean, nullable=False, default=False)
    # Pre-cut-over original-text snapshot retained for audit/rollback only.
    raw_text_snapshot = Column(Text, nullable=True)
    structured_json = Column(Text, nullable=True)
    parse_status = Column(
        String, nullable=False, default="pending"
    )  # pending/ready/failed
    parse_error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(
        DateTime,
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )
    # Historical soft-delete marker.
    archived_at = Column(DateTime, nullable=True)
