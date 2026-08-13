"""Read-only projection for one durable Agent Tool Call.

The projection exposes the same ``call_id`` used by live SSE and persisted
History blocks.  It is deliberately not a second Tool log: all fields are
read from :class:`AgentToolCall` and redacted again at the presentation
boundary.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, JsonValue, PositiveInt


class AgentToolCallAuditView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    call_id: str
    turn_id: str
    tool_name: str
    effect: str
    status: str
    dispatch_generation: PositiveInt
    policy_decision: str
    policy_reason: str
    arguments: dict[str, JsonValue]
    result: JsonValue | None
    error: str | None
    timeout_seconds: float
    duration_ms: float | None
    started_at: datetime
    completed_at: datetime | None


__all__ = ["AgentToolCallAuditView"]
