"""Public DTOs and bounded read contracts for Canva and Notion plugins."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


ExternalPluginProvider = Literal["canva", "notion"]
ExternalPluginAccountStatus = Literal["active", "invalid", "revoked"]


class ExternalPluginAccountView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    provider: ExternalPluginProvider
    account_hint: str
    scopes: list[str] = Field(validation_alias="scopes_json")
    status: ExternalPluginAccountStatus
    last_checked_at: datetime | None
    last_error_code: str | None
    revoked_at: datetime | None


class ExternalPluginStatusView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: ExternalPluginProvider
    adapter_available: bool
    connection_required: bool
    account: ExternalPluginAccountView | None = None


class ExternalPluginOAuthAuthorizationView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: ExternalPluginProvider
    authorization_url: str
    expires_in_seconds: int = Field(ge=60, le=900)


class CanvaSearchDesignsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(default="", max_length=255)
    limit: int = Field(default=10, ge=1, le=20)


class NotionSearchPagesArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=200)
    limit: int = Field(default=10, ge=1, le=20)


__all__ = [
    "CanvaSearchDesignsArgs",
    "ExternalPluginAccountStatus",
    "ExternalPluginAccountView",
    "ExternalPluginOAuthAuthorizationView",
    "ExternalPluginProvider",
    "ExternalPluginStatusView",
    "NotionSearchPagesArgs",
]
