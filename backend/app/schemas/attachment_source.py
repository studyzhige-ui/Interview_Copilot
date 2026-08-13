"""Public DTOs for attachment and Debrief Project source lifecycle."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.artifact import ArtifactView


class AttachmentParseQualityView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parser_id: str | None = None
    quality_score: float | None = None
    ocr_used: bool = False
    warnings: list[str] = Field(default_factory=list)


class AttachmentProjectionCoverageView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk_count: int = 0
    parsed_char_count: int = 0
    page_count: int | None = None
    page_start: int | None = None
    page_end: int | None = None
    full_text_projection_available: bool = False
    visual_layout_reviewed: bool = False


class AttachmentSourceView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    source_id: str
    source_kind: Literal[
        "draft",
        "conversation_attachment",
        "debrief_project_source",
    ]
    scope_kind: Literal[
        "composer_draft",
        "pending_submission",
        "conversation",
        "debrief_project",
    ]
    scope_id: str
    status: Literal["processing", "ready", "failed"]
    file_asset_id: str | None = None
    file_asset_version: str | None = None
    document_id: str | None = None
    title: str
    error_message: str | None = None
    can_retry: bool = False
    parse_quality: AttachmentParseQualityView
    coverage: AttachmentProjectionCoverageView


class AttachmentRetryView(BaseModel):
    source: AttachmentSourceView
    dispatched: bool


class DebriefSourcePromotionView(BaseModel):
    source: AttachmentSourceView


class AttachmentArtifactPromotionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_key: str = Field(min_length=1, max_length=128)
    artifact_kind: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=240)


class AttachmentArtifactPromotionView(BaseModel):
    source_id: str
    file_asset_id: str
    file_asset_version: str
    artifact: ArtifactView
    resume_parse_dispatched: bool = False


class ConversationAttachmentRemovalView(BaseModel):
    source_id: str
    status: Literal["removed"] = "removed"
    resumed_turn: bool


__all__ = [
    "AttachmentArtifactPromotionRequest",
    "AttachmentArtifactPromotionView",
    "AttachmentRetryView",
    "AttachmentParseQualityView",
    "AttachmentProjectionCoverageView",
    "AttachmentSourceView",
    "ConversationAttachmentRemovalView",
    "DebriefSourcePromotionView",
]
