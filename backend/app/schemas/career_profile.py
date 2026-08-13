"""Typed CareerProfile commands and aggregate projections."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, PositiveInt, model_validator


DirectionLifecycle = Literal["exploring", "active", "paused", "archived"]
ConfirmationKind = Literal["user_edit", "conversation_message"]


class ConfirmationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: ConfirmationKind
    source_message_id: PositiveInt | None = None

    @model_validator(mode="after")
    def source_matches_kind(self):
        if self.kind == "conversation_message" and self.source_message_id is None:
            raise ValueError(
                "conversation_message confirmation requires its message id"
            )
        if self.kind == "user_edit" and self.source_message_id is not None:
            raise ValueError("user_edit confirmation cannot claim a message source")
        return self


class _DatedFact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_date: date | None = None
    end_date: date | None = None

    @model_validator(mode="after")
    def dates_are_ordered(self):
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date cannot precede start_date")
        return self


class EducationFactInput(_DatedFact):
    kind: Literal["education"]
    institution: str = Field(min_length=1, max_length=240)
    degree: str | None = Field(default=None, max_length=160)
    field_of_study: str | None = Field(default=None, max_length=160)
    description: str | None = Field(default=None, max_length=2_000)


class ExperienceFactInput(_DatedFact):
    kind: Literal["experience"]
    organization: str = Field(min_length=1, max_length=240)
    role: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4_000)


class ProjectFactInput(_DatedFact):
    kind: Literal["project"]
    name: str = Field(min_length=1, max_length=240)
    role: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=4_000)
    technologies: list[str] = Field(default_factory=list, max_length=50)


class SkillFactInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["skill"]
    name: str = Field(min_length=1, max_length=160)
    category: str | None = Field(default=None, max_length=120)


class AchievementFactInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["achievement"]
    title: str = Field(min_length=1, max_length=240)
    description: str | None = Field(default=None, max_length=2_000)
    occurred_on: date | None = None


class ContactFactInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["contact"]
    channel: Literal["email", "phone", "website", "other"]
    value: str = Field(min_length=1, max_length=500)


class LocationFactInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["location"]
    value: str = Field(min_length=1, max_length=240)


PersonalFactInput = Annotated[
    EducationFactInput
    | ExperienceFactInput
    | ProjectFactInput
    | SkillFactInput
    | AchievementFactInput
    | ContactFactInput
    | LocationFactInput,
    Field(discriminator="kind"),
]


class ConfirmedPersonalFact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    value: PersonalFactInput
    confirmed_source_kind: Literal[
        "user_edit", "conversation_message", "draft_acceptance"
    ]
    confirmed_source_id: str | None
    confirmed_at: datetime


class DirectionCriteria(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role_keywords: list[str] = Field(default_factory=list, max_length=30)
    seniority: list[str] = Field(default_factory=list, max_length=10)
    locations: list[str] = Field(default_factory=list, max_length=30)
    work_modes: list[Literal["onsite", "hybrid", "remote"]] = Field(
        default_factory=list
    )
    salary_min: int | None = Field(default=None, ge=0)
    salary_max: int | None = Field(default=None, ge=0)
    salary_currency: str | None = Field(default=None, min_length=3, max_length=3)
    industries: list[str] = Field(default_factory=list, max_length=30)
    technologies: list[str] = Field(default_factory=list, max_length=50)
    exclusions: list[str] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def salary_is_ordered(self):
        if (
            self.salary_min is not None
            and self.salary_max is not None
            and self.salary_max < self.salary_min
        ):
            raise ValueError("salary_max cannot be lower than salary_min")
        return self


class DirectionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=160)
    criteria: DirectionCriteria = Field(default_factory=DirectionCriteria)
    lifecycle: DirectionLifecycle = "exploring"
    priority: int = Field(default=0, ge=0)


class FactDraftChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal["upsert", "remove"]
    target_fact_id: str | None = Field(default=None, min_length=1, max_length=128)
    fact: PersonalFactInput | None = None

    @model_validator(mode="after")
    def operation_shape(self):
        if self.operation == "upsert" and self.fact is None:
            raise ValueError("upsert requires fact")
        if self.operation == "remove" and (
            self.target_fact_id is None or self.fact is not None
        ):
            raise ValueError("remove requires only target_fact_id")
        return self


class DirectionDraftChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal["upsert", "archive"]
    target_direction_id: str | None = Field(default=None, min_length=1, max_length=128)
    direction: DirectionInput | None = None

    @model_validator(mode="after")
    def operation_shape(self):
        if self.operation == "upsert" and self.direction is None:
            raise ValueError("upsert requires direction")
        if self.operation == "archive" and (
            self.target_direction_id is None or self.direction is not None
        ):
            raise ValueError("archive requires only target_direction_id")
        return self


ProfileDraftSourceKind = Literal[
    "artifact_version", "conversation_message", "model_inference"
]
PersistedProfileDraftSourceKind = Literal[
    "artifact_version", "resume", "conversation_message", "model_inference"
]


class CareerProfileDraftInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_kind: ProfileDraftSourceKind
    source_id: str = Field(min_length=1, max_length=128)
    proposed_facts: list[FactDraftChange] = Field(default_factory=list, max_length=200)
    proposed_directions: list[DirectionDraftChange] = Field(
        default_factory=list,
        max_length=50,
    )

    @model_validator(mode="after")
    def is_not_empty(self):
        if not self.proposed_facts and not self.proposed_directions:
            raise ValueError("a draft change-set cannot be empty")
        return self


class CareerProfileDirectionView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    label: str
    criteria: DirectionCriteria = Field(validation_alias="criteria_json")
    lifecycle: DirectionLifecycle
    priority: int
    confirmed_source_kind: str
    confirmed_source_id: str | None
    confirmed_at: datetime


class CareerProfileView(BaseModel):
    id: str
    user_id: int
    personal_facts: list[ConfirmedPersonalFact]
    directions: list[CareerProfileDirectionView]
    version: PositiveInt
    created_at: datetime
    updated_at: datetime


class PersonalFactMutationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_profile_version: PositiveInt
    fact: PersonalFactInput
    confirmation: ConfirmationInput


class PersonalFactRemovalInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_profile_version: PositiveInt
    confirmation: ConfirmationInput


class DirectionMutationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_profile_version: PositiveInt
    direction: DirectionInput
    confirmation: ConfirmationInput


class DirectionLifecycleMutationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_profile_version: PositiveInt
    lifecycle: DirectionLifecycle
    confirmation: ConfirmationInput


class CareerProfileDraftResolutionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_draft_version: PositiveInt
    expected_profile_version: PositiveInt | None = None
    resolution_note: str | None = Field(default=None, max_length=2_000)


class CareerProfileCandidateDecisionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: str = Field(min_length=1, max_length=37)
    expected_version: PositiveInt
    decision: Literal["accept", "reject"]
    note: str | None = Field(default=None, max_length=2_000)


class CareerProfileCandidateBatchResolutionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_draft_version: PositiveInt
    expected_profile_version: PositiveInt
    decisions: list[CareerProfileCandidateDecisionInput] = Field(
        min_length=1, max_length=250
    )


class CareerProfileCandidateItemView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    item_kind: Literal["fact", "direction"]
    position: int
    payload: dict = Field(validation_alias="payload_json")
    conflict_kind: Literal["none", "duplicate", "conflict", "missing_target"]
    current_value: dict | None = Field(
        default=None, validation_alias="current_value_json"
    )
    status: Literal["pending", "accepted", "rejected"]
    resolution_note: str | None
    version: PositiveInt
    created_at: datetime
    resolved_at: datetime | None


class CareerProfileDraftView(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str
    career_profile_id: str
    # Existing pre-cut-over draft rows may still identify their historical
    # source as ``resume``. Runtime input no longer accepts that value.
    source_kind: PersistedProfileDraftSourceKind
    source_id: str
    base_profile_version: PositiveInt
    proposed_facts: list[FactDraftChange] = Field(
        validation_alias="proposed_facts_json"
    )
    proposed_directions: list[DirectionDraftChange] = Field(
        validation_alias="proposed_directions_json"
    )
    status: Literal["pending", "accepted", "rejected"]
    resolution_note: str | None
    version: PositiveInt
    created_at: datetime
    resolved_at: datetime | None
    candidates: list[CareerProfileCandidateItemView] = Field(default_factory=list)


class CareerProfileCandidateResolutionView(BaseModel):
    profile: CareerProfileView
    draft: CareerProfileDraftView


__all__ = [
    "CareerProfileDirectionView",
    "CareerProfileCandidateBatchResolutionInput",
    "CareerProfileCandidateDecisionInput",
    "CareerProfileCandidateItemView",
    "CareerProfileCandidateResolutionView",
    "CareerProfileDraftInput",
    "CareerProfileDraftResolutionInput",
    "CareerProfileDraftView",
    "CareerProfileView",
    "ConfirmationInput",
    "ConfirmedPersonalFact",
    "DirectionCriteria",
    "DirectionDraftChange",
    "DirectionInput",
    "DirectionLifecycleMutationInput",
    "DirectionMutationInput",
    "DirectionLifecycle",
    "FactDraftChange",
    "PersonalFactInput",
    "PersonalFactMutationInput",
    "PersonalFactRemovalInput",
]
