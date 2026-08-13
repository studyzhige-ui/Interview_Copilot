"""Public safe views and concrete read contracts for the Gmail slice."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


GmailAccountStatus = Literal["active", "invalid", "revoked"]


class GmailIntegrationAccountView(BaseModel):
    """Safe account view: the credential handle is deliberately absent."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    provider: Literal["gmail"] = "gmail"
    account_hint: str
    scopes: list[str] = Field(validation_alias="scopes_json")
    status: GmailAccountStatus
    last_checked_at: datetime | None
    last_error_code: str | None
    history_cursor_updated_at: datetime | None
    last_observation_sync_at: datetime | None
    last_observation_sync_error_code: str | None
    revoked_at: datetime | None


class GmailIntegrationStatusView(BaseModel):
    """Connection projection that can honestly represent no bound grant."""

    model_config = ConfigDict(extra="forbid")

    provider: Literal["gmail"] = "gmail"
    adapter_available: bool
    connection_required: bool
    account: GmailIntegrationAccountView | None = None


class GmailOAuthAuthorizationView(BaseModel):
    """Safe browser handoff; no OAuth code, token, or credential handle."""

    model_config = ConfigDict(extra="forbid")

    provider: Literal["gmail"] = "gmail"
    authorization_url: str
    expires_in_seconds: int = Field(ge=60, le=900)


class GmailSearchMessagesArgs(BaseModel):
    """A bounded Gmail-search request, not a whole-mailbox synchronization."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(
        min_length=1,
        max_length=500,
        description=(
            "A narrow Gmail search query for messages relevant to the user's "
            "current request. Do not scan the entire mailbox."
        ),
    )
    limit: int = Field(default=10, ge=1, le=10)


class GmailMessageSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message_id: str = Field(min_length=1, max_length=256)
    thread_id: str = Field(min_length=1, max_length=256)
    received_at: AwareDatetime | None = None
    from_hint: str = Field(default="", max_length=320)
    subject: str = Field(default="", max_length=500)
    snippet: str = Field(default="", max_length=500)


class GmailSearchMessagesResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["gmail"] = "gmail"
    account_id: str
    account_hint: str
    query: str
    messages: list[GmailMessageSummary]
    external_content_notice: str


__all__ = [
    "GmailAccountStatus",
    "GmailIntegrationAccountView",
    "GmailIntegrationStatusView",
    "GmailOAuthAuthorizationView",
    "GmailMessageSummary",
    "GmailSearchMessagesArgs",
    "GmailSearchMessagesResult",
]
