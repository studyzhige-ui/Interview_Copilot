"""Provider-neutral source, observation, candidate, and evidence records."""

from __future__ import annotations

import uuid

from sqlalchemy import (
    CheckConstraint,
    Column,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
)

from app.db.database import Base
from app.db.types import JSONValue as JSON
from app.db.types import UTCDateTime as DateTime
from app.db.types import utc_now


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


class InterviewInvitationSourceSnapshot(Base):
    """Immutable bytes/fields captured from one invitation source version."""

    __tablename__ = "interview_invitation_source_snapshots"
    __table_args__ = (
        CheckConstraint(
            "source_kind IN ('fixture', 'manual', 'user_message', 'gmail')",
            name="ck_interview_invitation_sources_kind",
        ),
        UniqueConstraint(
            "user_id",
            "source_kind",
            "source_identity",
            "source_version",
            name="uq_interview_invitation_source_version",
        ),
        Index(
            "ix_interview_invitation_sources_user_observed",
            "user_id",
            "observed_at",
        ),
    )

    id = Column(String(36), primary_key=True, default=lambda: _id("iis"))
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_kind = Column(String(32), nullable=False)
    source_identity = Column(String(256), nullable=False)
    source_version = Column(String(128), nullable=False)
    content_sha256 = Column(String(64), nullable=False)
    payload_json = Column(JSON, nullable=False)
    observed_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, nullable=False, default=utc_now)


class InterviewInvitationSourceImmutableError(RuntimeError):
    """A captured source version cannot be rewritten or removed in place."""


@event.listens_for(InterviewInvitationSourceSnapshot, "before_update", propagate=True)
def _reject_source_update(*_args) -> None:
    raise InterviewInvitationSourceImmutableError(
        "InterviewInvitationSourceSnapshot is append-only"
    )


@event.listens_for(InterviewInvitationSourceSnapshot, "before_delete", propagate=True)
def _reject_source_delete(*_args) -> None:
    raise InterviewInvitationSourceImmutableError(
        "InterviewInvitationSourceSnapshot is append-only"
    )


class InterviewInvitationObservation(Base):
    """The product's handling state for one immutable source snapshot."""

    __tablename__ = "interview_invitation_observations"
    __table_args__ = (
        CheckConstraint(
            "status IN ('received', 'candidate_registered', "
            "'pending_confirmation', 'confirmed', 'rejected', 'retracted')",
            name="ck_interview_invitation_observations_status",
        ),
        CheckConstraint(
            "version >= 1",
            name="ck_interview_invitation_observations_version",
        ),
        UniqueConstraint(
            "source_snapshot_id",
            name="uq_interview_invitation_observation_source",
        ),
        Index(
            "ix_interview_invitation_observations_user_status",
            "user_id",
            "status",
            "updated_at",
        ),
    )

    id = Column(String(36), primary_key=True, default=lambda: _id("iio"))
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_snapshot_id = Column(
        String(36),
        ForeignKey("interview_invitation_source_snapshots.id", ondelete="CASCADE"),
        nullable=False,
    )
    status = Column(String(32), nullable=False, default="received")
    version = Column(Integer, nullable=False, default=1)
    retraction_reason = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now)
    updated_at = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now)


class InterviewInvitationCandidate(Base):
    """A low-authority, evidence-backed invitation proposal."""

    __tablename__ = "interview_invitation_candidates"
    __table_args__ = (
        CheckConstraint(
            "status IN ('needs_clarification', 'pending_confirmation', "
            "'confirmed', 'rejected', 'superseded')",
            name="ck_interview_invitation_candidates_status",
        ),
        CheckConstraint(
            "version >= 1",
            name="ck_interview_invitation_candidates_version",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_interview_invitation_candidates_confidence",
        ),
        UniqueConstraint(
            "user_id",
            "source_kind",
            "source_identity",
            "source_version",
            name="uq_interview_invitation_candidate_source",
        ),
        Index(
            "ix_interview_invitation_candidates_user_status",
            "user_id",
            "status",
            "updated_at",
        ),
    )

    id = Column(String(36), primary_key=True, default=lambda: _id("iic"))
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    observation_id = Column(
        String(36),
        ForeignKey("interview_invitation_observations.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    source_kind = Column(String(32), nullable=False)
    source_identity = Column(String(256), nullable=False)
    source_version = Column(String(128), nullable=False)
    status = Column(String(32), nullable=False)
    version = Column(Integer, nullable=False, default=1)
    facts_json = Column(JSON, nullable=False)
    field_provenance_json = Column(JSON, nullable=False, default=list)
    missing_fields_json = Column(JSON, nullable=False, default=list)
    conflicts_json = Column(JSON, nullable=False, default=list)
    confidence = Column(Float, nullable=True)
    extractor_version = Column(String(128), nullable=False)
    resolved_by_interaction_id = Column(
        String(36),
        ForeignKey("agent_interactions.id", ondelete="SET NULL"),
        nullable=True,
    )
    confirmed_operation_id = Column(
        String(36),
        ForeignKey("application_operations.id", ondelete="SET NULL"),
        nullable=True,
    )
    resolution_note = Column(Text, nullable=True)
    resolved_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now)
    updated_at = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now)


class InterviewInvitationEvidenceRef(Base):
    """Append-only field-level evidence bound by a confirmed operation."""

    __tablename__ = "interview_invitation_evidence_refs"
    __table_args__ = (
        UniqueConstraint(
            "operation_id",
            "field_name",
            "source_kind",
            "source_identity",
            "source_version",
            name="uq_interview_invitation_evidence_binding",
        ),
        Index(
            "ix_interview_invitation_evidence_interview",
            "interview_record_id",
            "created_at",
        ),
    )

    id = Column(String(36), primary_key=True, default=lambda: _id("iie"))
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    operation_id = Column(
        String(36),
        ForeignKey("application_operations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    candidate_id = Column(
        String(36),
        ForeignKey("interview_invitation_candidates.id", ondelete="SET NULL"),
        nullable=True,
    )
    source_snapshot_id = Column(
        String(36),
        ForeignKey("interview_invitation_source_snapshots.id", ondelete="SET NULL"),
        nullable=True,
    )
    interview_record_id = Column(
        String,
        ForeignKey("interview_records.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    process_event_id = Column(
        String(35),
        ForeignKey("process_events.id", ondelete="CASCADE"),
        nullable=False,
    )
    field_name = Column(String(80), nullable=False)
    source_kind = Column(String(32), nullable=False)
    source_identity = Column(String(256), nullable=False)
    source_version = Column(String(128), nullable=True)
    value_hash = Column(String(64), nullable=False)
    created_at = Column(DateTime, nullable=False, default=utc_now)


__all__ = [
    "InterviewInvitationCandidate",
    "InterviewInvitationEvidenceRef",
    "InterviewInvitationObservation",
    "InterviewInvitationSourceImmutableError",
    "InterviewInvitationSourceSnapshot",
]
