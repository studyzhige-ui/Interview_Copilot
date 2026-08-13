"""Typed commands and read models for PersistentTask automation intake."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    PositiveInt,
    field_validator,
    model_validator,
)

from app.schemas.conversation_lifecycle import ConversationDeletionImpact


PersistentTaskState = Literal["active", "paused"]
AutomationTriggerKind = Literal["scheduled", "event", "manual"]


class ScheduledTriggerSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["scheduled"] = "scheduled"
    schedule: str = Field(min_length=1, max_length=200)
    timezone: str = Field(min_length=1, max_length=80)

    @model_validator(mode="after")
    def validate_schedule(self) -> "ScheduledTriggerSpec":
        from app.services.persistent_task_schedule import validate_cron_schedule

        self.schedule, self.timezone = validate_cron_schedule(
            self.schedule, self.timezone
        )
        return self


class EventTriggerSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["event"] = "event"
    # Only the real first-party Gmail History intake exists today.  Keeping
    # this provider-specific prevents the UI/API from pretending Outlook,
    # Calendar, or a generic event bus is implemented.
    connector: Literal["gmail"] = "gmail"
    event_types: list[str] = Field(min_length=1, max_length=20)

    @field_validator("event_types")
    @classmethod
    def normalize_event_types(cls, value: list[str]) -> list[str]:
        return _normalized_strings(value, field="event_types", max_length=120)


PersistentTaskTriggerSpec = Annotated[
    ScheduledTriggerSpec | EventTriggerSpec,
    Field(discriminator="kind"),
]


class PersistentTaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=120)
    instruction: str = Field(min_length=1, max_length=5_000)
    trigger: PersistentTaskTriggerSpec
    read_scope: list[str] = Field(default_factory=list, max_length=50)
    action_scope: list[str] = Field(default_factory=list, max_length=50)
    allowed_tool_names: list[str] = Field(default_factory=list, max_length=64)
    skill_ids: list[PositiveInt] = Field(default_factory=list, max_length=20)
    user_request_identity: str = Field(min_length=1, max_length=256)
    user_request_version: str | None = Field(default=None, max_length=128)
    idempotency_key: str = Field(min_length=1, max_length=200)

    @field_validator("read_scope", "action_scope")
    @classmethod
    def normalize_scope(cls, value: list[str]) -> list[str]:
        return _normalized_strings(value, field="scope", max_length=300)

    @field_validator("allowed_tool_names")
    @classmethod
    def normalize_tools(cls, value: list[str]) -> list[str]:
        return _normalized_strings(
            value,
            field="allowed_tool_names",
            max_length=128,
            sort=True,
        )


class PersistentTaskUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: PositiveInt
    title: str | None = Field(default=None, min_length=1, max_length=120)
    instruction: str | None = Field(default=None, min_length=1, max_length=5_000)
    trigger: PersistentTaskTriggerSpec | None = None
    read_scope: list[str] | None = Field(default=None, max_length=50)
    action_scope: list[str] | None = Field(default=None, max_length=50)
    allowed_tool_names: list[str] | None = Field(default=None, max_length=64)
    skill_ids: list[PositiveInt] | None = Field(default=None, max_length=20)
    user_request_identity: str = Field(min_length=1, max_length=256)
    user_request_version: str | None = Field(default=None, max_length=128)

    @field_validator("read_scope", "action_scope")
    @classmethod
    def normalize_optional_scope(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return _normalized_strings(value, field="scope", max_length=300)

    @field_validator("allowed_tool_names")
    @classmethod
    def normalize_optional_tools(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return _normalized_strings(
            value,
            field="allowed_tool_names",
            max_length=128,
            sort=True,
        )

    @model_validator(mode="after")
    def require_definition_change(self) -> "PersistentTaskUpdate":
        if all(
            value is None
            for value in (
                self.title,
                self.instruction,
                self.trigger,
                self.read_scope,
                self.action_scope,
                self.allowed_tool_names,
                self.skill_ids,
            )
        ):
            raise ValueError("at least one task definition field must change")
        return self


class PersistentTaskStateChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: PositiveInt
    state: PersistentTaskState
    user_request_identity: str = Field(min_length=1, max_length=256)
    user_request_version: str | None = Field(default=None, max_length=128)


class PersistentTaskDelete(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: PositiveInt
    user_request_identity: str = Field(min_length=1, max_length=256)
    user_request_version: str | None = Field(default=None, max_length=128)
    confirmation_token: str = Field(min_length=64, max_length=64)
    confirm_task_id: str = Field(min_length=1, max_length=128)


class PersistentTaskDeletionImpact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str
    title: str
    version: int
    pending_trigger_count: int
    confirmation_token: str
    conversation: ConversationDeletionImpact
    disclosures: list[str] = Field(default_factory=list)


class PersistentTaskTriggerInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: AutomationTriggerKind
    occurred_at: AwareDatetime
    observed_at: AwareDatetime | None = None
    source_identity: str = Field(min_length=1, max_length=256)
    source_version: str | None = Field(default=None, max_length=128)
    summary: str = Field(min_length=1, max_length=4_000)
    cursor_after: str | None = Field(default=None, max_length=1_024)
    idempotency_key: str = Field(min_length=1, max_length=200)


class PersistentTaskView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: int
    conversation_id: str
    title: str
    instruction: str
    state: PersistentTaskState
    version: int
    trigger_kind: Literal["scheduled", "event"]
    trigger_spec_json: dict
    read_scope_json: list[str]
    action_scope_json: list[str]
    allowed_tool_names_json: list[str]
    skill_refs_json: list[dict]
    user_request_identity: str
    user_request_version: str | None
    compensation_blocked_at: datetime | None
    next_due_at: datetime | None
    created_at: datetime
    updated_at: datetime


class PersistentTaskTriggerView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    persistent_task_id: str
    kind: AutomationTriggerKind
    occurred_at: datetime
    observed_at: datetime
    source_identity: str
    source_version: str | None
    summary: str
    cursor_after: str | None
    admitted_turn_id: str | None
    admitted_at: datetime | None
    created_at: datetime


class PersistentTaskTriggerAdmissionView(BaseModel):
    """Safe intake result; a retained trigger is not represented as a run."""

    model_config = ConfigDict(extra="forbid")

    trigger_id: str | None
    status: Literal["admitted", "pending", "already_admitted", "empty"]
    reason: str | None
    turn_id: str | None
    merged_trigger_ids: list[str]
    pending_trigger_count: int = Field(ge=0)


class PersistentTaskEligibleToolView(BaseModel):
    """Current concrete cloud-sustainable read Tool exposed to the UI."""

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str


def _normalized_strings(
    values: list[str],
    *,
    field: str,
    max_length: int,
    sort: bool = False,
) -> list[str]:
    normalized: list[str] = []
    for value in values:
        item = value.strip()
        if not item:
            raise ValueError(f"{field} entries must not be empty")
        if len(item) > max_length:
            raise ValueError(f"{field} entries must not exceed {max_length} chars")
        if item not in normalized:
            normalized.append(item)
    return sorted(normalized) if sort else normalized


__all__ = [
    "AutomationTriggerKind",
    "EventTriggerSpec",
    "PersistentTaskCreate",
    "PersistentTaskDelete",
    "PersistentTaskDeletionImpact",
    "PersistentTaskEligibleToolView",
    "PersistentTaskState",
    "PersistentTaskStateChange",
    "PersistentTaskTriggerInput",
    "PersistentTaskTriggerAdmissionView",
    "PersistentTaskTriggerSpec",
    "PersistentTaskTriggerView",
    "PersistentTaskUpdate",
    "PersistentTaskView",
    "ScheduledTriggerSpec",
]
