"""Versioned transport contracts for the VS-01 invitation operations."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Annotated, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    PositiveInt,
    field_validator,
    model_validator,
)

from app.career.domain.interview_invitation import (
    INTERVIEW_INVITATION_FACT_FIELDS,
    InterviewInvitationFacts as DomainInvitationFacts,
    InvitationEvidence as DomainInvitationEvidence,
    InvitationSourceReference as DomainSourceReference,
)
from app.schemas.context_package import ContextPackage


InvitationSourceKind = Literal["fixture", "manual", "user_message", "gmail"]
OperationActorKind = Literal[
    "user",
    "agent_on_behalf",
    "automation",
    "system_connector",
]


class InvitationSourceReference(BaseModel):
    model_config = ConfigDict(
        extra="forbid", json_schema_serialization_defaults_required=True
    )

    kind: InvitationSourceKind
    identity: str = Field(min_length=1, max_length=256)
    version: str | None = Field(default=None, max_length=128)
    snapshot_id: str | None = Field(default=None, max_length=36)

    def to_domain(self) -> DomainSourceReference:
        return DomainSourceReference(
            kind=self.kind,
            identity=self.identity,
            version=self.version,
        )


class InterviewInvitationFacts(BaseModel):
    model_config = ConfigDict(
        extra="forbid", json_schema_serialization_defaults_required=True
    )

    company_name: str = Field(min_length=1, max_length=200)
    job_title: str = Field(min_length=1, max_length=300)
    scheduled_start_at: AwareDatetime
    original_time_text: str = Field(min_length=1, max_length=300)
    source_timezone: str = Field(min_length=1, max_length=80)
    scheduled_end_at: AwareDatetime | None = None
    stage_label: str | None = Field(default=None, max_length=200)
    location: str | None = Field(default=None, max_length=500)
    meeting_url: str | None = Field(default=None, max_length=4_000)
    contact_name: str | None = Field(default=None, max_length=200)
    contact_email: str | None = Field(default=None, max_length=320)

    @model_validator(mode="after")
    def validate_schedule(self) -> "InterviewInvitationFacts":
        self.to_domain()
        return self

    def to_domain(self) -> DomainInvitationFacts:
        return DomainInvitationFacts(**self.model_dump())


class InterviewInvitationCandidateFacts(BaseModel):
    """Partial facts are valid only while the candidate is non-canonical."""

    model_config = ConfigDict(
        extra="forbid", json_schema_serialization_defaults_required=True
    )

    company_name: str | None = Field(default=None, max_length=200)
    job_title: str | None = Field(default=None, max_length=300)
    scheduled_start_at: AwareDatetime | None = None
    original_time_text: str | None = Field(default=None, max_length=300)
    source_timezone: str | None = Field(default=None, max_length=80)
    scheduled_end_at: AwareDatetime | None = None
    stage_label: str | None = Field(default=None, max_length=200)
    location: str | None = Field(default=None, max_length=500)
    meeting_url: str | None = Field(default=None, max_length=4_000)
    contact_name: str | None = Field(default=None, max_length=200)
    contact_email: str | None = Field(default=None, max_length=320)

    @model_validator(mode="after")
    def validate_partial_schedule(self) -> "InterviewInvitationCandidateFacts":
        if (
            self.scheduled_start_at is not None
            and self.scheduled_end_at is not None
            and self.scheduled_end_at <= self.scheduled_start_at
        ):
            raise ValueError("scheduled_end_at must be after scheduled_start_at")
        return self


class InvitationFieldEvidence(BaseModel):
    model_config = ConfigDict(
        extra="forbid", json_schema_serialization_defaults_required=True
    )

    field_name: str = Field(min_length=1, max_length=80)
    source: InvitationSourceReference
    value_hash: str = Field(min_length=64, max_length=64)

    @field_validator("field_name")
    @classmethod
    def validate_field_name(cls, value: str) -> str:
        if value not in INTERVIEW_INVITATION_FACT_FIELDS:
            raise ValueError(f"unsupported invitation fact field: {value}")
        return value

    def to_domain(self) -> DomainInvitationEvidence:
        return DomainInvitationEvidence(
            field_name=self.field_name,
            source=self.source.to_domain(),
            value_hash=self.value_hash,
        )


class IntakeInterviewInvitationObservation(BaseModel):
    model_config = ConfigDict(
        extra="forbid", json_schema_serialization_defaults_required=True
    )

    idempotency_key: str = Field(min_length=1, max_length=200)
    actor_kind: Literal["automation", "system_connector"]
    source_kind: Literal["fixture", "manual", "gmail"]
    source_identity: str = Field(min_length=1, max_length=256)
    source_version: str = Field(min_length=1, max_length=128)
    observed_at: AwareDatetime
    payload: dict[str, JsonValue]
    content_sha256: str | None = Field(default=None, min_length=64, max_length=64)


class InvitationObservationView(BaseModel):
    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: str
    source_snapshot_id: str
    status: Literal[
        "received",
        "candidate_registered",
        "pending_confirmation",
        "confirmed",
        "rejected",
        "retracted",
    ]
    version: PositiveInt
    created_at: datetime
    updated_at: datetime


class IntakeInterviewInvitationResult(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    operation_id: str
    verification_id: str
    source_snapshot_id: str
    observation: InvitationObservationView
    deduplicated: bool
    replayed: bool = False


class FixtureInterviewInvitationInput(BaseModel):
    """Deterministic first-slice ingress; never represents a live provider."""

    model_config = ConfigDict(
        extra="forbid", json_schema_serialization_defaults_required=True
    )

    idempotency_key: str = Field(min_length=1, max_length=160)
    source_identity: str = Field(min_length=1, max_length=256)
    source_version: str = Field(min_length=1, max_length=128)
    observed_at: AwareDatetime
    raw_payload: dict[str, JsonValue]
    extracted_facts: InterviewInvitationCandidateFacts
    missing_fields: list[str] = Field(default_factory=list, max_length=20)
    conflicts: list[str] = Field(default_factory=list, max_length=20)
    confidence: float | None = Field(default=None, ge=0, le=1)
    extractor_version: str = Field(default="fixture.v1", min_length=1, max_length=128)


class FixtureInterviewInvitationResult(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    source_snapshot_id: str
    observation: ObjectReference
    candidate: ObjectReference
    conversation_id: str | None = None
    turn_id: str | None = None
    interaction: ObjectReference | None = None
    status: Literal[
        "needs_clarification",
        "pending_confirmation",
        "confirmed",
        "rejected",
        "superseded",
    ]
    deduplicated: bool = False
    replayed: bool = False


class RegisterInterviewInvitationCandidate(BaseModel):
    model_config = ConfigDict(
        extra="forbid", json_schema_serialization_defaults_required=True
    )

    idempotency_key: str = Field(min_length=1, max_length=200)
    actor_kind: Literal["agent_on_behalf", "automation", "system_connector"]
    observation_id: str | None = Field(default=None, max_length=36)
    expected_observation_version: PositiveInt | None = None
    source_kind: Literal["observation", "user_message"]
    source_identity: str = Field(min_length=1, max_length=256)
    source_version: str = Field(min_length=1, max_length=128)
    facts: InterviewInvitationCandidateFacts
    field_provenance: list[InvitationFieldEvidence] = Field(max_length=30)
    missing_fields: list[str] = Field(default_factory=list, max_length=20)
    conflicts: list[str] = Field(default_factory=list, max_length=20)
    confidence: float | None = Field(default=None, ge=0, le=1)
    extractor_version: str = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def validate_observation_version(self) -> "RegisterInterviewInvitationCandidate":
        if (self.observation_id is None) != (self.expected_observation_version is None):
            raise ValueError(
                "observation_id and expected_observation_version must be provided together"
            )
        facts = self.facts.model_dump(mode="json")
        evidence_fields: set[str] = set()
        for item in self.field_provenance:
            item.to_domain()
            if facts[item.field_name] is None:
                raise ValueError(
                    f"field_provenance references missing {item.field_name}"
                )
            expected_hash = hashlib.sha256(
                json.dumps(
                    facts[item.field_name],
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            if item.value_hash.lower() != expected_hash:
                raise ValueError(
                    f"field_provenance hash does not match {item.field_name}"
                )
            evidence_fields.add(item.field_name)
        present_fields = {field for field, value in facts.items() if value is not None}
        if present_fields - evidence_fields:
            raise ValueError(
                "every present candidate fact requires field_provenance: "
                f"{sorted(present_fields - evidence_fields)}"
            )
        return self

    @field_validator("missing_fields")
    @classmethod
    def validate_missing_fields(cls, value: list[str]) -> list[str]:
        unsupported = set(value) - set(INTERVIEW_INVITATION_FACT_FIELDS)
        if unsupported:
            raise ValueError(f"unsupported missing fields: {sorted(unsupported)}")
        if len(value) != len(set(value)):
            raise ValueError("missing_fields must not contain duplicates")
        return value


class InterviewInvitationCandidateView(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
        json_schema_serialization_defaults_required=True,
    )

    id: str
    observation_id: str | None
    source_kind: str
    source_identity: str
    source_version: str
    status: Literal[
        "needs_clarification",
        "pending_confirmation",
        "confirmed",
        "rejected",
        "superseded",
    ]
    version: PositiveInt
    facts: dict[str, JsonValue] = Field(validation_alias="facts_json")
    field_provenance: list[dict[str, JsonValue]] = Field(
        validation_alias="field_provenance_json"
    )
    missing_fields: list[str] = Field(validation_alias="missing_fields_json")
    conflicts: list[str] = Field(validation_alias="conflicts_json")
    confidence: float | None
    extractor_version: str
    resolved_by_interaction_id: str | None
    confirmed_operation_id: str | None
    resolution_note: str | None
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None


class ObjectReference(BaseModel):
    model_config = ConfigDict(
        extra="forbid", json_schema_serialization_defaults_required=True
    )

    kind: str
    id: str
    version: int | None = None


class OpportunityMatchOption(BaseModel):
    """One owned canonical opportunity the user may explicitly select."""

    model_config = ConfigDict(
        extra="forbid", json_schema_serialization_defaults_required=True
    )

    opportunity_id: str = Field(min_length=1, max_length=35)
    expected_version: PositiveInt
    company_name: str = Field(min_length=1, max_length=200)
    job_title: str = Field(min_length=1, max_length=300)
    current_step: str = Field(min_length=1, max_length=200)


class FactConfirmationRequest(BaseModel):
    """Durable ``fact_confirmation@1`` request shown by any experience surface."""

    model_config = ConfigDict(
        extra="forbid", json_schema_serialization_defaults_required=True
    )

    protocol: Literal["interview_invitation.fact_confirmation.v1"] = (
        "interview_invitation.fact_confirmation.v1"
    )
    candidate_reference: ObjectReference
    expected_candidate_version: PositiveInt
    invitation_facts: InterviewInvitationCandidateFacts
    field_provenance: list[InvitationFieldEvidence] = Field(max_length=30)
    missing_or_uncertain_fields: list[str] = Field(default_factory=list, max_length=20)
    conflicts: list[str] = Field(default_factory=list, max_length=20)
    source_and_evidence_references: list[InvitationSourceReference] = Field(
        max_length=30
    )
    opportunity_match_options: list[OpportunityMatchOption] = Field(
        default_factory=list,
        max_length=20,
    )
    context_package: ContextPackage
    allowed_decisions: list[Literal["confirm", "correct_and_confirm", "reject"]] = (
        Field(
            default_factory=lambda: ["confirm", "correct_and_confirm", "reject"],
            min_length=3,
            max_length=3,
        )
    )

    @model_validator(mode="after")
    def validate_contract(self) -> "FactConfirmationRequest":
        if self.candidate_reference.kind != "interview_invitation_candidate":
            raise ValueError(
                "candidate_reference must identify an invitation candidate"
            )
        if self.candidate_reference.version != self.expected_candidate_version:
            raise ValueError("candidate reference version must match expected version")
        if self.allowed_decisions != [
            "confirm",
            "correct_and_confirm",
            "reject",
        ]:
            raise ValueError(
                "fact confirmation decisions are fixed by schema version 1"
            )
        return self


class RegisterInterviewInvitationCandidateResult(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    operation_id: str
    verification_id: str
    candidate: InterviewInvitationCandidateView
    replayed: bool = False


class ExplicitUserAssertionBasis(BaseModel):
    model_config = ConfigDict(
        extra="forbid", json_schema_serialization_defaults_required=True
    )

    kind: Literal["explicit_user_assertion"]
    source: InvitationSourceReference

    @model_validator(mode="after")
    def require_user_source(self) -> "ExplicitUserAssertionBasis":
        if self.source.kind not in {"manual", "user_message"}:
            raise ValueError(
                "explicit_user_assertion requires a manual or user_message source"
            )
        return self


class CandidateConfirmationBasis(BaseModel):
    model_config = ConfigDict(
        extra="forbid", json_schema_serialization_defaults_required=True
    )

    kind: Literal["candidate_confirmation"]
    candidate_id: str = Field(min_length=1, max_length=36)
    expected_candidate_version: PositiveInt
    interaction_id: str = Field(min_length=1, max_length=36)
    decision_identity: str = Field(min_length=1, max_length=128)


ConfirmationBasis = Annotated[
    ExplicitUserAssertionBasis | CandidateConfirmationBasis,
    Field(discriminator="kind"),
]


class LinkExistingOpportunity(BaseModel):
    model_config = ConfigDict(
        extra="forbid", json_schema_serialization_defaults_required=True
    )

    kind: Literal["link_existing"]
    opportunity_id: str = Field(min_length=1, max_length=35)
    expected_version: PositiveInt


class CreateOpportunity(BaseModel):
    model_config = ConfigDict(
        extra="forbid", json_schema_serialization_defaults_required=True
    )

    kind: Literal["create_new"]
    location: str | None = Field(default=None, max_length=200)
    team: str | None = Field(default=None, max_length=200)
    source_url: str | None = Field(default=None, max_length=4_000)
    source_provider: str | None = Field(default=None, max_length=80)
    external_job_id: str | None = Field(default=None, max_length=200)


OpportunityResolution = Annotated[
    LinkExistingOpportunity | CreateOpportunity,
    Field(discriminator="kind"),
]


class CreateInterview(BaseModel):
    model_config = ConfigDict(
        extra="forbid", json_schema_serialization_defaults_required=True
    )

    kind: Literal["create"] = "create"


class UpdateExistingInterview(BaseModel):
    model_config = ConfigDict(
        extra="forbid", json_schema_serialization_defaults_required=True
    )

    kind: Literal["update_existing"]
    interview_id: str = Field(min_length=1, max_length=128)
    expected_schedule_version: PositiveInt


InterviewResolution = Annotated[
    CreateInterview | UpdateExistingInterview,
    Field(discriminator="kind"),
]


class FactConfirmationResolution(BaseModel):
    """Typed user decision that resumes the owning Turn."""

    model_config = ConfigDict(
        extra="forbid", json_schema_serialization_defaults_required=True
    )

    protocol: Literal["interview_invitation.fact_confirmation.v1"] = (
        "interview_invitation.fact_confirmation.v1"
    )
    decision: Literal["confirm", "correct_and_confirm", "reject"]
    corrected_facts: InterviewInvitationFacts | None = None
    opportunity: OpportunityResolution | None = None
    interview: InterviewResolution = Field(default_factory=CreateInterview)
    reason: str | None = Field(default=None, max_length=2_000)

    @model_validator(mode="after")
    def validate_decision_shape(self) -> "FactConfirmationResolution":
        if self.decision == "reject":
            if self.corrected_facts is not None or self.opportunity is not None:
                raise ValueError("reject cannot include canonical write inputs")
            return self
        if self.opportunity is None:
            raise ValueError("confirmation requires an explicit opportunity resolution")
        if self.decision == "correct_and_confirm" and self.corrected_facts is None:
            raise ValueError("correct_and_confirm requires corrected_facts")
        if self.decision == "confirm" and self.corrected_facts is not None:
            raise ValueError("confirm uses the displayed candidate facts unchanged")
        return self


class OperationCausation(BaseModel):
    model_config = ConfigDict(
        extra="forbid", json_schema_serialization_defaults_required=True
    )

    conversation_id: str | None = Field(default=None, max_length=36)
    turn_id: str | None = Field(default=None, max_length=36)
    task_id: str | None = Field(default=None, max_length=36)
    tool_call_id: str | None = Field(default=None, max_length=256)


class ConfirmInterviewInvitation(BaseModel):
    model_config = ConfigDict(
        extra="forbid", json_schema_serialization_defaults_required=True
    )

    schema_version: Literal[1] = 1
    idempotency_key: str = Field(min_length=1, max_length=200)
    actor_kind: OperationActorKind
    asserted_at: AwareDatetime
    confirmation_basis: ConfirmationBasis
    facts: InterviewInvitationFacts
    opportunity: OpportunityResolution
    interview: InterviewResolution = Field(default_factory=CreateInterview)
    evidence: list[InvitationFieldEvidence] = Field(default_factory=list, max_length=30)
    causation: OperationCausation = Field(default_factory=OperationCausation)


class RejectInterviewInvitationCandidate(BaseModel):
    model_config = ConfigDict(
        extra="forbid", json_schema_serialization_defaults_required=True
    )

    schema_version: Literal[1] = 1
    idempotency_key: str = Field(min_length=1, max_length=200)
    actor_kind: OperationActorKind
    candidate_id: str = Field(min_length=1, max_length=36)
    expected_candidate_version: PositiveInt
    interaction_id: str = Field(min_length=1, max_length=36)
    decision_identity: str = Field(min_length=1, max_length=128)
    reason: str | None = Field(default=None, max_length=2_000)
    causation: OperationCausation = Field(default_factory=OperationCausation)


class VerificationView(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
        json_schema_serialization_defaults_required=True,
    )

    id: str
    operation_id: str
    schema_version: PositiveInt
    conclusion: Literal["pending", "verified", "failed", "unknown", "reconciled"]
    method: str
    expected_postconditions: list[dict[str, JsonValue]] = Field(
        validation_alias="expected_postconditions_json"
    )
    observed_evidence: list[dict[str, JsonValue]] = Field(
        validation_alias="observed_evidence_json"
    )
    failure_reason: str | None
    attempt: PositiveInt
    completed_at: datetime | None


class ConfirmInterviewInvitationResult(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    operation_id: str
    replayed: bool = False
    opportunity: ObjectReference
    interview: ObjectReference
    process_event: ObjectReference
    evidence: list[ObjectReference]
    domain_events: list[ObjectReference]
    verification: VerificationView
    projection_invalidations: list[str]


class RejectInterviewInvitationCandidateResult(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    operation_id: str
    replayed: bool = False
    candidate: ObjectReference
    domain_events: list[ObjectReference]
    verification: VerificationView


class InterviewInvitationHandoffView(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    opportunity: ObjectReference
    interview: ObjectReference
    company_name: str
    job_title: str
    scheduled_start_at: datetime
    scheduled_end_at: datetime | None
    original_time_text: str
    source_timezone: str
    stage_label: str | None
    location: str | None
    meeting_url: str | None
    source: InvitationSourceReference
    verification: VerificationView


__all__ = [
    "CandidateConfirmationBasis",
    "ConfirmInterviewInvitation",
    "ConfirmInterviewInvitationResult",
    "CreateInterview",
    "CreateOpportunity",
    "ExplicitUserAssertionBasis",
    "FactConfirmationRequest",
    "FactConfirmationResolution",
    "FixtureInterviewInvitationInput",
    "FixtureInterviewInvitationResult",
    "IntakeInterviewInvitationObservation",
    "IntakeInterviewInvitationResult",
    "InterviewInvitationCandidateFacts",
    "InterviewInvitationCandidateView",
    "InterviewInvitationFacts",
    "InterviewInvitationHandoffView",
    "InvitationFieldEvidence",
    "InvitationObservationView",
    "InvitationSourceReference",
    "LinkExistingOpportunity",
    "ObjectReference",
    "OpportunityMatchOption",
    "OperationActorKind",
    "OperationCausation",
    "RegisterInterviewInvitationCandidate",
    "RegisterInterviewInvitationCandidateResult",
    "RejectInterviewInvitationCandidate",
    "RejectInterviewInvitationCandidateResult",
    "UpdateExistingInterview",
    "VerificationView",
]
