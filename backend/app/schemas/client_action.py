"""Typed contracts for product-owned Client Actions.

Client Actions are durable, reversible client effects attached to a Tool Call.
They never own Career Domain state and their acknowledgements never prove an
Application Operation succeeded.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator
from app.interviews.domain.specification import InterviewPurpose, InterviewSpecification


ClientActionOutcome = Literal[
    "acknowledged",
    "refused",
    "unsupported",
    "failed",
    "expired",
]
MockClientActionName = Literal[
    "mock_interview.prefill",
    "mock_interview.check_readiness",
    "mock_interview.enter_live",
]
ClientActionName = Literal[
    "mock_interview.prefill",
    "mock_interview.check_readiness",
    "mock_interview.enter_live",
    "interview.preparation.open",
]


class MockPrefillPayload(BaseModel):
    model_config = ConfigDict(
        extra="forbid", json_schema_serialization_defaults_required=True
    )

    kind: Literal["mock_prefill"] = "mock_prefill"
    input_mode: Literal["text", "voice"] = "voice"
    jd_snapshot_id: str | None = Field(default=None, min_length=1, max_length=36)
    jd_snapshot_version: int | None = Field(default=None, ge=1)
    purpose: InterviewPurpose = "full"
    focus: str | None = Field(default=None, min_length=2, max_length=1000)
    resume_id: str | None = Field(default=None, min_length=1, max_length=128)
    resume_version_id: str | None = Field(default=None, min_length=1, max_length=128)
    resume_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    jd_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    jd_text: str = Field(default="", max_length=50_000)
    interviewer_style: Literal["friendly", "professional", "rigorous", "pressure"]
    target_question_count: Literal[15, 20, 30]
    job_opportunity_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=35,
    )

    @model_validator(mode="after")
    def validate_purpose(self):
        spec = InterviewSpecification(purpose=self.purpose, focus=self.focus)
        if spec.purpose != "focused_practice" and not self.resume_id:
            raise ValueError("This purpose requires a resume")
        if spec.purpose == "full" and len(self.jd_text.strip()) < 20:
            raise ValueError("Full interview requires a JD")
        self.focus = spec.focus
        return self


class MockReadinessPayload(BaseModel):
    model_config = ConfigDict(
        extra="forbid", json_schema_serialization_defaults_required=True
    )

    kind: Literal["mock_readiness"] = "mock_readiness"
    requirements: list[Literal["microphone"]] = Field(
        default_factory=lambda: ["microphone"],
        min_length=1,
        max_length=1,
    )


class MockEnterLivePayload(BaseModel):
    model_config = ConfigDict(
        extra="forbid", json_schema_serialization_defaults_required=True
    )

    kind: Literal["mock_enter_live"] = "mock_enter_live"
    input_mode: Literal["text", "voice"] = "voice"
    record_id: str = Field(min_length=1, max_length=128)
    conversation_id: str = Field(min_length=1, max_length=128)
    runtime_status: Literal["mock_in_progress"] = "mock_in_progress"


class InterviewPreparationOpenPayload(BaseModel):
    model_config = ConfigDict(
        extra="forbid", json_schema_serialization_defaults_required=True
    )

    kind: Literal["interview_preparation_open"] = "interview_preparation_open"
    interview_id: str = Field(min_length=1, max_length=128)
    opportunity_id: str = Field(min_length=1, max_length=35)
    expected_interview_version: int = Field(ge=1)
    expected_opportunity_version: int = Field(ge=1)
    source_operation_id: str = Field(min_length=1, max_length=36)
    preferred_surface: Literal["interviews"] = "interviews"


MockClientActionPayload = Annotated[
    MockPrefillPayload | MockReadinessPayload | MockEnterLivePayload,
    Field(discriminator="kind"),
]
ClientActionPayload = Annotated[
    MockPrefillPayload
    | MockReadinessPayload
    | MockEnterLivePayload
    | InterviewPreparationOpenPayload,
    Field(discriminator="kind"),
]


class MockClientActionRequest(BaseModel):
    """Durable request stored in the existing AgentInteraction record."""

    model_config = ConfigDict(
        extra="forbid", json_schema_serialization_defaults_required=True
    )

    protocol: Literal["mock_handoff.v1", "client_action.v1"] = "mock_handoff.v1"
    action_id: str = Field(min_length=1, max_length=128)
    action: ClientActionName
    original_client_id: str = Field(min_length=1, max_length=128)
    bound_client_id: str = Field(min_length=1, max_length=128)
    takeover_generation: int = Field(default=0, ge=0)
    takeover_history: list[dict[str, JsonValue]] = Field(default_factory=list)
    payload: ClientActionPayload

    @model_validator(mode="after")
    def validate_action_payload_pair(self) -> "MockClientActionRequest":
        expected = {
            "mock_interview.prefill": "mock_prefill",
            "mock_interview.check_readiness": "mock_readiness",
            "mock_interview.enter_live": "mock_enter_live",
            "interview.preparation.open": "interview_preparation_open",
        }[self.action]
        if self.payload.kind != expected:
            raise ValueError(f"{self.action} requires payload kind {expected}")
        return self


class MockClientActionResultRequest(BaseModel):
    """Authenticated response from the one client bound to an action."""

    model_config = ConfigDict(
        extra="forbid", json_schema_serialization_defaults_required=True
    )

    action_id: str = Field(min_length=1, max_length=128)
    client_id: str = Field(min_length=1, max_length=128)
    expected_version: int = Field(ge=1)
    outcome: ClientActionOutcome
    readiness: Literal["ready"] | None = None
    fallback_mode: Literal["text"] | None = None
    reason: str | None = Field(default=None, max_length=1_000)

    @model_validator(mode="after")
    def validate_outcome(self) -> "MockClientActionResultRequest":
        if self.outcome == "acknowledged" and self.reason is not None:
            raise ValueError("acknowledged actions cannot include a failure reason")
        if self.outcome != "acknowledged" and not (self.reason or "").strip():
            raise ValueError("refused and failed actions require a reason")
        return self


class MockClientActionTakeoverRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid", json_schema_serialization_defaults_required=True
    )

    action_id: str = Field(min_length=1, max_length=128)
    expected_version: int = Field(ge=1)
    client_id: str = Field(min_length=1, max_length=128)


class MockClientActionView(BaseModel):
    model_config = ConfigDict(
        extra="forbid", json_schema_serialization_defaults_required=True
    )

    interaction_id: str
    turn_id: str
    tool_call_id: str
    version: int
    action_id: str
    action: ClientActionName
    payload: ClientActionPayload
    takeover_generation: int
    created_at: datetime


class MockClientActionResolutionResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid", json_schema_serialization_defaults_required=True
    )

    action_id: str
    interaction_id: str
    accepted: bool = True
    replayed: bool = False
    turn_status: Literal[
        "pending", "running", "waiting", "completed", "blocked", "failed", "cancelled"
    ]
    dispatch_generation: int = Field(ge=1)


__all__ = [
    "ClientActionOutcome",
    "ClientActionName",
    "ClientActionPayload",
    "InterviewPreparationOpenPayload",
    "MockClientActionName",
    "MockClientActionPayload",
    "MockClientActionRequest",
    "MockClientActionResolutionResponse",
    "MockClientActionResultRequest",
    "MockClientActionTakeoverRequest",
    "MockClientActionView",
    "MockEnterLivePayload",
    "MockPrefillPayload",
    "MockReadinessPayload",
]
