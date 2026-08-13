"""Career process state: opportunities, immutable facts, and next actions.

These three records are one bounded product slice, not a generic workflow
engine.  ``ProcessEvent`` is the append-only fact history;
``JobOpportunity`` stores only its replayable current projection; and
``NextAction`` represents a user-facing future action, never Agent runtime
work or a Reminder lifecycle.
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
    text,
)
from sqlalchemy.orm import relationship

from app.db.database import Base
from app.db.types import UTCDateTime as DateTime
from app.db.types import JSONValue as JSON
from app.db.types import utc_now


JOB_PHASES = (
    "pending_application",
    "applied",
    "in_process",
    "offer",
)
JOB_OUTCOMES = (
    "rejected",
    "withdrawn",
    "posting_closed",
    "declined_offer",
    "accepted",
)

PROCESS_EVENT_KINDS = (
    "tracking_started",
    "preparation_started",
    "application_submitted",
    "application_acknowledged",
    "recruiter_contact",
    "assessment_invited",
    "assessment_completed",
    "hiring_step",
    "interview_scheduled",
    "interview_completed",
    "background_check_started",
    "offer_received",
    "rejected",
    "withdrawn",
    "posting_closed",
    "offer_declined",
    "offer_accepted",
    "retraction",
)
PROCESS_EVENT_OPERATIONS = ("assert", "retract")
PROCESS_SOURCE_KINDS = (
    "user_assertion",
    "observation",
    "tool_result",
    "provider_receipt",
)

NEXT_ACTION_STATUSES = ("suggested", "planned", "done", "closed")
NEXT_ACTION_TIME_KINDS = ("fixed", "deadline", "flexible")
NEXT_ACTION_SOURCE_KINDS = (
    "user_request",
    "process_event",
    "agent_suggestion",
    "copilot_preference",
    "offer",
)
NEXT_ACTION_TRANSITION_SOURCE_KINDS = (
    "user_assertion",
    "process_event",
    "tool_result",
    "application_service_result",
    "copilot_preference",
)


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


class JobOpportunity(Base):
    """One user's process for one concrete role and recruitment batch."""

    __tablename__ = "job_opportunities"
    __table_args__ = (
        CheckConstraint(
            "phase IN ('pending_application', 'applied', 'in_process', 'offer')",
            name="ck_job_opportunities_phase",
        ),
        CheckConstraint(
            "outcome IS NULL OR outcome IN "
            "('rejected', 'withdrawn', 'posting_closed', "
            "'declined_offer', 'accepted')",
            name="ck_job_opportunities_outcome",
        ),
        CheckConstraint(
            "direction_version >= 0",
            name="ck_job_opportunities_direction_version",
        ),
        UniqueConstraint(
            "user_id",
            "idempotency_key",
            name="uq_job_opportunities_user_idempotency",
        ),
        UniqueConstraint(
            "user_id",
            "source_provider",
            "external_application_id",
            name="uq_job_opportunities_external_application",
        ),
        Index(
            "ix_job_opportunities_user_outcome_updated",
            "user_id",
            "outcome",
            "updated_at",
        ),
        Index(
            "ix_job_opportunities_user_external_job",
            "user_id",
            "source_provider",
            "external_job_id",
        ),
    )

    id = Column(String(35), primary_key=True, default=lambda: _id("jo"))
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    company_name = Column(String(200), nullable=False)
    job_title = Column(String(300), nullable=False)
    location = Column(String(200), nullable=True)
    team = Column(String(200), nullable=True)

    source_url = Column(Text, nullable=True)
    normalized_source_url = Column(Text, nullable=True)
    source_provider = Column(String(80), nullable=True)
    external_job_id = Column(String(200), nullable=True)
    external_application_id = Column(String(200), nullable=True)

    # Current projection only. The service rebuilds these fields exclusively
    # from immutable ProcessEvents after every append/correction.
    phase = Column(String(32), nullable=False, default="pending_application")
    current_step = Column(String(300), nullable=False, default="已加入跟踪")
    outcome = Column(String(32), nullable=True)
    archived_at = Column(DateTime, nullable=True)
    last_event_at = Column(DateTime, nullable=True)
    # Independent CAS token for current CareerProfile direction links.
    # ProcessEvent history remains append-only when matching changes.
    direction_version = Column(Integer, nullable=False, default=0, server_default="0")

    idempotency_key = Column(String(200), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now)
    updated_at = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now)

    direction_links = relationship(
        "JobOpportunityDirectionLink",
        order_by="JobOpportunityDirectionLink.position",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class JobOpportunityDirectionLink(Base):
    """A confirmed current relation, never a second direction owner."""

    __tablename__ = "job_opportunity_direction_links"
    __table_args__ = (
        CheckConstraint(
            "source_kind IN ('user_assertion', 'observation', "
            "'tool_result', 'provider_receipt')",
            name="ck_job_opportunity_direction_links_source_kind",
        ),
        CheckConstraint(
            "position >= 0",
            name="ck_job_opportunity_direction_links_position",
        ),
        UniqueConstraint(
            "job_opportunity_id",
            "career_profile_direction_id",
            name="uq_job_opportunity_direction_links_pair",
        ),
        UniqueConstraint(
            "job_opportunity_id",
            "position",
            name="uq_job_opportunity_direction_links_position",
        ),
        Index(
            "ix_job_opportunity_direction_links_direction",
            "career_profile_direction_id",
            "job_opportunity_id",
        ),
    )

    id = Column(String(37), primary_key=True, default=lambda: _id("jodl"))
    job_opportunity_id = Column(
        String(35),
        ForeignKey("job_opportunities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    career_profile_direction_id = Column(
        String(36),
        ForeignKey("career_profile_directions.id", ondelete="CASCADE"),
        nullable=False,
    )
    position = Column(Integer, nullable=False)
    source_kind = Column(String(32), nullable=False)
    source_identity = Column(String(256), nullable=False)
    match_reason = Column(Text, nullable=False)
    confirmed_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, nullable=False, default=utc_now)


class JobOpportunityMerge(Base):
    """One explicit, reversible duplicate-to-canonical relation.

    Neither opportunity nor either ProcessEvent history is rewritten. The
    relation only changes how the product projects the duplicate, and a
    retraction restores both original lines immediately.
    """

    __tablename__ = "job_opportunity_merges"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'retracted')",
            name="ck_job_opportunity_merges_status",
        ),
        CheckConstraint(
            "version >= 1",
            name="ck_job_opportunity_merges_version_positive",
        ),
        CheckConstraint(
            "duplicate_opportunity_id <> canonical_opportunity_id",
            name="ck_job_opportunity_merges_distinct",
        ),
        UniqueConstraint(
            "user_id",
            "operation_key",
            name="uq_job_opportunity_merges_user_operation",
        ),
        UniqueConstraint(
            "user_id",
            "retraction_operation_key",
            name="uq_job_opportunity_merges_user_retraction",
        ),
        Index(
            "uq_job_opportunity_merges_active_duplicate",
            "duplicate_opportunity_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
            sqlite_where=text("status = 'active'"),
        ),
        Index(
            "ix_job_opportunity_merges_user_status",
            "user_id",
            "status",
            "created_at",
        ),
    )

    id = Column(String(36), primary_key=True, default=lambda: _id("jom"))
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    duplicate_opportunity_id = Column(
        String(35),
        ForeignKey("job_opportunities.id", ondelete="CASCADE"),
        nullable=False,
    )
    canonical_opportunity_id = Column(
        String(35),
        ForeignKey("job_opportunities.id", ondelete="CASCADE"),
        nullable=False,
    )
    status = Column(
        String(16), nullable=False, default="active", server_default="active"
    )
    version = Column(Integer, nullable=False, default=1, server_default="1")
    operation_key = Column(String(200), nullable=False)
    reason = Column(Text, nullable=False)
    confirmation_source_identity = Column(String(256), nullable=False)
    created_at = Column(DateTime, nullable=False, default=utc_now)
    updated_at = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now)
    retraction_operation_key = Column(String(200), nullable=True)
    retraction_reason = Column(Text, nullable=True)
    retracted_at = Column(DateTime, nullable=True)


class ProcessEventImmutableError(RuntimeError):
    """Raised when code attempts to rewrite or delete a historical fact."""


class ProcessEvent(Base):
    """An append-only, confirmed fact in one opportunity's timeline."""

    __tablename__ = "process_events"
    __table_args__ = (
        CheckConstraint(
            "operation IN ('assert', 'retract')",
            name="ck_process_events_operation",
        ),
        CheckConstraint(
            "kind IN ("
            "'tracking_started', 'preparation_started', "
            "'application_submitted', 'application_acknowledged', "
            "'recruiter_contact', 'assessment_invited', "
            "'assessment_completed', 'hiring_step', "
            "'interview_scheduled', 'interview_completed', "
            "'background_check_started', 'offer_received', 'rejected', "
            "'withdrawn', 'posting_closed', 'offer_declined', "
            "'offer_accepted', 'retraction')",
            name="ck_process_events_kind",
        ),
        CheckConstraint(
            "source_kind IN "
            "('user_assertion', 'observation', 'tool_result', 'provider_receipt')",
            name="ck_process_events_source_kind",
        ),
        CheckConstraint(
            "(operation = 'assert' AND kind <> 'retraction') OR "
            "(operation = 'retract' AND kind = 'retraction' "
            "AND corrects_event_id IS NOT NULL)",
            name="ck_process_events_operation_shape",
        ),
        CheckConstraint(
            "(jd_snapshot_id IS NULL AND jd_snapshot_version IS NULL) OR "
            "(jd_snapshot_id IS NOT NULL AND jd_snapshot_version IS NOT NULL)",
            name="ck_process_events_jd_snapshot_shape",
        ),
        UniqueConstraint(
            "job_opportunity_id",
            "sequence",
            name="uq_process_events_opportunity_sequence",
        ),
        UniqueConstraint(
            "job_opportunity_id",
            "idempotency_key",
            name="uq_process_events_opportunity_idempotency",
        ),
        Index(
            "ix_process_events_opportunity_occurred",
            "job_opportunity_id",
            "occurred_at",
        ),
        Index(
            "ix_process_events_source_identity",
            "source_kind",
            "source_identity",
        ),
    )

    id = Column(String(35), primary_key=True, default=lambda: _id("pe"))
    job_opportunity_id = Column(
        String(35),
        ForeignKey("job_opportunities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sequence = Column(Integer, nullable=False)
    operation = Column(String(16), nullable=False, default="assert")
    kind = Column(String(40), nullable=False)

    occurred_at = Column(DateTime, nullable=False)
    observed_at = Column(DateTime, nullable=False, default=utc_now)
    source_kind = Column(String(32), nullable=False)
    source_identity = Column(String(256), nullable=False)
    source_version = Column(String(128), nullable=True)
    description = Column(Text, nullable=False)
    step_summary = Column(String(300), nullable=True)
    # Immutable analysis-time facts captured with the event (for example the
    # confirmed direction identities and application channel at submission).
    # This is deliberately part of the fact row rather than a mutable funnel
    # projection, so later profile edits cannot rewrite historical cohorts.
    analysis_context_json = Column(JSON, nullable=False, default=dict)

    # A replacement is another asserted fact that points at the invalid fact.
    # A pure retraction uses operation='retract'. Both preserve the old row.
    # application_submitted freezes the exact JD version visible at its event
    # time. Later JobDescriptionSnapshots never rewrite this historical pair.
    jd_snapshot_id = Column(
        String(36),
        ForeignKey("job_description_snapshots.id", ondelete="NO ACTION"),
        nullable=True,
    )
    jd_snapshot_version = Column(Integer, nullable=True)

    corrects_event_id = Column(
        String(35),
        ForeignKey(
            "process_events.id",
            ondelete="NO ACTION",
            deferrable=True,
            initially="DEFERRED",
        ),
        nullable=True,
    )
    idempotency_key = Column(String(300), nullable=False)
    created_at = Column(DateTime, nullable=False, default=utc_now)


@event.listens_for(ProcessEvent, "before_update", propagate=True)
def _reject_process_event_update(*_args) -> None:
    raise ProcessEventImmutableError("ProcessEvent is append-only")


@event.listens_for(ProcessEvent, "before_delete", propagate=True)
def _reject_process_event_delete(*_args) -> None:
    raise ProcessEventImmutableError("ProcessEvent is append-only")


class NextAction(Base):
    """A lightweight user-facing future action, independent of AgentTask."""

    __tablename__ = "next_actions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('suggested', 'planned', 'done', 'closed')",
            name="ck_next_actions_status",
        ),
        CheckConstraint(
            "time_kind IN ('fixed', 'deadline', 'flexible')",
            name="ck_next_actions_time_kind",
        ),
        CheckConstraint(
            "source_kind IN "
            "('user_request', 'process_event', 'agent_suggestion', "
            "'copilot_preference', 'offer')",
            name="ck_next_actions_source_kind",
        ),
        CheckConstraint(
            "(time_kind = 'fixed' AND starts_at IS NOT NULL "
            "AND due_at IS NULL AND (ends_at IS NULL OR ends_at >= starts_at)) OR "
            "(time_kind = 'deadline' AND due_at IS NOT NULL "
            "AND starts_at IS NULL AND ends_at IS NULL) OR "
            "(time_kind = 'flexible' AND starts_at IS NULL "
            "AND ends_at IS NULL AND due_at IS NULL)",
            name="ck_next_actions_time_shape",
        ),
        CheckConstraint(
            "time_kind = 'flexible' OR "
            "(original_time_text IS NOT NULL AND source_timezone IS NOT NULL)",
            name="ck_next_actions_time_provenance",
        ),
        CheckConstraint(
            "planned_source_kind IS NULL OR planned_source_kind IN "
            "('user_assertion', 'process_event', 'tool_result', "
            "'application_service_result', 'copilot_preference')",
            name="ck_next_actions_planned_source_kind",
        ),
        CheckConstraint(
            "resolution_source_kind IS NULL OR resolution_source_kind IN "
            "('user_assertion', 'process_event', 'tool_result', "
            "'application_service_result', 'copilot_preference')",
            name="ck_next_actions_resolution_source_kind",
        ),
        CheckConstraint(
            "(planned_at IS NULL AND planned_source_kind IS NULL "
            "AND planned_source_identity IS NULL AND planned_source_version IS NULL) "
            "OR (planned_at IS NOT NULL AND planned_source_kind IS NOT NULL "
            "AND planned_source_identity IS NOT NULL)",
            name="ck_next_actions_planning_provenance",
        ),
        CheckConstraint(
            "(resolved_at IS NULL AND resolution_source_kind IS NULL "
            "AND resolution_source_identity IS NULL "
            "AND resolution_source_version IS NULL) "
            "OR (resolved_at IS NOT NULL AND resolution_source_kind IS NOT NULL "
            "AND resolution_source_identity IS NOT NULL)",
            name="ck_next_actions_resolution_provenance",
        ),
        CheckConstraint(
            "(status = 'suggested' AND planned_at IS NULL AND resolved_at IS NULL) "
            "OR (status = 'planned' AND planned_at IS NOT NULL "
            "AND resolved_at IS NULL) "
            "OR (status IN ('done', 'closed') AND resolved_at IS NOT NULL)",
            name="ck_next_actions_status_shape",
        ),
        CheckConstraint(
            "(status = 'closed' AND close_reason IS NOT NULL) OR "
            "(status <> 'closed' AND close_reason IS NULL)",
            name="ck_next_actions_close_reason",
        ),
        CheckConstraint("version >= 0", name="ck_next_actions_version"),
        CheckConstraint(
            "reminder_channel IS NULL OR reminder_channel = 'in_app'",
            name="ck_next_actions_reminder_channel",
        ),
        CheckConstraint(
            "(reminder_at IS NULL AND reminder_next_attempt_at IS NULL "
            "AND reminder_channel IS NULL AND reminder_delivered_at IS NULL "
            "AND reminder_dismissed_at IS NULL) OR "
            "(reminder_at IS NOT NULL AND reminder_next_attempt_at IS NOT NULL "
            "AND reminder_channel IS NOT NULL AND status <> 'suggested')",
            name="ck_next_actions_reminder_shape",
        ),
        UniqueConstraint(
            "user_id",
            "idempotency_key",
            name="uq_next_actions_user_idempotency",
        ),
        Index(
            "ix_next_actions_user_status_updated",
            "user_id",
            "status",
            "updated_at",
        ),
        Index(
            "ix_next_actions_opportunity_status",
            "job_opportunity_id",
            "status",
        ),
        Index(
            "ix_next_actions_reminder_due",
            "reminder_next_attempt_at",
            "reminder_delivered_at",
            "status",
        ),
    )

    id = Column(String(35), primary_key=True, default=lambda: _id("na"))
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Association only: JobOpportunity does not own this user-level object.
    job_opportunity_id = Column(
        String(35),
        ForeignKey("job_opportunities.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    interview_record_id = Column(
        String(128),
        ForeignKey("interview_records.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    offer_id = Column(
        String(35),
        ForeignKey("offers.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    artifact_id = Column(
        String(128),
        ForeignKey("artifacts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    content = Column(Text, nullable=False)
    status = Column(String(16), nullable=False)
    time_kind = Column(String(16), nullable=False)
    starts_at = Column(DateTime, nullable=True)
    ends_at = Column(DateTime, nullable=True)
    due_at = Column(DateTime, nullable=True)
    original_time_text = Column(String(300), nullable=True)
    source_timezone = Column(String(80), nullable=True)

    source_kind = Column(String(32), nullable=False)
    source_identity = Column(String(256), nullable=False)
    source_version = Column(String(128), nullable=True)

    planned_at = Column(DateTime, nullable=True)
    planned_source_kind = Column(String(40), nullable=True)
    planned_source_identity = Column(String(256), nullable=True)
    planned_source_version = Column(String(128), nullable=True)

    resolved_at = Column(DateTime, nullable=True)
    resolution_source_kind = Column(String(40), nullable=True)
    resolution_source_identity = Column(String(256), nullable=True)
    resolution_source_version = Column(String(128), nullable=True)
    close_reason = Column(String(300), nullable=True)

    # Reminder is notification scheduling attached to this planned action,
    # not another task/object lifecycle.  A minute scheduler materializes an
    # in-app delivery by stamping ``reminder_delivered_at``; dismissal only
    # controls presentation and never changes the NextAction lifecycle.
    reminder_at = Column(DateTime, nullable=True)
    reminder_next_attempt_at = Column(DateTime, nullable=True)
    reminder_channel = Column(String(24), nullable=True)
    reminder_delivered_at = Column(DateTime, nullable=True)
    reminder_dismissed_at = Column(DateTime, nullable=True)

    idempotency_key = Column(String(200), nullable=True)
    version = Column(Integer, nullable=False, default=0, server_default="0")
    created_at = Column(DateTime, nullable=False, default=utc_now)
    updated_at = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now)


__all__ = [
    "JOB_OUTCOMES",
    "JOB_PHASES",
    "NEXT_ACTION_SOURCE_KINDS",
    "NEXT_ACTION_STATUSES",
    "NEXT_ACTION_TIME_KINDS",
    "NEXT_ACTION_TRANSITION_SOURCE_KINDS",
    "PROCESS_EVENT_KINDS",
    "PROCESS_EVENT_OPERATIONS",
    "PROCESS_SOURCE_KINDS",
    "JobOpportunity",
    "JobOpportunityDirectionLink",
    "JobOpportunityMerge",
    "NextAction",
    "ProcessEvent",
    "ProcessEventImmutableError",
]
