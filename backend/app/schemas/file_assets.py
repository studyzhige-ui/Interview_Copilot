"""Pydantic schemas for the unified file-asset upload API."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class UploadUrlRequest(BaseModel):
    purpose: str
    filename: str = Field(..., min_length=1, max_length=255)
    content_type: str | None = None
    size_bytes: int | None = Field(default=None, ge=0)


class UploadUrlResponse(BaseModel):
    file_asset_id: str
    upload_url: str
    filename: str


class ConfirmResponse(BaseModel):
    file_asset_id: str
    upload_status: str
    validation_status: str
    validation_error: str | None = None


class FileAssetReferenceImpact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reference_type: str
    active_count: int = 0
    tombstone_count: int = 0
    effect: str


class FileAssetDeletionImpact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_asset_id: str
    filename: str
    purpose: str
    size_bytes: int | None = None
    reference_impacts: list[FileAssetReferenceImpact] = Field(default_factory=list)
    known_external_transmission_count: int = 0
    confirmation_token: str
    disclosures: list[str] = Field(default_factory=list)


class FileAssetPermanentDeleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmation_token: str = Field(min_length=64, max_length=64)
    confirm_file_asset_id: str = Field(min_length=1, max_length=128)
    confirm_filename: str = Field(min_length=1, max_length=512)


class FileAssetPermanentDeleteResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    file_asset_id: str
    removed_draft_scopes: int = 0
    removed_conversation_scopes: int = 0
    removed_debrief_scopes: int = 0
    deleted_projections: int = 0
    preserved_reference_tombstones: int = 0


__all__ = [
    "ConfirmResponse",
    "FileAssetDeletionImpact",
    "FileAssetPermanentDeleteRequest",
    "FileAssetPermanentDeleteResult",
    "FileAssetReferenceImpact",
    "UploadUrlRequest",
    "UploadUrlResponse",
]
