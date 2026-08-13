"""Typed JD snapshot commands with source-specific trust boundaries."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class JobDescriptionSnapshotFromToolResult(BaseModel):
    """Create from an exact completed search_jobs detail/read_url ToolResult."""

    model_config = ConfigDict(extra="forbid")

    source_kind: Literal["tool_result"] = "tool_result"
    source_identity: str = Field(
        min_length=1,
        max_length=128,
        description="AgentToolCall.call_id within tool_session_id",
    )
    tool_session_id: str = Field(min_length=1, max_length=128)
    original_url: str = Field(min_length=1, max_length=4_000)
    observed_at: AwareDatetime
    idempotency_key: str = Field(min_length=1, max_length=200)


class JobDescriptionSnapshotFromProductUI(BaseModel):
    """Create from explicit typed first-party product UI input."""

    model_config = ConfigDict(extra="forbid")

    source_kind: Literal["typed_product_ui"] = "typed_product_ui"
    source_identity: str = Field(min_length=1, max_length=256)
    source_version: str = Field(min_length=1, max_length=128)
    original_url: str = Field(min_length=1, max_length=4_000)
    observed_at: AwareDatetime
    provider: str = Field(min_length=1, max_length=80)
    canonical_content: str = Field(min_length=1, max_length=120_000)
    idempotency_key: str = Field(min_length=1, max_length=200)


JobDescriptionSnapshotCreate = Annotated[
    JobDescriptionSnapshotFromToolResult | JobDescriptionSnapshotFromProductUI,
    Field(discriminator="source_kind"),
]


class JobDescriptionSnapshotView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    job_opportunity_id: str
    version: int
    original_url: str
    normalized_url: str
    observed_at: datetime
    provider: str
    canonical_content: str
    content_checksum: str
    source_kind: Literal["tool_result", "typed_product_ui"]
    source_identity: str
    source_version: str
    created_at: datetime


__all__ = [
    "JobDescriptionSnapshotCreate",
    "JobDescriptionSnapshotFromProductUI",
    "JobDescriptionSnapshotFromToolResult",
    "JobDescriptionSnapshotView",
]
