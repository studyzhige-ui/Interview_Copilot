"""Typed commands and reads for inferred AbilitySignal product state."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, PositiveInt, model_validator


AbilitySignalStatus = Literal["active", "disputed", "invalidated", "superseded"]
AbilityScopeKind = Literal[
    "general",
    "career_direction",
    "job_opportunity",
    "interview_record",
]
AbilitySourceKind = Literal[
    "interview_record",
    "interview_qa",
    "conversation_message",
    "agent_tool_call",
    "process_event",
    "artifact_version",
]


class AbilityScopeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: AbilityScopeKind = "general"
    ref_id: str | None = Field(default=None, min_length=1, max_length=128)

    @model_validator(mode="after")
    def scope_shape(self):
        if self.kind == "general" and self.ref_id is not None:
            raise ValueError("general scope cannot carry ref_id")
        if self.kind != "general" and self.ref_id is None:
            raise ValueError(f"{self.kind} scope requires ref_id")
        return self


class AbilitySourceRefInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: AbilitySourceKind
    source_id: str = Field(min_length=1, max_length=128)


class AbilitySignalCreateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic: str = Field(min_length=1, max_length=200)
    signal_type: str = Field(min_length=1, max_length=64)
    level: str | None = Field(default=None, max_length=64)
    score: float | None = None
    summary: str = Field(min_length=1, max_length=4_000)
    confidence: float = Field(ge=0, le=1)
    limitations: str | None = Field(default=None, max_length=4_000)
    scope: AbilityScopeInput = Field(default_factory=AbilityScopeInput)
    formed_at: datetime
    rubric_version: str | None = Field(default=None, max_length=64)
    sources: list[AbilitySourceRefInput] = Field(min_length=1, max_length=100)


class AbilitySignalSourceView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    source_kind: AbilitySourceKind
    source_id: str
    source_version: str | None


class AbilitySignalView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: int
    topic: str
    signal_type: str
    level: str | None
    score: float | None
    summary: str
    confidence: float | None
    limitations: str | None
    scope_kind: AbilityScopeKind
    scope_ref_id: str | None
    formed_at: datetime
    rubric_version: str | None
    status: AbilitySignalStatus
    status_reason: str | None
    supersedes_signal_id: str | None
    version: PositiveInt
    created_at: datetime
    updated_at: datetime
    status_changed_at: datetime
    sources: list[AbilitySignalSourceView]


class AbilitySignalStatusChangeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: PositiveInt
    reason: str = Field(min_length=1, max_length=4_000)


__all__ = [
    "AbilityScopeInput",
    "AbilityScopeKind",
    "AbilitySignalCreateInput",
    "AbilitySignalSourceView",
    "AbilitySignalStatus",
    "AbilitySignalStatusChangeInput",
    "AbilitySignalView",
    "AbilitySourceKind",
    "AbilitySourceRefInput",
]
