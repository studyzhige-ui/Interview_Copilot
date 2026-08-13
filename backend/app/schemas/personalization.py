"""Typed commands and projections for explicit personalization guidance."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, PositiveInt, field_validator


class CopilotPreferenceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=0)
    instructions: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("instructions")
    @classmethod
    def normalize_instructions(cls, value: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for raw in value:
            instruction = raw.strip()
            if not instruction:
                raise ValueError("instructions cannot contain blank values")
            if len(instruction) > 1_000:
                raise ValueError("each instruction must be at most 1000 characters")
            if instruction not in seen:
                seen.add(instruction)
                result.append(instruction)
        return result


class CopilotPreferenceView(BaseModel):
    id: str | None
    instructions: list[str]
    version: int
    updated_at: datetime | None


class ScopedGuidanceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=0)
    guidance: str | None = Field(default=None, max_length=4_000)
    source_message_id: PositiveInt | None = None

    @field_validator("guidance")
    @classmethod
    def normalize_guidance(cls, value: str | None) -> str | None:
        if value is None:
            return None
        result = value.strip()
        return result or None


class ScopedGuidanceView(BaseModel):
    owner_id: str
    guidance: str | None
    source_message_id: int | None
    version: int
    updated_at: datetime | None


__all__ = [
    "CopilotPreferenceUpdate",
    "CopilotPreferenceView",
    "ScopedGuidanceUpdate",
    "ScopedGuidanceView",
]
