"""Minimal VS-01 Context Compiler for a pending invitation decision."""

from __future__ import annotations

import hashlib
import json

from sqlalchemy.orm import Session

from app.db.types import utc_now
from app.models.conversation_turn import ConversationTurn
from app.models.interview_invitation import (
    InterviewInvitationCandidate,
    InterviewInvitationSourceSnapshot,
)
from app.schemas.context_package import (
    ContextBudget,
    ContextObjectReference,
    ContextPackage,
    ContextPackageSection,
    ContextPolicyScope,
    ContextSourceManifestItem,
    ContextSourceReference,
)
from app.schemas.interview_invitation import (
    InterviewInvitationCandidateFacts,
    InvitationFieldEvidence,
    InvitationSourceReference,
    OpportunityMatchOption,
)


_COMPILER_VERSION = "vs01.invitation-context@1"


def _sha256(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _source(reference: InvitationSourceReference) -> ContextSourceReference:
    return ContextSourceReference(
        kind=reference.kind,
        identity=reference.identity,
        version=reference.version,
        snapshot_id=reference.snapshot_id,
    )


def _manifest(
    db: Session,
    *,
    user_pk: int,
    references: list[InvitationSourceReference],
) -> list[ContextSourceManifestItem]:
    snapshot_ids = {item.snapshot_id for item in references if item.snapshot_id}
    snapshots = {
        row.id: row
        for row in db.query(InterviewInvitationSourceSnapshot)
        .filter(
            InterviewInvitationSourceSnapshot.user_id == user_pk,
            InterviewInvitationSourceSnapshot.id.in_(snapshot_ids),
        )
        .all()
    }
    result: list[ContextSourceManifestItem] = []
    seen: set[tuple[str, str, str | None, str | None]] = set()
    for item in references:
        identity = (item.kind, item.identity, item.version, item.snapshot_id)
        if identity in seen:
            continue
        seen.add(identity)
        snapshot = snapshots.get(item.snapshot_id or "")
        result.append(
            ContextSourceManifestItem(
                source=_source(item),
                object_owner="interview_invitation_source_snapshot",
                producer="source_intake" if snapshot is not None else "user_or_adapter",
                captured_or_observed_at=(
                    snapshot.observed_at if snapshot is not None else None
                ),
                authority="evidence",
                content_hash=(
                    snapshot.content_sha256
                    if snapshot is not None
                    else _sha256(
                        {
                            "kind": item.kind,
                            "identity": item.identity,
                            "version": item.version,
                        }
                    )
                ),
            )
        )
    return result


def compile_invitation_confirmation_context(
    db: Session,
    *,
    user_pk: int,
    turn: ConversationTurn,
    tool_call_id: str,
    candidate: InterviewInvitationCandidate,
    facts: InterviewInvitationCandidateFacts,
    evidence: list[InvitationFieldEvidence],
    opportunity_options: list[OpportunityMatchOption],
) -> ContextPackage:
    """Compile only the typed facts needed to decide this one candidate."""

    references = [item.source for item in evidence]
    source_manifest = _manifest(db, user_pk=user_pk, references=references)
    candidate_ref = ContextObjectReference(
        kind="interview_invitation_candidate",
        id=candidate.id,
        version=candidate.version,
    )
    opportunity_refs = [
        ContextObjectReference(
            kind="job_opportunity",
            id=item.opportunity_id,
            version=item.expected_version,
        )
        for item in opportunity_options
    ]
    package_identity = {
        "user": user_pk,
        "conversation": turn.conversation_id,
        "turn": turn.id,
        "tool_call": tool_call_id,
        "candidate": candidate.id,
        "candidate_version": candidate.version,
        "sources": [item.model_dump(mode="json") for item in source_manifest],
    }
    return ContextPackage(
        package_id=f"ctx_{_sha256(package_identity)[:32]}",
        compiled_at=utc_now(),
        user_scope=str(user_pk),
        conversation_id=turn.conversation_id,
        turn_id=turn.id,
        purpose="review_interview_invitation_candidate",
        object_scope=[candidate_ref, *opportunity_refs],
        policy_scope=ContextPolicyScope(
            actor_kind="agent",
            allowed_operations=[
                "query_interview_invitation_candidate",
                "confirm_interview_invitation",
                "reject_interview_invitation_candidate",
            ],
        ),
        budget=ContextBudget(),
        sections=[
            ContextPackageSection(
                role="observation_candidate",
                authority="candidate",
                content_or_reference={
                    "facts": facts.model_dump(mode="json"),
                    "missing_fields": list(candidate.missing_fields_json or []),
                    "conflicts": list(candidate.conflicts_json or []),
                    "confidence": candidate.confidence,
                    "extractor_version": candidate.extractor_version,
                },
                source_references=[_source(item) for item in references],
                object_versions=[candidate_ref],
                truncation_state="complete",
            ),
            ContextPackageSection(
                role="source_evidence",
                authority="evidence",
                content_or_reference={
                    "field_provenance": [
                        item.model_dump(mode="json") for item in evidence
                    ]
                },
                source_references=[_source(item) for item in references],
                object_versions=[candidate_ref],
                truncation_state="reference_only",
            ),
            ContextPackageSection(
                role="canonical_state",
                authority="canonical",
                content_or_reference={
                    "opportunity_match_options": [
                        item.model_dump(mode="json") for item in opportunity_options
                    ]
                },
                object_versions=opportunity_refs,
                truncation_state="bounded",
            ),
            ContextPackageSection(
                role="runtime_controls",
                authority="runtime",
                content_or_reference={
                    "tool_call_id": tool_call_id,
                    "allowed_decisions": [
                        "confirm",
                        "correct_and_confirm",
                        "reject",
                    ],
                    "execution_time_version_check": True,
                    "execution_time_policy_recheck": True,
                },
                object_versions=[candidate_ref],
                truncation_state="complete",
            ),
        ],
        source_manifest=source_manifest,
        compiler_version=_COMPILER_VERSION,
    )


__all__ = ["compile_invitation_confirmation_context"]
