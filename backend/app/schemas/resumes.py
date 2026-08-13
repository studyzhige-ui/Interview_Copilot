"""Pydantic schemas for the personal-resume HTTP endpoints."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ResumeCreateRequest(BaseModel):
    operation_key: str | None = Field(default=None, min_length=1, max_length=128)
    file_asset_id: str | None = None
    title: str | None = Field(default=None, max_length=200)
    raw_text_snapshot: str | None = None
    make_default: bool | None = None


class ResumeResponse(BaseModel):
    id: str
    artifact_id: str
    current_version_id: str
    title: str
    is_default: bool
    parse_status: str
    parse_error: str | None = None
    file_asset_id: str | None
    has_text: bool
    pending_profile_draft_id: str | None = None
    legacy_resume_id: str | None = None
    created_at: str
    updated_at: str


__all__ = ["ResumeCreateRequest", "ResumeResponse"]
