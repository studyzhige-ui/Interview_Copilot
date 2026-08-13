"""Public DTOs for attachment and Debrief Project source lifecycle."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


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


class AttachmentRetryView(BaseModel):
    source: AttachmentSourceView
    dispatched: bool


class DebriefSourcePromotionView(BaseModel):
    source: AttachmentSourceView


class ConversationAttachmentRemovalView(BaseModel):
    source_id: str
    status: Literal["removed"] = "removed"
    resumed_turn: bool


__all__ = [
    "AttachmentRetryView",
    "AttachmentSourceView",
    "ConversationAttachmentRemovalView",
    "DebriefSourcePromotionView",
]
