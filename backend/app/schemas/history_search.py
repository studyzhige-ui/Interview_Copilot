"""Exact Interaction Record search projections."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class HistorySearchQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=2, max_length=200)
    conversation_id: str | None = None
    kinds: list[Literal["message", "tool_call"]] = Field(
        default_factory=lambda: ["message", "tool_call"]
    )
    roles: list[Literal["user", "assistant", "tool", "system"]] = Field(
        default_factory=list
    )
    limit: int = Field(default=20, ge=1, le=50)

    @field_validator("query")
    @classmethod
    def normalize_query(cls, value: str) -> str:
        return " ".join(value.split())


class HistorySearchResult(BaseModel):
    kind: Literal["message", "tool_call"]
    identity: str
    conversation_id: str
    conversation_title: str
    conversation_type: str
    turn_id: str | None
    message_id: int | None
    seq: int | None
    role: str | None
    tool_call_id: str | None
    tool_name: str | None
    tool_status: str | None
    occurred_at: datetime
    excerpt: str


class HistorySearchResponse(BaseModel):
    query: str
    count: int
    results: list[HistorySearchResult]


class HistoryRecordDetail(BaseModel):
    """Owner-scoped exact read of one canonical Interaction Record."""

    kind: Literal["message", "tool_call"]
    identity: str
    conversation_id: str
    conversation_title: str
    conversation_type: str
    turn_id: str | None
    message_id: int | None
    seq: int | None
    role: str | None
    tool_call_id: str | None
    tool_name: str | None
    tool_status: str | None
    occurred_at: datetime
    content: str | None = None
    content_blocks: list[dict] = Field(default_factory=list)
    arguments: dict | None = None
    result: dict | None = None
    error: str | None = None


__all__ = [
    "HistoryRecordDetail",
    "HistorySearchQuery",
    "HistorySearchResponse",
    "HistorySearchResult",
]
