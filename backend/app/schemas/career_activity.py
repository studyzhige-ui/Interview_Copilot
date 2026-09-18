"""Read-only event-envelope projection for Career OS activity surfaces."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue


class ActivityObjectReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str
    id: str
    version: int | None = None


class CareerActivityEvent(BaseModel):
    """Contract-shaped envelope over a canonical event or owner projection."""

    model_config = ConfigDict(extra="forbid")

    event_id: str
    event_kind: str
    event_category: Literal["domain", "harness", "experience"]
    schema_version: int = Field(ge=1)
    occurred_at: datetime
    sequence_or_cursor: str
    user_scope: str
    conversation_id: str | None = None
    turn_id: str | None = None
    task_id: str | None = None
    operation_id: str | None = None
    tool_call_id: str | None = None
    interaction_id: str | None = None
    object_references: list[ActivityObjectReference] = Field(default_factory=list)
    replayable: bool
    payload: dict[str, JsonValue]


__all__ = ["ActivityObjectReference", "CareerActivityEvent"]
