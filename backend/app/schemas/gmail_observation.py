"""Typed Gmail Observation, event-candidate, and review-card contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from app.schemas.job_opportunity import ProcessEventKind


class GmailIncrementalMessage(BaseModel):
    """Safe provider output accepted by deterministic Observation intake."""

    model_config = ConfigDict(extra="forbid")

    message_id: str = Field(min_length=1, max_length=256)
    thread_id: str = Field(min_length=1, max_length=256)
    history_id: str = Field(min_length=1, max_length=256)
    content_available: bool = True
    received_at: AwareDatetime | None = None
    from_hint: str = Field(default="", max_length=320)
    subject: str = Field(default="", max_length=500)
    snippet: str = Field(default="", max_length=1_000)


class GmailIncrementalBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cursor_before: str | None = Field(default=None, max_length=256)
    cursor_after: str = Field(min_length=1, max_length=256)
    initialized_cursor: bool = False
    messages: list[GmailIncrementalMessage] = Field(
        default_factory=list, max_length=100
    )


class GmailObservationSnapshotView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    observation_id: str
    snapshot_version: str
    provider_history_id: str
    provider_message_id: str
    provider_thread_id: str
    content_available: bool
    received_at: datetime | None
    from_hint: str
    subject: str
    snippet: str
    content_sha256: str
    observed_at: datetime
    created_at: datetime


class GmailObservationView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    gmail_account_id: str
    provider_message_id: str
    provider_thread_id: str
    received_at: datetime | None
    observed_at: datetime
    status: Literal[
        "unreviewed",
        "pending_confirmation",
        "applied",
        "dismissed",
        "retracted",
    ]
    version: int
    candidate_event_kind: str | None
    classification_confidence: float | None
    unique_match: bool | None
    analysis_summary: str | None
    matched_job_opportunity_id: str | None
    applied_process_event_id: str | None
    retraction_process_event_id: str | None
    notification_summary: str | None
    created_at: datetime
    updated_at: datetime
    latest_snapshot: GmailObservationSnapshotView


class GmailObservationNewOpportunity(BaseModel):
    """Typed candidate used only by the Gmail Observation workflow."""

    model_config = ConfigDict(extra="forbid")

    company_name: str = Field(min_length=1, max_length=200)
    job_title: str = Field(min_length=1, max_length=300)
    application_provider: str = Field(min_length=1, max_length=80)
    external_application_id: str = Field(min_length=1, max_length=200)
    external_job_id: str | None = Field(default=None, max_length=200)
    source_url: str | None = Field(default=None, max_length=4_000)
    location: str | None = Field(default=None, max_length=200)


class GmailObservationProposal(BaseModel):
    """Semantic result submitted by the bounded automation Turn.

    The deterministic Application Service decides whether it may be applied,
    must become a review card, or is only dismissed.  Confidence never bypasses
    ownership, archived-line, unique-match, or task-scope checks.
    """

    model_config = ConfigDict(extra="forbid")

    observation_id: str = Field(min_length=1, max_length=36)
    expected_version: int = Field(ge=1)
    disposition: Literal["auto_apply", "needs_confirmation", "dismiss"]
    event_kind: ProcessEventKind | None = None
    opportunity_id: str | None = Field(default=None, max_length=35)
    new_opportunity: GmailObservationNewOpportunity | None = None
    occurred_at: AwareDatetime | None = None
    description: str | None = Field(default=None, max_length=10_000)
    step_summary: str | None = Field(default=None, max_length=300)
    confidence: float = Field(default=0, ge=0, le=1)
    unique_match: bool = False
    rationale: str = Field(min_length=1, max_length=4_000)

    @model_validator(mode="after")
    def validate_shape(self) -> "GmailObservationProposal":
        if self.disposition == "dismiss":
            if any(
                value is not None
                for value in (
                    self.event_kind,
                    self.opportunity_id,
                    self.new_opportunity,
                    self.occurred_at,
                    self.description,
                    self.step_summary,
                )
            ):
                raise ValueError("dismiss does not carry a process-event candidate")
            return self
        if self.event_kind is None or self.occurred_at is None or not self.description:
            raise ValueError("event candidate requires kind, time, and description")
        if (self.opportunity_id is None) == (self.new_opportunity is None):
            raise ValueError(
                "event candidate requires exactly one existing or new opportunity"
            )
        if self.event_kind == "hiring_step" and not (self.step_summary or "").strip():
            raise ValueError("hiring_step requires step_summary")
        return self


class GmailObservationCardResolve(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    decision: Literal["approve", "reject", "skip"]
    user_request_identity: str = Field(min_length=1, max_length=256)
    user_request_version: str | None = Field(default=None, max_length=128)
    resolution_note: str | None = Field(default=None, max_length=2_000)
    opportunity_id: str | None = Field(default=None, max_length=35)
    new_opportunity: GmailObservationNewOpportunity | None = None
    event_kind: ProcessEventKind | None = None
    occurred_at: AwareDatetime | None = None
    description: str | None = Field(default=None, max_length=10_000)
    step_summary: str | None = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def validate_resolution(self) -> "GmailObservationCardResolve":
        corrections = (
            self.opportunity_id,
            self.new_opportunity,
            self.event_kind,
            self.occurred_at,
            self.description,
            self.step_summary,
        )
        if self.decision != "approve" and any(
            value is not None for value in corrections
        ):
            raise ValueError("reject/skip cannot carry candidate corrections")
        if self.opportunity_id is not None and self.new_opportunity is not None:
            raise ValueError("choose an existing or new opportunity, not both")
        return self


class GmailObservationRetract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    occurred_at: AwareDatetime
    reason: str = Field(min_length=1, max_length=2_000)
    user_request_identity: str = Field(min_length=1, max_length=256)
    user_request_version: str | None = Field(default=None, max_length=128)


class GmailObservationRebaseline(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm_gap: Literal[True]
    user_request_identity: str = Field(min_length=1, max_length=256)


class GmailObservationReviewCardView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    persistent_task_id: str
    observation_id: str
    source_snapshot_id: str
    status: Literal["pending", "approved", "rejected", "skipped"]
    version: int
    candidate_event_kind: str
    candidate_opportunity_id: str | None
    occurred_at: datetime
    description: str
    step_summary: str | None
    confidence: float
    unique_match: bool
    rationale: str
    new_opportunity_json: dict | None
    process_event_id: str | None
    resolution_note: str | None
    resolved_at: datetime | None
    created_at: datetime
    updated_at: datetime
    source_snapshot: GmailObservationSnapshotView


class GmailObservationSyncView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    initialized_cursor: bool
    cursor_after: str
    observations_created: int = Field(ge=0)
    snapshots_created: int = Field(ge=0)
    triggers_created: int = Field(ge=0)
    turns_admitted: int = Field(ge=0)
    turn_ids: list[str]


class GmailObservationResolutionView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: str
    observation: GmailObservationView
    review_card: GmailObservationReviewCardView | None = None
    process_event_id: str | None = None


__all__ = [
    "GmailIncrementalBatch",
    "GmailIncrementalMessage",
    "GmailObservationCardResolve",
    "GmailObservationNewOpportunity",
    "GmailObservationProposal",
    "GmailObservationRebaseline",
    "GmailObservationRetract",
    "GmailObservationReviewCardView",
    "GmailObservationResolutionView",
    "GmailObservationSnapshotView",
    "GmailObservationSyncView",
    "GmailObservationView",
]
