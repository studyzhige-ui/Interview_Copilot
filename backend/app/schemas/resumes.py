"""Pydantic schemas for the personal-resume HTTP endpoints."""
from __future__ import annotations

from pydantic import BaseModel, Field


class ResumeCreateRequest(BaseModel):
    file_asset_id: str | None = None
    title: str | None = Field(default=None, max_length=200)
    raw_text_snapshot: str | None = None
    make_default: bool | None = None


class ResumeResponse(BaseModel):
    id: str
    title: str
    is_default: bool
    parse_status: str
    file_asset_id: str | None
    has_text: bool
    created_at: str
    updated_at: str


__all__ = ["ResumeCreateRequest", "ResumeResponse"]
