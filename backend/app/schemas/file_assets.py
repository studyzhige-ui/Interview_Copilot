"""Pydantic schemas for the unified file-asset upload API."""

from __future__ import annotations

from pydantic import BaseModel, Field


class UploadUrlRequest(BaseModel):
    purpose: str
    filename: str = Field(..., min_length=1, max_length=255)
    content_type: str | None = None
    size_bytes: int | None = Field(default=None, ge=0)


class UploadUrlResponse(BaseModel):
    file_asset_id: str
    upload_url: str
    storage_uri: str
    filename: str


class ConfirmResponse(BaseModel):
    file_asset_id: str
    upload_status: str
    validation_status: str
    validation_error: str | None = None


__all__ = ["UploadUrlRequest", "UploadUrlResponse", "ConfirmResponse"]
