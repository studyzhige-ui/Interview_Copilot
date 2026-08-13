"""Versioned user artifacts and their exact application-use snapshots.

An Artifact is created only through an explicit product command.  Its
versions are append-only content records: saving one proves only that this
version exists, never that its statements are factual or that it was used in
an application.  Application ``related`` and ``submitted`` semantics live in
separate records so neither can be inferred from generation, export, or the
Artifact's current version.
"""

from __future__ import annotations

import uuid

from sqlalchemy import (
    Column,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import event, inspect

from app.db.database import Base
from app.db.types import UTCDateTime as DateTime
from app.db.types import utc_now


def generate_artifact_id() -> str:
    return f"art_{uuid.uuid4().hex}"


def generate_artifact_version_id() -> str:
    return f"artv_{uuid.uuid4().hex}"


def generate_artifact_relation_id() -> str:
    return f"arj_{uuid.uuid4().hex}"


def generate_artifact_submission_id() -> str:
    return f"asu_{uuid.uuid4().hex}"


class ImmutableArtifactRecordError(RuntimeError):
    """Raised when an append-only Artifact record is updated in place."""


class Artifact(Base):
    """Stable identity and lifecycle for one user-visible saved deliverable."""

    __tablename__ = "artifacts"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "creation_key",
            name="uq_artifacts_user_creation_key",
        ),
        Index("ix_artifacts_user_kind_archived", "user_id", "kind", "archived_at"),
    )

    id = Column(String(128), primary_key=True, default=generate_artifact_id)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind = Column(String(64), nullable=False, index=True)
    # Stable command identity. Reusing it with a different initial version is
    # rejected; retrying the same explicit creation returns the original row.
    creation_key = Column(String(128), nullable=False)
    created_at = Column(DateTime, nullable=False, default=utc_now)
    updated_at = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now)
    archived_at = Column(DateTime, nullable=True)


class ArtifactVersion(Base):
    """One immutable content version belonging to an Artifact.

    Current version is derived as the greatest ``version_no``. This avoids a
    second mutable current pointer that could disagree with append-only
    history. Provenance columns point directly at real owner identities; they
    do not form a polymorphic Source object or registry.
    """

    __tablename__ = "artifact_versions"
    __table_args__ = (
        UniqueConstraint(
            "artifact_id",
            "version_no",
            name="uq_artifact_versions_artifact_number",
        ),
        UniqueConstraint(
            "artifact_id",
            "operation_key",
            name="uq_artifact_versions_artifact_operation",
        ),
        Index("ix_artifact_versions_artifact_created", "artifact_id", "created_at"),
    )

    id = Column(String(128), primary_key=True, default=generate_artifact_version_id)
    artifact_id = Column(
        String(128),
        ForeignKey("artifacts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_no = Column(Integer, nullable=False)
    operation_key = Column(String(128), nullable=False)
    title = Column(String(240), nullable=False)
    content_text = Column(Text, nullable=True)
    content_format = Column(String(64), nullable=False)
    # Reuses the real raw-file owner. ArtifactVersion owns no duplicate blob.
    file_asset_id = Column(
        String,
        ForeignKey("file_assets.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    # explicit_save | message_promotion | flow_delivery | edit
    origin_kind = Column(String(32), nullable=False)
    # Deliberately retained as identities rather than cascading FKs: deleting
    # a Conversation must not rewrite a formally saved Artifact's provenance.
    source_message_id = Column(Integer, nullable=True)
    source_turn_id = Column(String(128), nullable=True)
    source_owner_type = Column(String(64), nullable=True)
    source_owner_id = Column(String(128), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now)


class ArtifactJobRelation(Base):
    """A weak, artifact-level ``related`` link to a real JobOpportunity."""

    __tablename__ = "artifact_job_relations"
    __table_args__ = (
        UniqueConstraint(
            "artifact_id",
            "job_opportunity_id",
            name="uq_artifact_job_relations_pair",
        ),
        Index(
            "ix_artifact_job_relations_user_job",
            "user_id",
            "job_opportunity_id",
        ),
    )

    id = Column(String(128), primary_key=True, default=generate_artifact_relation_id)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    artifact_id = Column(
        String(128),
        ForeignKey("artifacts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # No placeholder FK: Stage 2's real JobOpportunity owner validates this
    # identity through the injected Application Service checker.
    job_opportunity_id = Column(String(128), nullable=False)
    created_at = Column(DateTime, nullable=False, default=utc_now)


class ArtifactSubmissionSnapshot(Base):
    """Immutable assertion that one exact version was actually submitted."""

    __tablename__ = "artifact_submission_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "operation_key",
            name="uq_artifact_submissions_user_operation",
        ),
        Index(
            "ix_artifact_submissions_user_job",
            "user_id",
            "job_opportunity_id",
        ),
        Index(
            "ix_artifact_submissions_artifact_version",
            "artifact_id",
            "artifact_version_id",
        ),
    )

    id = Column(String(128), primary_key=True, default=generate_artifact_submission_id)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    operation_key = Column(String(128), nullable=False)
    job_opportunity_id = Column(String(128), nullable=False)
    artifact_id = Column(
        String(128),
        ForeignKey("artifacts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    artifact_version_id = Column(
        String(128),
        ForeignKey("artifact_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    # user_confirmation | external_receipt
    basis = Column(String(32), nullable=False)
    # A user-confirmed submission points at the original user message. An
    # external submission instead points at the actual receipt/read-back
    # owner's typed identity. These are mutually exclusive.
    confirmation_message_id = Column(Integer, nullable=True)
    receipt_owner_type = Column(String(64), nullable=True)
    receipt_owner_id = Column(String(128), nullable=True)
    submitted_at = Column(DateTime, nullable=False, default=utc_now)


def _reject_append_only_update(_mapper, _connection, target) -> None:
    state = inspect(target)
    if any(attribute.history.has_changes() for attribute in state.attrs):
        raise ImmutableArtifactRecordError(
            f"{type(target).__name__} rows are append-only"
        )


event.listen(ArtifactVersion, "before_update", _reject_append_only_update)
event.listen(ArtifactSubmissionSnapshot, "before_update", _reject_append_only_update)


__all__ = [
    "Artifact",
    "ArtifactJobRelation",
    "ArtifactSubmissionSnapshot",
    "ArtifactVersion",
    "ImmutableArtifactRecordError",
]
