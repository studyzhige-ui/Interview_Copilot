"""Typed contracts for the Stage 2 career-process domain slice."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


JobPhase = Literal["pending_application", "applied", "in_process", "offer"]
JobOutcome = Literal[
    "rejected",
    "withdrawn",
    "posting_closed",
    "declined_offer",
    "accepted",
]
OpportunityEntryReason = Literal[
    "explicit_tracking",
    "targeted_preparation",
    "user_confirmed_application",
    "verified_submission",
]
ProcessEventKind = Literal[
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
]
ProcessSourceKind = Literal[
    "user_assertion",
    "observation",
    "tool_result",
    "provider_receipt",
]
NextActionStatus = Literal["suggested", "planned", "done", "closed"]
NextActionTimeKind = Literal["fixed", "deadline", "flexible"]
NextActionSourceKind = Literal[
    "user_request",
    "process_event",
    "agent_suggestion",
    "copilot_preference",
    "offer",
]
NextActionTransitionSourceKind = Literal[
    "user_assertion",
    "process_event",
    "tool_result",
    "application_service_result",
    "copilot_preference",
]


class OpportunityDirectionSelection(BaseModel):
    """One requested relation to the canonical CareerProfile direction owner."""

    model_config = ConfigDict(extra="forbid")

    direction_id: str = Field(min_length=1, max_length=36)
    match_reason: str = Field(min_length=1, max_length=2_000)


class OpportunityCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company_name: str = Field(min_length=1, max_length=200)
    job_title: str = Field(min_length=1, max_length=300)
    entry_reason: OpportunityEntryReason
    occurred_at: AwareDatetime
    source_kind: ProcessSourceKind
    source_identity: str = Field(min_length=1, max_length=256)
    source_version: str | None = Field(default=None, max_length=128)
    source_description: str = Field(min_length=1, max_length=10_000)

    location: str | None = Field(default=None, max_length=200)
    team: str | None = Field(default=None, max_length=200)
    source_url: str | None = Field(default=None, max_length=4_000)
    source_provider: str | None = Field(default=None, max_length=80)
    external_job_id: str | None = Field(default=None, max_length=200)
    external_application_id: str | None = Field(default=None, max_length=200)
    idempotency_key: str | None = Field(default=None, max_length=200)
    reapplication_confirmed: bool = False
    directions: list[OpportunityDirectionSelection] = Field(
        default_factory=list,
        max_length=20,
    )

    @model_validator(mode="after")
    def validate_unique_directions(self) -> "OpportunityCreate":
        direction_ids = [item.direction_id for item in self.directions]
        if len(direction_ids) != len(set(direction_ids)):
            raise ValueError(
                "directions must not contain duplicate direction_id values"
            )
        return self


class OpportunityDirectionsReplace(BaseModel):
    """CAS command replacing one opportunity's current direction relation set."""

    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=0)
    directions: list[OpportunityDirectionSelection] = Field(max_length=20)
    source_kind: ProcessSourceKind
    source_identity: str = Field(min_length=1, max_length=256)

    @model_validator(mode="after")
    def validate_unique_directions(self) -> "OpportunityDirectionsReplace":
        direction_ids = [item.direction_id for item in self.directions]
        if len(direction_ids) != len(set(direction_ids)):
            raise ValueError(
                "directions must not contain duplicate direction_id values"
            )
        return self


class OpportunityMergeCreate(BaseModel):
    """Explicitly project one duplicate opportunity through a canonical one."""

    model_config = ConfigDict(extra="forbid")

    duplicate_opportunity_id: str = Field(min_length=1, max_length=35)
    canonical_opportunity_id: str = Field(min_length=1, max_length=35)
    operation_key: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=2_000)


class OpportunityMergeRetract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    operation_key: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=2_000)


class OpportunityMergeView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    duplicate_opportunity_id: str
    canonical_opportunity_id: str
    status: Literal["active", "retracted"]
    version: int
    reason: str
    confirmation_source_identity: str
    created_at: datetime
    updated_at: datetime
    retraction_reason: str | None
    retracted_at: datetime | None


class OpportunityMergeCandidateView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    duplicate_opportunity_id: str
    canonical_opportunity_id: str
    reasons: list[str]


class ProcessEventAppend(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: ProcessEventKind
    occurred_at: AwareDatetime
    observed_at: AwareDatetime | None = None
    source_kind: ProcessSourceKind
    source_identity: str = Field(min_length=1, max_length=256)
    source_version: str | None = Field(default=None, max_length=128)
    description: str = Field(min_length=1, max_length=10_000)
    step_summary: str | None = Field(default=None, max_length=300)
    application_channel: str | None = Field(default=None, max_length=160)
    idempotency_key: str | None = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def channel_belongs_to_application(self) -> "ProcessEventAppend":
        if (
            self.application_channel is not None
            and self.kind != "application_submitted"
        ):
            raise ValueError(
                "application_channel is only valid for application_submitted"
            )
        return self


class ProcessEventCorrection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    replacement_kind: ProcessEventKind | None = None
    occurred_at: AwareDatetime
    observed_at: AwareDatetime | None = None
    source_kind: ProcessSourceKind
    source_identity: str = Field(min_length=1, max_length=256)
    source_version: str | None = Field(default=None, max_length=128)
    description: str = Field(min_length=1, max_length=10_000)
    step_summary: str | None = Field(default=None, max_length=300)
    application_channel: str | None = Field(default=None, max_length=160)
    idempotency_key: str | None = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def channel_belongs_to_replacement(self) -> "ProcessEventCorrection":
        if (
            self.application_channel is not None
            and self.replacement_kind != "application_submitted"
        ):
            raise ValueError(
                "application_channel is only valid when replacing with application_submitted"
            )
        return self


class NextActionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=2_000)
    status: Literal["suggested", "planned"]
    time_kind: NextActionTimeKind
    source_kind: NextActionSourceKind
    source_identity: str = Field(min_length=1, max_length=256)
    source_version: str | None = Field(default=None, max_length=128)
    job_opportunity_id: str | None = Field(default=None, max_length=35)
    interview_record_id: str | None = Field(default=None, max_length=128)
    offer_id: str | None = Field(default=None, max_length=35)
    artifact_id: str | None = Field(default=None, max_length=128)

    starts_at: AwareDatetime | None = None
    ends_at: AwareDatetime | None = None
    due_at: AwareDatetime | None = None
    original_time_text: str | None = Field(default=None, max_length=300)
    source_timezone: str | None = Field(default=None, max_length=80)
    reminder_at: AwareDatetime | None = None
    reminder_channel: Literal["in_app"] | None = None
    idempotency_key: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def validate_time_shape(self) -> "NextActionCreate":
        if self.time_kind == "fixed":
            if self.starts_at is None or self.due_at is not None:
                raise ValueError("fixed actions require starts_at and forbid due_at")
            if self.ends_at is not None and self.ends_at < self.starts_at:
                raise ValueError("ends_at must not precede starts_at")
        elif self.time_kind == "deadline":
            if (
                self.due_at is None
                or self.starts_at is not None
                or self.ends_at is not None
            ):
                raise ValueError(
                    "deadline actions require due_at and forbid starts_at/ends_at"
                )
        elif any(
            value is not None for value in (self.starts_at, self.ends_at, self.due_at)
        ):
            raise ValueError("flexible actions do not carry fixed timestamps")

        if self.time_kind != "flexible" and (
            not self.original_time_text or not self.source_timezone
        ):
            raise ValueError(
                "fixed/deadline actions require original_time_text and source_timezone"
            )
        if (self.reminder_at is None) != (self.reminder_channel is None):
            raise ValueError("reminder_at and reminder_channel must be paired")
        if self.reminder_at is not None:
            if self.status != "planned":
                raise ValueError("only planned actions may schedule reminders")
            anchor = self.starts_at if self.time_kind == "fixed" else self.due_at
            if anchor is not None and self.reminder_at > anchor:
                raise ValueError("a reminder cannot be scheduled after its action time")
        return self


class NextActionEdit(BaseModel):
    """CAS replacement of editable action details; lifecycle stays separate."""

    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=0)
    content: str = Field(min_length=1, max_length=2_000)
    time_kind: NextActionTimeKind
    job_opportunity_id: str | None = Field(default=None, max_length=35)
    interview_record_id: str | None = Field(default=None, max_length=128)
    offer_id: str | None = Field(default=None, max_length=35)
    artifact_id: str | None = Field(default=None, max_length=128)
    starts_at: AwareDatetime | None = None
    ends_at: AwareDatetime | None = None
    due_at: AwareDatetime | None = None
    original_time_text: str | None = Field(default=None, max_length=300)
    source_timezone: str | None = Field(default=None, max_length=80)
    reminder_at: AwareDatetime | None = None
    reminder_channel: Literal["in_app"] | None = None

    @model_validator(mode="after")
    def validate_shape(self) -> "NextActionEdit":
        probe = NextActionCreate(
            content=self.content,
            status="planned" if self.reminder_at is not None else "suggested",
            time_kind=self.time_kind,
            source_kind="user_request"
            if self.reminder_at is not None
            else "process_event",
            source_identity="edit-validation",
            job_opportunity_id=self.job_opportunity_id,
            interview_record_id=self.interview_record_id,
            offer_id=self.offer_id,
            artifact_id=self.artifact_id,
            starts_at=self.starts_at,
            ends_at=self.ends_at,
            due_at=self.due_at,
            original_time_text=self.original_time_text,
            source_timezone=self.source_timezone,
            reminder_at=self.reminder_at,
            reminder_channel=self.reminder_channel,
        )
        del probe
        return self


class NextActionTransition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_kind: NextActionTransitionSourceKind
    source_identity: str = Field(min_length=1, max_length=256)
    source_version: str | None = Field(default=None, max_length=128)


class NextActionClose(NextActionTransition):
    reason: str = Field(min_length=1, max_length=300)


class JobOpportunityDirectionLinkView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    career_profile_direction_id: str
    position: int
    source_kind: ProcessSourceKind
    source_identity: str
    match_reason: str
    confirmed_at: datetime


class JobOpportunityView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: int
    company_name: str
    job_title: str
    location: str | None
    team: str | None
    source_url: str | None
    source_provider: str | None
    external_job_id: str | None
    external_application_id: str | None
    phase: JobPhase
    current_step: str
    outcome: JobOutcome | None
    archived_at: datetime | None
    last_event_at: datetime | None
    direction_version: int
    direction_links: list[JobOpportunityDirectionLinkView]
    created_at: datetime
    updated_at: datetime


class ProcessEventView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    job_opportunity_id: str
    sequence: int
    operation: Literal["assert", "retract"]
    kind: ProcessEventKind | Literal["retraction"]
    occurred_at: datetime
    observed_at: datetime
    source_kind: ProcessSourceKind
    source_identity: str
    source_version: str | None
    description: str
    step_summary: str | None
    analysis_context_json: dict[str, object]
    jd_snapshot_id: str | None
    jd_snapshot_version: int | None
    corrects_event_id: str | None
    created_at: datetime


class NextActionView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: int
    job_opportunity_id: str | None
    interview_record_id: str | None
    offer_id: str | None
    artifact_id: str | None
    content: str
    status: NextActionStatus
    time_kind: NextActionTimeKind
    starts_at: datetime | None
    ends_at: datetime | None
    due_at: datetime | None
    original_time_text: str | None
    source_timezone: str | None
    source_kind: NextActionSourceKind
    source_identity: str
    source_version: str | None
    planned_at: datetime | None
    planned_source_kind: NextActionTransitionSourceKind | None
    planned_source_identity: str | None
    planned_source_version: str | None
    resolved_at: datetime | None
    resolution_source_kind: NextActionTransitionSourceKind | None
    resolution_source_identity: str | None
    resolution_source_version: str | None
    close_reason: str | None
    reminder_at: datetime | None
    reminder_next_attempt_at: datetime | None
    reminder_channel: Literal["in_app"] | None
    reminder_delivered_at: datetime | None
    reminder_dismissed_at: datetime | None
    version: int
    created_at: datetime
    updated_at: datetime


__all__ = [
    "JobOpportunityDirectionLinkView",
    "JobOpportunityView",
    "JobOutcome",
    "JobPhase",
    "NextActionClose",
    "NextActionCreate",
    "NextActionEdit",
    "NextActionSourceKind",
    "NextActionStatus",
    "NextActionTimeKind",
    "NextActionTransition",
    "NextActionTransitionSourceKind",
    "NextActionView",
    "OpportunityCreate",
    "OpportunityDirectionSelection",
    "OpportunityDirectionsReplace",
    "OpportunityEntryReason",
    "OpportunityMergeCandidateView",
    "OpportunityMergeCreate",
    "OpportunityMergeRetract",
    "OpportunityMergeView",
    "ProcessEventAppend",
    "ProcessEventCorrection",
    "ProcessEventKind",
    "ProcessEventView",
    "ProcessSourceKind",
]
