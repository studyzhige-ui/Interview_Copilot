"""Explicit catalog of approved Career Application Operations.

This is intentionally independent from HTTP routes and the Agent Tool
registry.  Adapters use these definitions for discovery and Policy metadata;
the operation handler remains the single business execution boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class OperationEffect(StrEnum):
    READ = "read"
    SOURCE_WRITE = "source_write"
    CANDIDATE_WRITE = "candidate_write"
    CANONICAL_WRITE = "canonical_write"
    CLIENT_ACTION = "client_action"
    EXTERNAL_WRITE = "external_write"


@dataclass(frozen=True, slots=True)
class OperationDefinition:
    name: str
    schema_version: int
    effect: OperationEffect
    allowed_adapters: frozenset[str]
    verification: str
    domain_events: tuple[str, ...] = ()


class OperationCatalog:
    def __init__(self, definitions: tuple[OperationDefinition, ...]) -> None:
        by_key = {(item.name, item.schema_version): item for item in definitions}
        if len(by_key) != len(definitions):
            raise ValueError("Operation catalog contains duplicate name/version pairs")
        self._definitions = by_key

    def get(self, name: str, schema_version: int = 1) -> OperationDefinition:
        try:
            return self._definitions[(name, schema_version)]
        except KeyError as exc:
            raise KeyError(
                f"Unknown Career Operation: {name}@{schema_version}"
            ) from exc

    def list(self) -> tuple[OperationDefinition, ...]:
        return tuple(
            self._definitions[key]
            for key in sorted(self._definitions, key=lambda item: (item[0], item[1]))
        )


CAREER_OPERATION_CATALOG = OperationCatalog(
    (
        OperationDefinition(
            name="intake_interview_invitation_observation",
            schema_version=1,
            effect=OperationEffect.SOURCE_WRITE,
            allowed_adapters=frozenset({"automation", "integration", "fixture"}),
            verification="source_snapshot_read_back",
            domain_events=("interview_invitation_observation_received",),
        ),
        OperationDefinition(
            name="register_interview_invitation_candidate",
            schema_version=1,
            effect=OperationEffect.CANDIDATE_WRITE,
            allowed_adapters=frozenset({"agent", "automation", "integration"}),
            verification="candidate_read_back",
            domain_events=("interview_invitation_candidate_registered",),
        ),
        OperationDefinition(
            name="confirm_interview_invitation",
            schema_version=1,
            effect=OperationEffect.CANONICAL_WRITE,
            allowed_adapters=frozenset({"ui", "agent", "automation"}),
            verification="confirmed_invitation_local_read_back",
            domain_events=(
                "interview_invitation_confirmed",
                "job_opportunity_created",
                "interview_created",
                "interview_schedule_updated",
                "process_event_appended",
                "evidence_bound",
            ),
        ),
        OperationDefinition(
            name="reject_interview_invitation_candidate",
            schema_version=1,
            effect=OperationEffect.CANDIDATE_WRITE,
            allowed_adapters=frozenset({"ui", "agent", "automation"}),
            verification="candidate_rejection_read_back",
            domain_events=("interview_invitation_candidate_rejected",),
        ),
        OperationDefinition(
            name="get_interview_invitation_candidate",
            schema_version=1,
            effect=OperationEffect.READ,
            allowed_adapters=frozenset({"ui", "agent", "automation"}),
            verification="none",
        ),
        OperationDefinition(
            name="get_interview_invitation_handoff",
            schema_version=1,
            effect=OperationEffect.READ,
            allowed_adapters=frozenset({"ui", "agent"}),
            verification="none",
        ),
    )
)


__all__ = [
    "CAREER_OPERATION_CATALOG",
    "OperationCatalog",
    "OperationDefinition",
    "OperationEffect",
]
