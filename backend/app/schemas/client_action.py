"""Typed contracts for the first product-owned Client Action handler.

Client Action is a delivery effect attached to an existing Tool Call, not a
domain object or a general-purpose UI protocol.  These contracts deliberately
cover only the Mock Interview handoff that the product implements today.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator


ClientActionOutcome = Literal["acknowledged", "refused", "failed"]
MockClientActionName = Literal[
    "mock_interview.prefill",
    "mock_interview.check_readiness",
    "mock_interview.enter_live",
]


class MockPrefillPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["mock_prefill"] = "mock_prefill"
    resume_id: str = Field(min_length=1, max_length=128)
    jd_text: str = Field(min_length=20, max_length=50_000)
    interviewer_style: Literal["friendly", "professional", "rigorous", "pressure"]
    target_question_count: Literal[15, 20, 30]
    job_opportunity_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=35,
    )


class MockReadinessPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["mock_readiness"] = "mock_readiness"
    requirements: list[Literal["microphone"]] = Field(
        default_factory=lambda: ["microphone"],
        min_length=1,
        max_length=1,
    )


class MockEnterLivePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["mock_enter_live"] = "mock_enter_live"
    record_id: str = Field(min_length=1, max_length=128)
    conversation_id: str = Field(min_length=1, max_length=128)
    runtime_status: Literal["mock_in_progress"] = "mock_in_progress"


MockClientActionPayload = Annotated[
    MockPrefillPayload | MockReadinessPayload | MockEnterLivePayload,
    Field(discriminator="kind"),
]


class MockClientActionRequest(BaseModel):
    """Durable request stored in the existing AgentInteraction record."""

    model_config = ConfigDict(extra="forbid")

    protocol: Literal["mock_handoff.v1"] = "mock_handoff.v1"
    action_id: str = Field(min_length=1, max_length=128)
    action: MockClientActionName
    original_client_id: str = Field(min_length=1, max_length=128)
    bound_client_id: str = Field(min_length=1, max_length=128)
    takeover_generation: int = Field(default=0, ge=0)
    takeover_history: list[dict[str, JsonValue]] = Field(default_factory=list)
    payload: MockClientActionPayload

    @model_validator(mode="after")
    def validate_action_payload_pair(self) -> "MockClientActionRequest":
        expected = {
            "mock_interview.prefill": "mock_prefill",
            "mock_interview.check_readiness": "mock_readiness",
            "mock_interview.enter_live": "mock_enter_live",
        }[self.action]
        if self.payload.kind != expected:
            raise ValueError(f"{self.action} requires payload kind {expected}")
        return self


class MockClientActionResultRequest(BaseModel):
    """Authenticated response from the one client bound to an action."""

    model_config = ConfigDict(extra="forbid")

    action_id: str = Field(min_length=1, max_length=128)
    client_id: str = Field(min_length=1, max_length=128)
    expected_version: int = Field(ge=1)
    outcome: ClientActionOutcome
    readiness: Literal["ready"] | None = None
    reason: str | None = Field(default=None, max_length=1_000)

    @model_validator(mode="after")
    def validate_outcome(self) -> "MockClientActionResultRequest":
        if self.outcome == "acknowledged" and self.reason is not None:
            raise ValueError("acknowledged actions cannot include a failure reason")
        if self.outcome != "acknowledged" and not (self.reason or "").strip():
            raise ValueError("refused and failed actions require a reason")
        return self


class MockClientActionTakeoverRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_id: str = Field(min_length=1, max_length=128)
    expected_version: int = Field(ge=1)
    client_id: str = Field(min_length=1, max_length=128)


class MockClientActionView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    interaction_id: str
    turn_id: str
    tool_call_id: str
    version: int
    action_id: str
    action: MockClientActionName
    payload: MockClientActionPayload
    takeover_generation: int
    created_at: datetime


class MockClientActionResolutionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

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
