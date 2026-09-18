"""Typed, auditable context snapshots compiled for one execution boundary."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue


ContextRole = Literal[
    "current_user_input",
    "canonical_state",
    "interaction_decision",
    "source_evidence",
    "observation_candidate",
    "learned_memory",
    "conversation_history",
    "working_ui_context",
    "runtime_controls",
]
ContextAuthority = Literal[
    "user_assertion",
    "canonical",
    "interaction_decision",
    "evidence",
    "candidate",
    "learned",
    "historical",
    "working",
    "runtime",
]


class ContextObjectReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str = Field(min_length=1, max_length=80)
    id: str = Field(min_length=1, max_length=256)
    version: int | None = Field(default=None, ge=1)


class ContextSourceReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str = Field(min_length=1, max_length=80)
    identity: str = Field(min_length=1, max_length=512)
    version: str | None = Field(default=None, max_length=128)
    snapshot_id: str | None = Field(default=None, max_length=128)


class ContextBudget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_sections: int = Field(default=8, ge=1, le=32)
    max_source_references: int = Field(default=30, ge=1, le=100)
    max_opportunity_options: int = Field(default=20, ge=1, le=100)


class ContextPolicyScope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actor_kind: Literal["user", "agent", "automation"]
    allowed_operations: list[str] = Field(max_length=20)
    canonical_write_requires_user_decision: bool = True
    execution_time_policy_recheck: bool = True
    user_scope_enforced: bool = True


class ContextSourceManifestItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: ContextSourceReference
    object_owner: str
    producer: str
    captured_or_observed_at: datetime | None = None
    authority: Literal["user_assertion", "evidence", "candidate", "canonical"]
    content_hash: str = Field(min_length=64, max_length=64)
    sensitivity: Literal["career_private"] = "career_private"
    redaction: Literal["reference_only", "bounded_fields"] = "reference_only"
    invalidated: bool = False


class ContextPackageSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: ContextRole
    authority: ContextAuthority
    content_or_reference: dict[str, JsonValue]
    source_references: list[ContextSourceReference] = Field(default_factory=list)
    object_versions: list[ContextObjectReference] = Field(default_factory=list)
    observed_at: datetime | None = None
    valid_at: datetime | None = None
    expires_at: datetime | None = None
    sensitivity: Literal["career_private"] = "career_private"
    truncation_state: Literal["complete", "bounded", "reference_only"]


class ContextPackage(BaseModel):
    """Execution snapshot; never the owner of canonical product facts."""

    model_config = ConfigDict(extra="forbid")

    package_id: str = Field(min_length=1, max_length=80)
    schema_version: Literal[1] = 1
    compiled_at: datetime
    user_scope: str
    conversation_id: str
    turn_id: str
    task_id: str | None = None
    purpose: str = Field(min_length=1, max_length=160)
    object_scope: list[ContextObjectReference]
    policy_scope: ContextPolicyScope
    budget: ContextBudget
    sections: list[ContextPackageSection] = Field(min_length=1, max_length=32)
    source_manifest: list[ContextSourceManifestItem] = Field(max_length=100)
    compiler_version: str = Field(min_length=1, max_length=80)


__all__ = [
    "ContextBudget",
    "ContextObjectReference",
    "ContextPackage",
    "ContextPackageSection",
    "ContextPolicyScope",
    "ContextSourceManifestItem",
    "ContextSourceReference",
]
