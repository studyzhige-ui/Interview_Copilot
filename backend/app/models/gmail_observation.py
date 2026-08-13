"""Gmail-owned Observation snapshots and Dedicated Conversation review cards.

These records deliberately belong to the concrete Gmail connector.  They are
not a provider-neutral Source/Evidence registry and they do not make an
external message a confirmed ``ProcessEvent``.  A snapshot records what Gmail
returned; the Observation records the product's current handling state; and a
review card is only a PersistentTask-local pending projection.
"""

from __future__ import annotations

import uuid

from sqlalchemy import (
    Boolean,
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


GMAIL_OBSERVATION_STATUSES = (
    "unreviewed",
    "pending_confirmation",
    "applied",
    "dismissed",
    "retracted",
)
GMAIL_REVIEW_CARD_STATUSES = ("pending", "approved", "rejected", "skipped")


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


class GmailObservation(Base):
    """One deduplicated Gmail message observed for one connected account."""

    __tablename__ = "gmail_observations"
    __table_args__ = (
        CheckConstraint(
            "status IN ('unreviewed', 'pending_confirmation', 'applied', "
            "'dismissed', 'retracted')",
            name="ck_gmail_observations_status",
        ),
        CheckConstraint(
            "classification_confidence IS NULL OR "
            "(classification_confidence >= 0 AND classification_confidence <= 1)",
            name="ck_gmail_observations_confidence",
        ),
        UniqueConstraint(
            "gmail_account_id",
            "provider_message_id",
            name="uq_gmail_observations_account_message",
        ),
        Index(
            "ix_gmail_observations_user_status_observed",
            "user_id",
            "status",
            "observed_at",
        ),
        Index(
            "ix_gmail_observations_opportunity",
            "matched_job_opportunity_id",
            "observed_at",
        ),
    )

    id = Column(String(36), primary_key=True, default=lambda: _id("gob"))
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    gmail_account_id = Column(
        String(36),
        ForeignKey("gmail_integration_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider_message_id = Column(String(256), nullable=False)
    provider_thread_id = Column(String(256), nullable=False)
    received_at = Column(DateTime, nullable=True)
    observed_at = Column(DateTime, nullable=False, default=utc_now)

    status = Column(String(32), nullable=False, default="unreviewed")
    version = Column(Integer, nullable=False, default=1)
    candidate_event_kind = Column(String(40), nullable=True)
    classification_confidence = Column(Float, nullable=True)
    unique_match = Column(Boolean, nullable=True)
    analysis_summary = Column(Text, nullable=True)
    matched_job_opportunity_id = Column(
        String(35),
        ForeignKey("job_opportunities.id", ondelete="SET NULL"),
        nullable=True,
    )
    applied_process_event_id = Column(
        String(35),
        ForeignKey("process_events.id", ondelete="SET NULL"),
        nullable=True,
    )
    retraction_process_event_id = Column(
        String(35),
        ForeignKey("process_events.id", ondelete="SET NULL"),
        nullable=True,
    )
    # A user-visible report, not a notification-delivery receipt.  It keeps a
    # high-confidence automatic application discoverable and correctable.
    notification_summary = Column(Text, nullable=True)

    created_at = Column(DateTime, nullable=False, default=utc_now)
    updated_at = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now)


class GmailObservationSnapshot(Base):
    """Immutable, versioned minimum Gmail source snapshot."""

    __tablename__ = "gmail_observation_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "observation_id",
            "snapshot_version",
            name="uq_gmail_observation_snapshots_version",
        ),
        Index(
            "ix_gmail_observation_snapshots_observation_observed",
            "observation_id",
            "observed_at",
        ),
    )

    id = Column(String(36), primary_key=True, default=lambda: _id("gos"))
    observation_id = Column(
        String(36),
        ForeignKey("gmail_observations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    snapshot_version = Column(String(128), nullable=False)
    provider_history_id = Column(String(256), nullable=False)
    provider_message_id = Column(String(256), nullable=False)
    provider_thread_id = Column(String(256), nullable=False)
    content_available = Column(Boolean, nullable=False, default=True)
    received_at = Column(DateTime, nullable=True)
    from_hint = Column(String(320), nullable=False, default="")
    subject = Column(String(500), nullable=False, default="")
    snippet = Column(String(1_000), nullable=False, default="")
    content_sha256 = Column(String(64), nullable=False)
    observed_at = Column(DateTime, nullable=False, default=utc_now)
    created_at = Column(DateTime, nullable=False, default=utc_now)


class GmailObservationSnapshotImmutableError(RuntimeError):
    """A captured provider snapshot cannot be rewritten or removed in place."""


@event.listens_for(GmailObservationSnapshot, "before_update", propagate=True)
def _reject_snapshot_update(*_args) -> None:
    raise GmailObservationSnapshotImmutableError(
        "GmailObservationSnapshot is append-only"
    )


@event.listens_for(GmailObservationSnapshot, "before_delete", propagate=True)
def _reject_snapshot_delete(*_args) -> None:
    raise GmailObservationSnapshotImmutableError(
        "GmailObservationSnapshot is append-only"
    )


class GmailObservationReviewCard(Base):
    """One task-local pending decision for one Gmail Observation."""

    __tablename__ = "gmail_observation_review_cards"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'skipped')",
            name="ck_gmail_observation_review_cards_status",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_gmail_observation_review_cards_confidence",
        ),
        UniqueConstraint(
            "persistent_task_id",
            "observation_id",
            name="uq_gmail_observation_review_cards_task_observation",
        ),
        Index(
            "ix_gmail_observation_review_cards_task_status_created",
            "persistent_task_id",
            "status",
            "created_at",
        ),
    )

    id = Column(String(36), primary_key=True, default=lambda: _id("grc"))
    persistent_task_id = Column(
        String(35),
        ForeignKey("persistent_tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    observation_id = Column(
        String(36),
        ForeignKey("gmail_observations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_snapshot_id = Column(
        String(36),
        ForeignKey("gmail_observation_snapshots.id", ondelete="CASCADE"),
        nullable=False,
    )
    status = Column(String(16), nullable=False, default="pending")
    version = Column(Integer, nullable=False, default=1)
    candidate_event_kind = Column(String(40), nullable=False)
    candidate_opportunity_id = Column(
        String(35),
        ForeignKey("job_opportunities.id", ondelete="SET NULL"),
        nullable=True,
    )
    occurred_at = Column(DateTime, nullable=False)
    description = Column(Text, nullable=False)
    step_summary = Column(String(300), nullable=True)
    confidence = Column(Float, nullable=False)
    unique_match = Column(Boolean, nullable=False, default=False)
    rationale = Column(Text, nullable=False)
    # Only the typed Gmail workflow reads this candidate.  It is not a generic
    # domain payload and cannot be promoted without Application Service checks.
    new_opportunity_json = Column(JSON, nullable=True)
    process_event_id = Column(
        String(35),
        ForeignKey("process_events.id", ondelete="SET NULL"),
        nullable=True,
    )
    resolution_note = Column(Text, nullable=True)
    user_request_identity = Column(String(256), nullable=True)
    user_request_version = Column(String(128), nullable=True)
    resolved_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now)
    updated_at = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now)


__all__ = [
    "GMAIL_OBSERVATION_STATUSES",
    "GMAIL_REVIEW_CARD_STATUSES",
    "GmailObservation",
    "GmailObservationReviewCard",
    "GmailObservationSnapshot",
    "GmailObservationSnapshotImmutableError",
]
