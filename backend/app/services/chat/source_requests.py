"""Closed read-only source requests for one admitted Conversation Turn.

These models are a small runtime protocol between the Debrief Chat retrieval
planner and the shared source-acquisition adapter.  They are not a Source
Registry, universal CareerState DTO/aggregate, or persistent owner; they own no
facts and cannot write product state.  Each request routes directly to named
existing owners with a hard result bound.
"""

from __future__ import annotations

import re
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class HistorySourceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["history"] = "history"
    query: str = Field(min_length=2, max_length=200)
    scope: Literal["current_conversation", "all_conversations"] = "all_conversations"
    limit: int = Field(default=3, ge=1, le=5)

    @field_validator("query")
    @classmethod
    def normalize_query(cls, value: str) -> str:
        return " ".join(value.split())


class ObservationSourceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["observations"] = "observations"
    query: str = Field(min_length=1, max_length=200)
    statuses: list[
        Literal[
            "unreviewed",
            "pending_confirmation",
            "applied",
            "dismissed",
            "retracted",
        ]
    ] = Field(default_factory=list, max_length=5)
    limit: int = Field(default=3, ge=1, le=5)

    @field_validator("query")
    @classmethod
    def normalize_query(cls, value: str) -> str:
        return " ".join(value.split())

    @model_validator(mode="after")
    def unique_statuses(self) -> "ObservationSourceRequest":
        self.statuses = list(dict.fromkeys(self.statuses))
        return self


class ArtifactSourceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["artifacts"] = "artifacts"
    query: str = Field(min_length=1, max_length=200)
    artifact_kinds: list[str] = Field(default_factory=list, max_length=8)
    # Exact identities come only from the admitted typed-reference payload.
    # The Chat planner schema never advertises this field.
    artifact_ids: list[str] = Field(default_factory=list, max_length=16)
    include_archived: bool = False
    limit: int = Field(default=3, ge=1, le=5)

    @field_validator("query")
    @classmethod
    def normalize_query(cls, value: str) -> str:
        return " ".join(value.split())

    @field_validator("artifact_kinds", mode="before")
    @classmethod
    def normalize_kinds(cls, value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        return list(
            dict.fromkeys(
                str(item).strip().casefold()[:64]
                for item in value
                if str(item or "").strip()
            )
        )

    @field_validator("artifact_ids", mode="before")
    @classmethod
    def normalize_artifact_ids(cls, value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        return list(
            dict.fromkeys(
                str(item).strip()[:128] for item in value if str(item or "").strip()
            )
        )


CareerDomainSection = Literal[
    "career_profile",
    "job_opportunities",
    "next_actions",
    "ability_signals",
    "interviews",
    "offers",
]

CareerDomainReferenceKind = Literal[
    "career_profile",
    "career_profile_direction",
    "job_opportunity",
    "next_action",
    "interview_record",
]


class CareerDomainSourceRequest(BaseModel):
    """Bounded reads across explicitly named career-domain owners.

    This runtime routing request is neither a stored ``CareerState`` owner nor
    a universal context object. Every selected section is read from its
    existing authoritative service/table and projected only for the Turn.
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["career_domains"] = "career_domains"
    query: str = Field(min_length=1, max_length=200)
    sections: list[CareerDomainSection] = Field(min_length=1, max_length=6)
    # Exact reference identity is deterministic admitted input, not Planner
    # output. ``reference_kind`` and ``object_ids`` remain a closed routing
    # contract to one existing owner.
    reference_kind: CareerDomainReferenceKind | None = None
    object_ids: list[str] = Field(default_factory=list, max_length=16)
    include_process_events: bool = False
    include_inactive: bool = False
    limit: int = Field(default=5, ge=1, le=10)

    @field_validator("query")
    @classmethod
    def normalize_query(cls, value: str) -> str:
        return " ".join(value.split())

    @field_validator("object_ids", mode="before")
    @classmethod
    def normalize_object_ids(cls, value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        return list(
            dict.fromkeys(
                str(item).strip()[:128] for item in value if str(item or "").strip()
            )
        )

    @model_validator(mode="after")
    def unique_sections(self) -> "CareerDomainSourceRequest":
        self.sections = list(dict.fromkeys(self.sections))
        self.object_ids = list(dict.fromkeys(self.object_ids))
        if bool(self.reference_kind) != bool(self.object_ids):
            raise ValueError("reference_kind and object_ids must be provided together")
        return self


ReadOnlySourceRequest = Annotated[
    HistorySourceRequest
    | ObservationSourceRequest
    | ArtifactSourceRequest
    | CareerDomainSourceRequest,
    Field(discriminator="kind"),
]


_URL_RE = re.compile(
    r"https?://[^\s<>\"'，。；：！？（）【】《》「」『』]+",
    re.IGNORECASE,
)
_URL_TRAILING_PUNCTUATION = ".,;:!)]}>，。；：！？）】》」』"
MAX_EXPLICIT_URLS = 3


def extract_explicit_urls(text: str) -> tuple[str, ...]:
    """Extract the exact public HTTP(S) identities in current user text.

    URL selection is deterministic: an LLM planner cannot omit or invent an
    explicitly supplied URL.  Network safety is still enforced later by the
    same SSRF-safe URL reader used by the Agent Tool.
    """

    values: list[str] = []
    for match in _URL_RE.finditer(str(text or "")):
        candidate = match.group(0).rstrip(_URL_TRAILING_PUNCTUATION)
        parsed = urlsplit(candidate)
        if parsed.scheme.casefold() not in {"http", "https"} or not parsed.hostname:
            continue
        if candidate not in values:
            values.append(candidate)
        # Do not truncate here. Acquisition admits the first bounded set and
        # emits a typed explicit failure when additional URLs exist, so no
        # user-supplied source can disappear silently.
    return tuple(values)


_REFERENCE_SECTION: dict[str, CareerDomainSection] = {
    "career_profile": "career_profile",
    "career_profile_direction": "career_profile",
    "job_opportunity": "job_opportunities",
    "next_action": "next_actions",
    "interview_record": "interviews",
}


def explicit_source_requests_from_object_references(
    references: object,
) -> list[ReadOnlySourceRequest]:
    """Convert admitted ``{kind, object_id}`` refs into exact owner reads.

    This deterministic adapter is not a Planner or Registry. Unknown shapes
    and kinds are ignored because Conversation admission owns their rejection;
    every admitted closed kind maps directly to its existing owner.
    """

    if not isinstance(references, (list, tuple)):
        return []
    requests: list[ReadOnlySourceRequest] = []
    seen: set[tuple[str, str]] = set()
    for raw in references:
        if isinstance(raw, dict):
            kind = str(raw.get("kind") or "").strip()
            object_id = str(raw.get("object_id") or "").strip()
        else:
            kind = str(getattr(raw, "kind", "") or "").strip()
            object_id = str(getattr(raw, "object_id", "") or "").strip()
        key = (kind, object_id)
        if not object_id or key in seen:
            continue
        seen.add(key)
        if kind == "artifact":
            requests.append(
                ArtifactSourceRequest(
                    query=object_id,
                    artifact_ids=[object_id],
                    include_archived=True,
                    limit=1,
                )
            )
            continue
        section = _REFERENCE_SECTION.get(kind)
        if section is not None:
            requests.append(
                CareerDomainSourceRequest(
                    query=object_id,
                    sections=[section],
                    reference_kind=kind,
                    object_ids=[object_id],
                    include_process_events=(kind == "job_opportunity"),
                    include_inactive=True,
                    limit=1,
                )
            )
    return requests


def strip_planner_identities(
    requests: list[ReadOnlySourceRequest],
) -> list[ReadOnlySourceRequest]:
    """Remove identity fields that are never authoritative Planner output."""

    sanitized: list[ReadOnlySourceRequest] = []
    for request in requests:
        if isinstance(request, ArtifactSourceRequest):
            sanitized.append(request.model_copy(update={"artifact_ids": []}))
        elif isinstance(request, CareerDomainSourceRequest):
            sanitized.append(
                request.model_copy(
                    update={
                        "reference_kind": None,
                        "object_ids": [],
                        "include_process_events": False,
                    }
                )
            )
        else:
            sanitized.append(request)
    return sanitized


_HISTORY_CUES = (
    "之前",
    "以前",
    "上次",
    "当时",
    "历史",
    "说过",
    "调用过",
    "返回过",
    "earlier",
    "previous",
    "last time",
    "history",
)
_OBSERVATION_CUES = (
    "gmail",
    "邮箱",
    "邮件",
    "确认信",
    "确认邮件",
    "observation",
)
_ARTIFACT_CUES = (
    "artifact",
    "简历",
    "求职信",
    "材料",
    "resume",
    "cover letter",
)
_CAREER_SECTIONS: tuple[tuple[tuple[str, ...], CareerDomainSection], ...] = (
    (("档案", "方向", "career profile"), "career_profile"),
    (("岗位", "机会", "申请进度", "job opportunity"), "job_opportunities"),
    (("下一步", "待办", "行动", "next action"), "next_actions"),
    (("能力信号", "能力", "ability signal"), "ability_signals"),
    (("面试记录", "面试", "interview"), "interviews"),
    (("offer", "录用", "报价"), "offers"),
)


def fallback_source_requests(text: str) -> list[ReadOnlySourceRequest]:
    """Conservative deterministic requests when the planner is unavailable."""

    query = " ".join(str(text or "").split())[:200]
    if not query:
        return []
    folded = query.casefold()
    requests: list[ReadOnlySourceRequest] = []
    if any(cue in folded for cue in _HISTORY_CUES):
        requests.append(HistorySourceRequest(query=query))
    if any(cue in folded for cue in _OBSERVATION_CUES):
        requests.append(ObservationSourceRequest(query=query))
    if any(cue in folded for cue in _ARTIFACT_CUES):
        requests.append(ArtifactSourceRequest(query=query))
    sections = [
        section
        for cues, section in _CAREER_SECTIONS
        if any(cue in folded for cue in cues)
    ]
    if sections:
        requests.append(
            CareerDomainSourceRequest(
                query=query, sections=list(dict.fromkeys(sections))
            )
        )
    return requests[:4]


__all__ = [
    "ArtifactSourceRequest",
    "CareerDomainSection",
    "CareerDomainSourceRequest",
    "CareerDomainReferenceKind",
    "HistorySourceRequest",
    "MAX_EXPLICIT_URLS",
    "ObservationSourceRequest",
    "ReadOnlySourceRequest",
    "extract_explicit_urls",
    "explicit_source_requests_from_object_references",
    "fallback_source_requests",
    "strip_planner_identities",
]
