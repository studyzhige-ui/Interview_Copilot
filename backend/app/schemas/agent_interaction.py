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
    "fact_confirmation",
    "profile_update_confirmation",
    "client_readiness",
]
InteractionStatus = Literal["pending", "resolved", "rejected", "cancelled"]
InteractionResolutionStatus = Literal["resolved", "rejected", "cancelled"]


class InteractionPayload(RootModel[dict[str, JsonValue]]):
    """A structured JSON object for callers without a narrower payload model."""


class ToolInteractionRequest(BaseModel):
    """Minimal user-visible facts for a paused concrete Tool Call."""

    model_config = ConfigDict(
        extra="forbid", json_schema_serialization_defaults_required=True
    )

    tool_name: str
    call_id: str
    effect: str
    reason: str
    arguments: dict[str, JsonValue]


class ResolveInteractionRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid", json_schema_serialization_defaults_required=True
    )

    expected_version: PositiveInt
    status: InteractionResolutionStatus
    resolution: InteractionPayload
    resolution_identity: str | None = Field(default=None, max_length=128)


class AgentInteractionView(BaseModel):
    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: str
    turn_id: str
    tool_call_id: str | None
    kind: InteractionKind
    schema_version: PositiveInt
    status: InteractionStatus
    request: dict[str, JsonValue] = Field(validation_alias="request_json")
    resolution: dict[str, JsonValue] | None = Field(
        default=None,
        validation_alias="resolution_json",
    )
    version: PositiveInt
    created_at: datetime
    expires_at: datetime | None
    resolved_at: datetime | None
    resolution_identity: str | None


class ResolveInteractionResponse(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    interaction: AgentInteractionView
    turn_status: Literal["pending", "cancelled"]
    dispatch_generation: PositiveInt


class PendingInteractionProjection(BaseModel):
    """User-level query projection; the Interaction remains the sole owner."""

    model_config = ConfigDict(
        extra="forbid", json_schema_serialization_defaults_required=True
    )

    conversation_id: str
    turn_status: str
    interaction: AgentInteractionView


__all__ = [
    "AgentInteractionView",
    "InteractionKind",
    "InteractionPayload",
    "InteractionResolutionStatus",
    "InteractionStatus",
    "PendingInteractionProjection",
    "ResolveInteractionRequest",
    "ResolveInteractionResponse",
    "ToolInteractionRequest",
]
