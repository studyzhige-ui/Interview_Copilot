"""Pure values and invariants for a confirmed interview invitation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


REQUIRED_INTERVIEW_INVITATION_FACT_FIELDS = (
    "company_name",
    "job_title",
    "scheduled_start_at",
    "original_time_text",
    "source_timezone",
)
INTERVIEW_INVITATION_FACT_FIELDS = (
    *REQUIRED_INTERVIEW_INVITATION_FACT_FIELDS,
    "scheduled_end_at",
    "stage_label",
    "location",
    "meeting_url",
    "contact_name",
    "contact_email",
)


class InterviewInvitationInvariantError(ValueError):
    """A proposed invitation cannot become canonical state."""


def _required_text(value: str, field: str, maximum: int) -> str:
    normalized = value.strip()
    if not normalized:
        raise InterviewInvitationInvariantError(f"{field} is required")
    if len(normalized) > maximum:
        raise InterviewInvitationInvariantError(
            f"{field} exceeds the {maximum}-character limit"
        )
    return normalized


def _optional_text(value: str | None, maximum: int) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if len(normalized) > maximum:
        raise InterviewInvitationInvariantError(
            f"value exceeds the {maximum}-character limit"
        )
    return normalized


def _aware(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise InterviewInvitationInvariantError(f"{field} must include a timezone")
    return value


@dataclass(frozen=True, slots=True)
class InvitationSourceReference:
    kind: str
    identity: str
    version: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", _required_text(self.kind, "source kind", 32))
        object.__setattr__(
            self,
            "identity",
            _required_text(self.identity, "source identity", 256),
        )
        object.__setattr__(self, "version", _optional_text(self.version, 128))


@dataclass(frozen=True, slots=True)
class InvitationEvidence:
    field_name: str
    source: InvitationSourceReference
    value_hash: str

    def __post_init__(self) -> None:
        if self.field_name not in INTERVIEW_INVITATION_FACT_FIELDS:
            raise InterviewInvitationInvariantError(
                f"unsupported invitation fact field: {self.field_name}"
            )
        normalized_hash = self.value_hash.strip().lower()
        if len(normalized_hash) != 64 or any(
            character not in "0123456789abcdef" for character in normalized_hash
        ):
            raise InterviewInvitationInvariantError(
                "evidence value_hash must be a SHA-256 hex digest"
            )
        object.__setattr__(self, "value_hash", normalized_hash)


@dataclass(frozen=True, slots=True)
class InterviewInvitationFacts:
    company_name: str
    job_title: str
    scheduled_start_at: datetime
    original_time_text: str
    source_timezone: str
    scheduled_end_at: datetime | None = None
    stage_label: str | None = None
    location: str | None = None
    meeting_url: str | None = None
    contact_name: str | None = None
    contact_email: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "company_name", _required_text(self.company_name, "company_name", 200)
        )
        object.__setattr__(
            self, "job_title", _required_text(self.job_title, "job_title", 300)
        )
        object.__setattr__(
            self,
            "scheduled_start_at",
            _aware(self.scheduled_start_at, "scheduled_start_at"),
        )
        object.__setattr__(
            self,
            "original_time_text",
            _required_text(self.original_time_text, "original_time_text", 300),
        )
        object.__setattr__(
            self,
            "source_timezone",
            _required_text(self.source_timezone, "source_timezone", 80),
        )
        if self.scheduled_end_at is not None:
            scheduled_end = _aware(self.scheduled_end_at, "scheduled_end_at")
            if scheduled_end <= self.scheduled_start_at:
                raise InterviewInvitationInvariantError(
                    "scheduled_end_at must be after scheduled_start_at"
                )
            object.__setattr__(self, "scheduled_end_at", scheduled_end)
        object.__setattr__(self, "stage_label", _optional_text(self.stage_label, 200))
        object.__setattr__(self, "location", _optional_text(self.location, 500))
        object.__setattr__(self, "meeting_url", _optional_text(self.meeting_url, 4_000))
        object.__setattr__(self, "contact_name", _optional_text(self.contact_name, 200))
        object.__setattr__(
            self, "contact_email", _optional_text(self.contact_email, 320)
        )

    def fact_values(self) -> dict[str, object | None]:
        return {
            field: getattr(self, field) for field in INTERVIEW_INVITATION_FACT_FIELDS
        }
