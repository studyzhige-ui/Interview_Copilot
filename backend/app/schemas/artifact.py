"""Typed commands and read snapshots for the Artifact domain."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, PositiveInt, model_validator


class ArtifactProvenanceInput(BaseModel):
    """Direct pointers to existing owners; this is not a Source registry."""

    source_message_id: PositiveInt | None = None
    source_turn_id: str | None = Field(default=None, min_length=1, max_length=128)
    source_owner_type: str | None = Field(default=None, min_length=1, max_length=64)
    source_owner_id: str | None = Field(default=None, min_length=1, max_length=128)

    @model_validator(mode="after")
    def owner_identity_is_paired(self):
        if (self.source_owner_type is None) != (self.source_owner_id is None):
            raise ValueError("source_owner_type and source_owner_id must be paired")
        return self


class ArtifactWriteInput(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    content_text: str | None = None
    content_format: str = Field(default="markdown", min_length=1, max_length=64)
    file_asset_id: str | None = Field(default=None, min_length=1, max_length=128)
    file_asset_version: str | None = Field(default=None, min_length=1, max_length=96)
    provenance: ArtifactProvenanceInput = Field(default_factory=ArtifactProvenanceInput)

    @model_validator(mode="after")
    def has_real_content(self):
        if not (self.content_text or "").strip() and self.file_asset_id is None:
            raise ValueError("an Artifact version requires text or a FileAsset")
        if self.file_asset_version is not None and self.file_asset_id is None:
            raise ValueError("file_asset_version requires file_asset_id")
        return self


class ArtifactVersionView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    artifact_id: str
    version_no: int
    title: str
    content_text: str | None
    content_format: str
    file_asset_id: str | None
    file_asset_version: str | None
    origin_kind: Literal["explicit_save", "message_promotion", "flow_delivery", "edit"]
    source_message_id: int | None
    source_turn_id: str | None
    source_owner_type: str | None
    source_owner_id: str | None
    created_at: datetime


class ArtifactView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    kind: str
    archived_at: datetime | None
    current_version: ArtifactVersionView


class ArtifactSubmissionView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    job_opportunity_id: str
    artifact_id: str
    artifact_version_id: str
    basis: Literal["user_confirmation", "product_ui_confirmation", "external_receipt"]
    confirmation_message_id: int | None
    receipt_owner_type: str | None
    receipt_owner_id: str | None
    submitted_at: datetime


class ArtifactSubmissionDetailView(ArtifactSubmissionView):
    """A use assertion together with the immutable version it froze."""

    submitted_version: ArtifactVersionView


class ArtifactExplicitSaveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_key: str = Field(min_length=1, max_length=128)
    artifact_kind: str = Field(min_length=1, max_length=64)
    version: ArtifactWriteInput


class ArtifactMessagePromotionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_key: str = Field(min_length=1, max_length=128)
    artifact_kind: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=240)
    source_message_id: PositiveInt
    source_turn_id: str | None = Field(default=None, min_length=1, max_length=128)


class ArtifactEditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_key: str = Field(min_length=1, max_length=128)
    version: ArtifactWriteInput


class ArtifactRelatedRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_opportunity_id: str = Field(min_length=1, max_length=128)


class ArtifactRelatedView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    artifact_id: str
    job_opportunity_id: str
    created_at: datetime


class ArtifactSubmittedRequest(BaseModel):
    """Exact-version submission explicitly confirmed through one user channel.

    External receipt confirmation intentionally has no public DTO until a
    concrete Connector defines a real receipt/read-back contract.
    """

    model_config = ConfigDict(extra="forbid")

    operation_key: str = Field(min_length=1, max_length=128)
    artifact_version_id: str = Field(min_length=1, max_length=128)
    job_opportunity_id: str = Field(min_length=1, max_length=128)
    confirmation_message_id: PositiveInt | None = None
    ui_confirmation: Literal["product_ui"] | None = None

    @model_validator(mode="after")
    def require_exactly_one_confirmation(self) -> "ArtifactSubmittedRequest":
        if (self.confirmation_message_id is None) == (self.ui_confirmation is None):
            raise ValueError(
                "exactly one of confirmation_message_id or ui_confirmation is required"
            )
        return self


__all__ = [
    "ArtifactEditRequest",
    "ArtifactExplicitSaveRequest",
    "ArtifactMessagePromotionRequest",
    "ArtifactProvenanceInput",
    "ArtifactRelatedRequest",
    "ArtifactRelatedView",
    "ArtifactSubmittedRequest",
    "ArtifactSubmissionView",
    "ArtifactSubmissionDetailView",
    "ArtifactVersionView",
    "ArtifactView",
    "ArtifactWriteInput",
]
