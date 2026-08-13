"""Append-only JD snapshots owned by one concrete JobOpportunity.

This is a product record with a narrow owner, not a generic Source registry.
The original URL, bounded canonical content and checksum preserve what was
actually observed; later observations append a new version and never rewrite
the snapshot frozen by an application event.
"""

from __future__ import annotations

import uuid

from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
)

from app.db.database import Base
from app.db.types import UTCDateTime as DateTime
from app.db.types import utc_now


JD_SNAPSHOT_SOURCE_KINDS = ("tool_result", "typed_product_ui")


class JobDescriptionSnapshotImmutableError(RuntimeError):
    """Raised when code attempts to rewrite or delete a captured JD version."""


class JobDescriptionSnapshot(Base):
    """One immutable observation of a JobOpportunity's description."""

    __tablename__ = "job_description_snapshots"
    __table_args__ = (
        CheckConstraint(
            "source_kind IN ('tool_result', 'typed_product_ui')",
            name="ck_job_description_snapshots_source_kind",
        ),
        CheckConstraint(
            "length(canonical_content) > 0 AND length(canonical_content) <= 120000",
            name="ck_job_description_snapshots_content_length",
        ),
        UniqueConstraint(
            "job_opportunity_id",
            "version",
            name="uq_job_description_snapshots_opportunity_version",
        ),
        UniqueConstraint(
            "job_opportunity_id",
            "idempotency_key",
            name="uq_job_description_snapshots_opportunity_idempotency",
        ),
        Index(
            "ix_job_description_snapshots_opportunity_observed",
            "job_opportunity_id",
            "observed_at",
            "version",
        ),
        Index(
            "ix_job_description_snapshots_source_identity",
            "source_kind",
            "source_identity",
            "source_version",
        ),
    )

    id = Column(
        String(36),
        primary_key=True,
        default=lambda: f"jds_{uuid.uuid4().hex}",
    )
    job_opportunity_id = Column(
        String(35),
        ForeignKey("job_opportunities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version = Column(Integer, nullable=False)

    original_url = Column(Text, nullable=False)
    normalized_url = Column(Text, nullable=False)
    observed_at = Column(DateTime, nullable=False)
    provider = Column(String(80), nullable=False)

    canonical_content = Column(Text, nullable=False)
    content_checksum = Column(String(64), nullable=False)

    source_kind = Column(String(32), nullable=False)
    source_identity = Column(String(256), nullable=False)
    source_version = Column(String(128), nullable=False)
    idempotency_key = Column(String(200), nullable=False)
    creation_fingerprint = Column(String(64), nullable=False)

    created_at = Column(DateTime, nullable=False, default=utc_now)


@event.listens_for(JobDescriptionSnapshot, "before_update", propagate=True)
def _reject_job_description_snapshot_update(*_args) -> None:
    raise JobDescriptionSnapshotImmutableError("JobDescriptionSnapshot is append-only")


@event.listens_for(JobDescriptionSnapshot, "before_delete", propagate=True)
def _reject_job_description_snapshot_delete(*_args) -> None:
    raise JobDescriptionSnapshotImmutableError("JobDescriptionSnapshot is append-only")


__all__ = [
    "JD_SNAPSHOT_SOURCE_KINDS",
    "JobDescriptionSnapshot",
    "JobDescriptionSnapshotImmutableError",
]
