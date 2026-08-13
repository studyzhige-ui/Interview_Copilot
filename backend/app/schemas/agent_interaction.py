"""Transport-neutral contracts for a durable waiting Interaction.

The concrete request/resolution fields remain owned by the Tool or client
handler that creates them.  ``InteractionPayload`` is only the JSON-object
boundary used when no narrower Pydantic model is needed; it is not a generic
UI schema or a registry of interaction implementations.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, PositiveInt, RootModel


InteractionKind = Literal[
    "clarification",
    "connection",
    "approval",
    "client_readiness",
]
InteractionStatus = Literal["pending", "resolved", "rejected", "cancelled"]
InteractionResolutionStatus = Literal["resolved", "rejected", "cancelled"]


class InteractionPayload(RootModel[dict[str, JsonValue]]):
    """A structured JSON object for callers without a narrower payload model."""


class ToolInteractionRequest(BaseModel):
    """Minimal user-visible facts for a paused concrete Tool Call."""

    model_config = ConfigDict(extra="forbid")

    tool_name: str
    call_id: str
    effect: str
    reason: str
    arguments: dict[str, JsonValue]


class ResolveInteractionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: PositiveInt
    status: InteractionResolutionStatus
    resolution: InteractionPayload


class AgentInteractionView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    turn_id: str
    tool_call_id: str | None
    kind: InteractionKind
    status: InteractionStatus
    request: dict[str, JsonValue] = Field(validation_alias="request_json")
    resolution: dict[str, JsonValue] | None = Field(
        default=None,
        validation_alias="resolution_json",
    )
    version: PositiveInt
    created_at: datetime
    resolved_at: datetime | None


class ResolveInteractionResponse(BaseModel):
    interaction: AgentInteractionView
    turn_status: Literal["pending", "cancelled"]
    dispatch_generation: PositiveInt


__all__ = [
    "AgentInteractionView",
    "InteractionKind",
    "InteractionPayload",
    "InteractionResolutionStatus",
    "InteractionStatus",
    "ResolveInteractionRequest",
    "ResolveInteractionResponse",
    "ToolInteractionRequest",
]
