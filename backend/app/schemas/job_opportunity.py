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
    idempotency_key: str | None = Field(default=None, max_length=300)


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
    idempotency_key: str | None = Field(default=None, max_length=300)


class NextActionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=2_000)
    status: Literal["suggested", "planned"]
    time_kind: NextActionTimeKind
    source_kind: NextActionSourceKind
    source_identity: str = Field(min_length=1, max_length=256)
    source_version: str | None = Field(default=None, max_length=128)
    job_opportunity_id: str | None = Field(default=None, max_length=35)

    starts_at: AwareDatetime | None = None
    ends_at: AwareDatetime | None = None
    due_at: AwareDatetime | None = None
    original_time_text: str | None = Field(default=None, max_length=300)
    source_timezone: str | None = Field(default=None, max_length=80)
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
    corrects_event_id: str | None
    created_at: datetime


class NextActionView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: int
    job_opportunity_id: str | None
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
    created_at: datetime
    updated_at: datetime


__all__ = [
    "JobOpportunityDirectionLinkView",
    "JobOpportunityView",
    "JobOutcome",
    "JobPhase",
    "NextActionClose",
    "NextActionCreate",
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
    "ProcessEventAppend",
    "ProcessEventCorrection",
    "ProcessEventKind",
    "ProcessEventView",
    "ProcessSourceKind",
]
