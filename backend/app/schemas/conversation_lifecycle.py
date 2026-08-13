"""Typed impact preview and result DTOs for destructive Conversation deletion."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ConversationDeletionImpact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: str
    conversation_type: str
    title: str
    active_turn_id: str | None = None
    active_turn_status: str | None = None
    pending_submission_count: int = 0
    message_count: int = 0
    local_attachment_count: int = 0
    unpromoted_file_count: int = 0
    preserved_debrief_source_count: int = 0
    unresolved_external_call_count: int = 0
    completed_external_action_count: int = 0
    confirmation_token: str
    disclosures: list[str] = Field(default_factory=list)


class ConversationDeleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmation_token: str = Field(min_length=64, max_length=64)
    confirm_conversation_id: str = Field(min_length=1, max_length=128)


class ConversationDeleteResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["deleted"] = "deleted"
    conversation_id: str
    cancelled_turn_id: str | None = None
    deleted_pending_submissions: int = 0
    deleted_attachment_refs: int = 0
    deleted_file_assets: int = 0
    preserved_debrief_sources: int = 0
    receipt_tombstones: int = 0


__all__ = [
    "ConversationDeleteRequest",
    "ConversationDeleteResult",
    "ConversationDeletionImpact",
]
