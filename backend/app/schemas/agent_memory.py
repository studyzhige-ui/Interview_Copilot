"""Typed user controls and read models for canonical Long-term Agent Memory."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.personalization import CopilotPreferenceView


class AgentMemorySettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=0)
    recall_enabled: bool
    contribution_enabled: bool


class AgentMemorySettingsView(BaseModel):
    recall_enabled: bool
    contribution_enabled: bool
    producer_available: bool
    version: int
    updated_at: datetime | None


class ConversationMemoryControlsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=0)
    recall_override: bool | None = None
    contribution_override: bool | None = None


class ConversationMemoryControlsView(BaseModel):
    conversation_id: str
    recall_override: bool | None
    contribution_override: bool | None
    effective_recall_enabled: bool
    effective_contribution_enabled: bool
    producer_available: bool
    version: int
    updated_at: datetime | None


class AgentMemorySourceView(BaseModel):
    source_turn_identity: str
    source_conversation_identity: str
    observed_at: datetime
    source_deleted_at: datetime | None


class AgentMemoryView(BaseModel):
    id: str
    semantic_key: str
    content: str
    applicability: str
    tags: list[str]
    valence: Literal["effective", "ineffective", "mixed"]
    confidence: float
    status: Literal["active", "invalidated", "deleted"]
    version: int
    formed_at: datetime
    last_confirmed_at: datetime
    last_recalled_at: datetime | None
    recall_count: int
    status_reason: str | None
    invalidated_at: datetime | None
    deleted_at: datetime | None
    created_at: datetime
    updated_at: datetime
    sources: list[AgentMemorySourceView]


class AgentMemoryUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    content: str = Field(min_length=1, max_length=800)
    applicability: str = Field(min_length=1, max_length=400)
    tags: list[str] = Field(default_factory=list, max_length=12)

    @field_validator("content", "applicability")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return " ".join(value.split())

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, value: list[str]) -> list[str]:
        tags: list[str] = []
        for raw in value:
            tag = raw.strip().casefold()
            if not tag or len(tag) > 40:
                raise ValueError("tags must contain 1-40 characters")
            if tag not in tags:
                tags.append(tag)
        return tags


class AgentMemoryStatusCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=500)


class AgentMemoryPromotionCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_memory_version: int = Field(ge=1)
    expected_preference_version: int = Field(ge=0)
    instruction: str = Field(min_length=1, max_length=1_000)

    @field_validator("instruction")
    @classmethod
    def normalize_instruction(cls, value: str) -> str:
        return " ".join(value.split())


class AgentMemoryPromotionView(BaseModel):
    memory: AgentMemoryView
    preference: CopilotPreferenceView


__all__ = [
    "AgentMemoryPromotionCommand",
    "AgentMemoryPromotionView",
    "AgentMemorySettingsUpdate",
    "AgentMemorySettingsView",
    "AgentMemorySourceView",
    "AgentMemoryStatusCommand",
    "AgentMemoryUpdate",
    "AgentMemoryView",
    "ConversationMemoryControlsUpdate",
    "ConversationMemoryControlsView",
]
