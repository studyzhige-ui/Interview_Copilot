"""Transport-neutral contracts for the minimal flat AgentTask plan."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, PositiveInt, model_validator


AgentTaskPhaseStatus = Literal["pending", "in_progress", "completed", "skipped"]
AgentTaskReferenceOwner = Literal[
    "tool_call",
    "artifact",
    "artifact_version",
    "domain_record",
]


class AgentTaskIdentityRef(BaseModel):
    """A reference to an authoritative result, never copied result content."""

    model_config = ConfigDict(extra="forbid")

    owner: AgentTaskReferenceOwner
    identity: str = Field(min_length=1, max_length=256)


class AgentTaskPhase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(
        min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$"
    )
    title: str = Field(min_length=1, max_length=240)
    status: AgentTaskPhaseStatus
    result_refs: list[AgentTaskIdentityRef] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_references(self) -> "AgentTaskPhase":
        refs = [(ref.owner, ref.identity) for ref in self.result_refs]
        if len(refs) != len(set(refs)):
            raise ValueError("result_refs must be unique within a phase")
        return self


class AgentTaskPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    objective: str = Field(min_length=1, max_length=2_000)
    completion_conditions: list[str] = Field(min_length=1)
    phases: list[AgentTaskPhase] = Field(min_length=2)

    @model_validator(mode="after")
    def validate_flat_plan(self) -> "AgentTaskPlan":
        phase_ids = [phase.id for phase in self.phases]
        if len(phase_ids) != len(set(phase_ids)):
            raise ValueError("phase ids must be unique")
        if sum(phase.status == "in_progress" for phase in self.phases) > 1:
            raise ValueError("at most one phase may be in_progress")
        if any(not condition.strip() for condition in self.completion_conditions):
            raise ValueError("completion conditions must not be blank")
        return self


class CreateAgentTaskRequest(AgentTaskPlan):
    idempotency_key: str = Field(min_length=1, max_length=200)


class ReviseAgentTaskRequest(AgentTaskPlan):
    expected_version: PositiveInt
    idempotency_key: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=2_000)


class AgentTaskView(AgentTaskPlan):
    model_config = ConfigDict(from_attributes=True)

    completion_conditions: list[str] = Field(
        validation_alias="completion_conditions_json"
    )
    phases: list[AgentTaskPhase] = Field(validation_alias="phases_json")
    id: str
    turn_id: str
    version: PositiveInt
    created_at: datetime
    updated_at: datetime
    frozen_at: datetime | None


__all__ = [
    "AgentTaskIdentityRef",
    "AgentTaskPhase",
    "AgentTaskPhaseStatus",
    "AgentTaskPlan",
    "AgentTaskReferenceOwner",
    "AgentTaskView",
    "CreateAgentTaskRequest",
    "ReviseAgentTaskRequest",
]
