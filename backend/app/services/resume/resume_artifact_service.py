"""Canonical personal-resume Application Service.

Personal resumes are ``Artifact(kind='resume')`` aggregates.  This module owns
only resume-specific selection/parsing commands and delegates all content and
history writes to ``artifact_service``. Migration 0029 copies any retired
``Resume`` identity into ``ArtifactResumeState.legacy_resume_id``; runtime alias
resolution reads that canonical sidecar and never the retired table.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import TypeAdapter, ValidationError
from sqlalchemy.orm import Session

from app.core.llm_client_factory import get_internal_llm
from app.db.types import utc_now
from app.models.artifact import Artifact, ArtifactResumeState, ArtifactVersion
from app.models.user import User
from app.schemas.artifact import ArtifactProvenanceInput, ArtifactWriteInput
from app.schemas.career_profile import (
    CareerProfileDraftInput,
    DirectionDraftChange,
    DirectionInput,
    FactDraftChange,
    PersonalFactInput,
)
from app.services import artifact_service, career_profile_service

MAX_ACTIVE_RESUMES = 2
_FACTS = TypeAdapter(list[PersonalFactInput])
_DIRECTIONS = TypeAdapter(list[DirectionInput])


class ResumeArtifactError(ValueError):
    pass


class ResumeArtifactNotFoundError(ResumeArtifactError):
    pass


class ResumeArtifactLimitError(ResumeArtifactError):
    pass


class ResumeArtifactNotReadyError(ResumeArtifactError):
    pass


class ResumeArtifactStaleVersionError(ResumeArtifactError):
    pass


@dataclass(frozen=True)
class ResumeArtifactRecord:
    artifact: Artifact
    state: ArtifactResumeState
    current_version: ArtifactVersion
    pending_draft_id: str | None


@dataclass(frozen=True)
class ExtractedProfileCandidates:
    facts: list[PersonalFactInput]
    directions: list[DirectionInput]


def list_resume_artifacts(
    db: Session, *, user_pk: int, include_archived: bool = False
) -> list[ResumeArtifactRecord]:
    query = (
        db.query(Artifact, ArtifactResumeState)
        .join(ArtifactResumeState, ArtifactResumeState.artifact_id == Artifact.id)
        .filter(
            Artifact.user_id == user_pk,
            ArtifactResumeState.user_id == user_pk,
            Artifact.kind == "resume",
        )
    )
    if not include_archived:
        query = query.filter(Artifact.archived_at.is_(None))
    pairs = query.order_by(
        ArtifactResumeState.is_default.desc(), Artifact.updated_at.desc()
    ).all()
    return [
        ResumeArtifactRecord(
            artifact=artifact,
            state=state,
            current_version=_current_version(db, artifact.id),
            pending_draft_id=_pending_draft_id(db, artifact.id),
        )
        for artifact, state in pairs
    ]


def resolve_owned_resume(
    db: Session, *, user_pk: int, resume_id: str, include_archived: bool = False
) -> ResumeArtifactRecord:
    normalized = (resume_id or "").strip()
    pair = (
        db.query(Artifact, ArtifactResumeState)
        .join(ArtifactResumeState, ArtifactResumeState.artifact_id == Artifact.id)
        .filter(
            Artifact.user_id == user_pk,
            ArtifactResumeState.user_id == user_pk,
            Artifact.kind == "resume",
            (
                (Artifact.id == normalized)
                | (ArtifactResumeState.legacy_resume_id == normalized)
            ),
        )
        .one_or_none()
    )
    if pair is None or (not include_archived and pair[0].archived_at is not None):
        raise ResumeArtifactNotFoundError(normalized)
    artifact, state = pair
    return ResumeArtifactRecord(
        artifact=artifact,
        state=state,
        current_version=_current_version(db, artifact.id),
        pending_draft_id=_pending_draft_id(db, artifact.id),
    )


def create_resume_artifact(
    db: Session,
    *,
    user_pk: int,
    operation_key: str,
    title: str,
    file_asset_id: str | None,
    raw_text: str | None,
    make_default: bool | None,
    content_format: str | None = None,
    file_asset_version: str | None = None,
    provenance: ArtifactProvenanceInput | None = None,
    source_owner_checker: Callable[[Session, int, str, str], bool] | None = None,
) -> ResumeArtifactRecord:
    _lock_user(db, user_pk=user_pk)
    existing = (
        db.query(Artifact.id)
        .filter(
            Artifact.user_id == user_pk,
            Artifact.creation_key == operation_key.strip(),
        )
        .scalar()
    )
    if (
        existing is None
        and _active_resume_artifact_count(db, user_pk=user_pk) >= MAX_ACTIVE_RESUMES
    ):
        raise ResumeArtifactLimitError("已有两份简历，请为其中一份添加新版本")
    artifact = artifact_service.save_artifact_explicitly(
        db,
        user_pk=user_pk,
        operation_key=operation_key,
        artifact_kind="resume",
        version=ArtifactWriteInput(
            title=title,
            content_text=(raw_text or "").strip() or None,
            content_format=(
                content_format or ("plain_text" if raw_text else "source_file")
            ),
            file_asset_id=file_asset_id,
            file_asset_version=file_asset_version,
            provenance=provenance or ArtifactProvenanceInput(),
        ),
        source_owner_checker=source_owner_checker,
    )
    return register_resume_artifact(
        db,
        user_pk=user_pk,
        artifact_id=artifact.id,
        make_default=make_default if existing is None else None,
        enforce_active_limit=existing is None,
    )


def add_resume_version(
    db: Session,
    *,
    user_pk: int,
    resume_id: str,
    operation_key: str,
    title: str,
    file_asset_id: str | None,
    raw_text: str | None,
    content_format: str | None = None,
    file_asset_version: str | None = None,
    provenance: ArtifactProvenanceInput | None = None,
    source_owner_checker: Callable[[Session, int, str, str], bool] | None = None,
) -> ResumeArtifactRecord:
    _lock_user(db, user_pk=user_pk)
    owned = resolve_owned_resume(db, user_pk=user_pk, resume_id=resume_id)
    replayed_version_id = (
        db.query(ArtifactVersion.id)
        .filter(
            ArtifactVersion.artifact_id == owned.artifact.id,
            ArtifactVersion.operation_key == operation_key.strip(),
        )
        .scalar()
    )
    edited_version = artifact_service.edit_artifact(
        db,
        user_pk=user_pk,
        artifact_id=owned.artifact.id,
        operation_key=operation_key,
        version=ArtifactWriteInput(
            title=title,
            content_text=(raw_text or "").strip() or None,
            content_format=(
                content_format or ("plain_text" if raw_text else "source_file")
            ),
            file_asset_id=file_asset_id,
            file_asset_version=file_asset_version,
            provenance=provenance or ArtifactProvenanceInput(),
        ),
        source_owner_checker=source_owner_checker,
    )
    if replayed_version_id is not None:
        return resolve_owned_resume(db, user_pk=user_pk, resume_id=owned.artifact.id)
    # Replaying an older idempotency key must not reset the parse state of a
    # newer version that already won the aggregate's version order.
    if _current_version(db, owned.artifact.id).id != edited_version.id:
        return resolve_owned_resume(db, user_pk=user_pk, resume_id=owned.artifact.id)
    owned.state.parse_status = "pending"
    owned.state.parse_error = None
    owned.state.parse_version_id = edited_version.id
    owned.state.updated_at = utc_now()
    db.add(owned.state)
    db.flush()
    return resolve_owned_resume(db, user_pk=user_pk, resume_id=owned.artifact.id)


def register_resume_artifact(
    db: Session,
    *,
    user_pk: int,
    artifact_id: str,
    make_default: bool | None = None,
    enforce_active_limit: bool = False,
) -> ResumeArtifactRecord:
    """Attach resume selection/parse metadata to an Artifact write.

    Artifact remains the only identity/content/version owner. This sidecar is
    required regardless of whether the explicit save entered through the
    resume manager, the general materials page, or a message promotion.
    """

    _lock_user(db, user_pk=user_pk)
    artifact = (
        db.query(Artifact)
        .filter(
            Artifact.id == artifact_id,
            Artifact.user_id == user_pk,
            Artifact.kind == "resume",
        )
        .one_or_none()
    )
    if artifact is None:
        raise ResumeArtifactNotFoundError(artifact_id)
    if (
        enforce_active_limit
        and artifact.archived_at is None
        and _active_resume_artifact_count(db, user_pk=user_pk) > MAX_ACTIVE_RESUMES
    ):
        raise ResumeArtifactLimitError("已有两份简历，请为其中一份添加新版本")

    state = (
        db.query(ArtifactResumeState)
        .filter(ArtifactResumeState.artifact_id == artifact.id)
        .one_or_none()
    )
    current_version = _current_version(db, artifact.id)
    if state is None:
        has_default = (
            db.query(ArtifactResumeState.id)
            .join(Artifact, Artifact.id == ArtifactResumeState.artifact_id)
            .filter(
                ArtifactResumeState.user_id == user_pk,
                ArtifactResumeState.is_default.is_(True),
                Artifact.archived_at.is_(None),
            )
            .first()
            is not None
        )
        should_default = bool(make_default) or not has_default
        if should_default:
            _clear_default(db, user_pk=user_pk)
        state = ArtifactResumeState(
            artifact_id=artifact.id,
            user_id=user_pk,
            is_default=should_default,
            parse_status="pending",
            parse_version_id=current_version.id,
        )
        db.add(state)
        db.flush()
    elif make_default and not state.is_default:
        _clear_default(db, user_pk=user_pk)
        state.is_default = True
        state.updated_at = utc_now()
        db.add(state)
        db.flush()
    return resolve_owned_resume(
        db,
        user_pk=user_pk,
        resume_id=artifact.id,
        include_archived=True,
    )


def set_default_resume_artifact(
    db: Session, *, user_pk: int, resume_id: str
) -> ResumeArtifactRecord:
    _lock_user(db, user_pk=user_pk)
    owned = resolve_owned_resume(db, user_pk=user_pk, resume_id=resume_id)
    _clear_default(db, user_pk=user_pk)
    owned.state.is_default = True
    owned.state.updated_at = utc_now()
    db.add(owned.state)
    db.flush()
    return resolve_owned_resume(db, user_pk=user_pk, resume_id=owned.artifact.id)


def archive_resume_artifact(db: Session, *, user_pk: int, resume_id: str) -> bool:
    _lock_user(db, user_pk=user_pk)
    owned = resolve_owned_resume(db, user_pk=user_pk, resume_id=resume_id)
    was_default = bool(owned.state.is_default)
    owned.state.is_default = False
    db.add(owned.state)
    artifact_service.archive_artifact(
        db, user_pk=user_pk, artifact_id=owned.artifact.id
    )
    if was_default:
        remaining = list_resume_artifacts(db, user_pk=user_pk)
        if remaining:
            remaining[0].state.is_default = True
            db.add(remaining[0].state)
    db.flush()
    return True


def mark_parse_state(
    db: Session,
    *,
    user_pk: int,
    resume_id: str,
    status: str,
    error: str | None = None,
    source_version_id: str | None = None,
) -> ResumeArtifactRecord:
    if status not in {"pending", "processing", "ready", "failed"}:
        raise ResumeArtifactError(f"Unsupported parse status {status}")
    _lock_user(db, user_pk=user_pk)
    owned = resolve_owned_resume(
        db, user_pk=user_pk, resume_id=resume_id, include_archived=True
    )
    target_version_id = source_version_id or owned.current_version.id
    if owned.current_version.id != target_version_id:
        raise ResumeArtifactStaleVersionError(
            "Resume parse result belongs to a superseded version"
        )
    owned.state.parse_status = status
    owned.state.parse_error = error
    owned.state.parse_version_id = target_version_id
    owned.state.updated_at = utc_now()
    db.add(owned.state)
    db.flush()
    return resolve_owned_resume(
        db,
        user_pk=user_pk,
        resume_id=owned.artifact.id,
        include_archived=True,
    )


def claim_resume_parse(
    db: Session,
    *,
    user_pk: int,
    resume_id: str,
) -> ResumeArtifactRecord | None:
    """Claim the current immutable version for one parse worker.

    The user-row lock serialises upload/default/archive commands with parser
    claims. A duplicate delivery for the same version observes ``processing``
    or ``ready`` and exits without starting another extraction/model call.
    """

    _lock_user(db, user_pk=user_pk)
    owned = resolve_owned_resume(db, user_pk=user_pk, resume_id=resume_id)
    if (
        owned.state.parse_version_id == owned.current_version.id
        and owned.state.parse_status in {"processing", "ready"}
    ):
        return None
    owned.state.parse_status = "processing"
    owned.state.parse_error = None
    owned.state.parse_version_id = owned.current_version.id
    owned.state.updated_at = utc_now()
    db.add(owned.state)
    db.flush()
    return resolve_owned_resume(db, user_pk=user_pk, resume_id=owned.artifact.id)


def persist_extracted_resume(
    db: Session,
    *,
    user_pk: int,
    resume_id: str,
    source_version_id: str,
    text: str,
    candidates: ExtractedProfileCandidates,
) -> ResumeArtifactRecord:
    """Append extracted text if needed and create one idempotent draft."""

    _lock_user(db, user_pk=user_pk)
    owned = resolve_owned_resume(db, user_pk=user_pk, resume_id=resume_id)
    if owned.current_version.id != source_version_id:
        # A newer user version won the race; never attach stale extraction to it.
        raise ResumeArtifactStaleVersionError(
            "Resume changed while extraction was running"
        )
    normalized_text = text.strip()
    source_version = owned.current_version
    candidate_version = source_version
    if (
        normalized_text
        and (source_version.content_text or "").strip() != normalized_text
    ):
        candidate_version = artifact_service.edit_artifact(
            db,
            user_pk=user_pk,
            artifact_id=owned.artifact.id,
            operation_key=f"resume_extract:{source_version.id}",
            version=ArtifactWriteInput(
                title=source_version.title,
                content_text=normalized_text,
                content_format="plain_text",
                file_asset_id=source_version.file_asset_id,
                file_asset_version=source_version.file_asset_version,
                provenance=ArtifactProvenanceInput(
                    source_owner_type="artifact_version",
                    source_owner_id=source_version.id,
                ),
            ),
            source_owner_checker=_artifact_version_owner_checker,
        )
    if candidates.facts or candidates.directions:
        # Import locally to keep this module dependent on the Application
        # Service contract rather than exposing the draft model as an API.
        from app.models.career_profile import CareerProfileDraftChange

        existing = (
            db.query(CareerProfileDraftChange)
            .filter(
                CareerProfileDraftChange.source_kind == "artifact_version",
                CareerProfileDraftChange.source_id == candidate_version.id,
            )
            .one_or_none()
        )
        if existing is None:
            career_profile_service.ensure_career_profile(db, user_pk=user_pk)
            career_profile_service.create_profile_draft_change(
                db,
                user_pk=user_pk,
                draft=CareerProfileDraftInput(
                    source_kind="artifact_version",
                    source_id=candidate_version.id,
                    proposed_facts=[
                        FactDraftChange(operation="upsert", fact=fact)
                        for fact in candidates.facts
                    ],
                    proposed_directions=[
                        DirectionDraftChange(operation="upsert", direction=direction)
                        for direction in candidates.directions
                    ],
                ),
            )
    owned.state.parse_status = "ready"
    owned.state.parse_error = None
    owned.state.parse_version_id = candidate_version.id
    owned.state.updated_at = utc_now()
    db.add(owned.state)
    db.flush()
    return resolve_owned_resume(db, user_pk=user_pk, resume_id=owned.artifact.id)


async def extract_profile_candidates(
    text: str, *, user_id: str | None = None
) -> ExtractedProfileCandidates:
    """Extract only explicit document facts/goals into typed candidates."""

    normalized = text.strip()
    if not normalized:
        return ExtractedProfileCandidates(facts=[], directions=[])
    prompt = _candidate_prompt(normalized)
    try:
        response = await get_internal_llm("worker").acomplete(
            prompt,
            response_format={"type": "json_object"},
        )
        payload = _json_payload(str(response.text))
        facts = _FACTS.validate_python(payload.get("facts") or [])
        directions = _DIRECTIONS.validate_python(payload.get("directions") or [])
        return ExtractedProfileCandidates(facts=facts, directions=directions)
    except (ValueError, ValidationError, json.JSONDecodeError):
        # A malformed model response must not invent or partially confirm
        # personal facts. The Artifact remains usable and the empty candidate
        # result is visible as "no structured candidates".
        return ExtractedProfileCandidates(facts=[], directions=[])


def read_resume_text(record: ResumeArtifactRecord) -> str:
    text = (record.current_version.content_text or "").strip()
    if text:
        return text
    if record.state.parse_status in {"pending", "processing"}:
        raise ResumeArtifactNotReadyError("简历仍在解析，请稍后重试")
    if record.state.parse_status == "failed":
        raise ResumeArtifactNotReadyError(record.state.parse_error or "简历解析失败")
    raise ResumeArtifactNotReadyError("简历没有可读取的文本")


def _current_version(db: Session, artifact_id: str) -> ArtifactVersion:
    row = (
        db.query(ArtifactVersion)
        .filter(ArtifactVersion.artifact_id == artifact_id)
        .order_by(ArtifactVersion.version_no.desc())
        .first()
    )
    if row is None:
        raise ResumeArtifactNotFoundError(artifact_id)
    return row


def _pending_draft_id(db: Session, artifact_id: str) -> str | None:
    from app.models.career_profile import CareerProfileDraftChange

    version_ids = db.query(ArtifactVersion.id).filter(
        ArtifactVersion.artifact_id == artifact_id
    )
    return (
        db.query(CareerProfileDraftChange.id)
        .filter(
            CareerProfileDraftChange.source_kind == "artifact_version",
            CareerProfileDraftChange.source_id.in_(version_ids),
            CareerProfileDraftChange.status == "pending",
        )
        .order_by(CareerProfileDraftChange.created_at.desc())
        .scalar()
    )


def _clear_default(db: Session, *, user_pk: int) -> None:
    db.query(ArtifactResumeState).filter(
        ArtifactResumeState.user_id == user_pk,
        ArtifactResumeState.is_default.is_(True),
    ).update({ArtifactResumeState.is_default: False}, synchronize_session=False)
    db.flush()


def _active_resume_artifact_count(db: Session, *, user_pk: int) -> int:
    return int(
        db.query(Artifact.id)
        .filter(
            Artifact.user_id == user_pk,
            Artifact.kind == "resume",
            Artifact.archived_at.is_(None),
        )
        .count()
    )


def _lock_user(db: Session, *, user_pk: int) -> User:
    row = db.query(User).filter(User.id == user_pk).with_for_update().one_or_none()
    if row is None:
        raise ResumeArtifactNotFoundError(f"Unknown user {user_pk}")
    return row


def _artifact_version_owner_checker(
    db: Session, user_pk: int, owner_type: str, owner_id: str
) -> bool:
    if owner_type != "artifact_version":
        return False
    return (
        db.query(ArtifactVersion.id)
        .join(Artifact, Artifact.id == ArtifactVersion.artifact_id)
        .filter(ArtifactVersion.id == owner_id, Artifact.user_id == user_pk)
        .scalar()
        is not None
    )


def _json_payload(raw: str) -> dict[str, Any]:
    normalized = raw.strip()
    if normalized.startswith("```"):
        normalized = normalized.strip("`")
        if normalized.lstrip().startswith("json"):
            normalized = normalized.lstrip()[4:].lstrip()
    payload = json.loads(normalized)
    if not isinstance(payload, dict):
        raise ValueError("candidate extraction must return an object")
    return payload


def _candidate_prompt(text: str) -> str:
    return f"""你负责把用户明确导入的简历整理为“待用户确认”的求职档案候选。
只抽取文档明确陈述的事实；不要推断能力、人格、资历水平或未写明的目标。
不要把简历措辞当成已确认事实。返回严格 JSON：
{{"facts": [...], "directions": [...]}}

facts 允许的结构：
- education: kind,institution,degree?,field_of_study?,description?,start_date?,end_date?
- experience: kind,organization,role,description?,start_date?,end_date?
- project: kind,name,role?,description?,technologies,start_date?,end_date?
- skill: kind,name,category?
- achievement: kind,title,description?,occurred_on?
- contact: kind,channel(email|phone|website|other),value
- location: kind,value
directions 仅在简历明确写有求职目标时输出，结构为
label, criteria(role_keywords,seniority,locations,work_modes,salary_min,salary_max,
salary_currency,industries,technologies,exclusions), lifecycle(exploring), priority(0)。
日期使用 YYYY-MM-DD；不确定日期留空，不要猜测。

<resume>
{text[:30000]}
</resume>"""


def new_operation_key(prefix: str) -> str:
    return f"{prefix}:{uuid.uuid4().hex}"


__all__ = [
    "ExtractedProfileCandidates",
    "MAX_ACTIVE_RESUMES",
    "ResumeArtifactError",
    "ResumeArtifactLimitError",
    "ResumeArtifactNotFoundError",
    "ResumeArtifactNotReadyError",
    "ResumeArtifactStaleVersionError",
    "ResumeArtifactRecord",
    "add_resume_version",
    "archive_resume_artifact",
    "create_resume_artifact",
    "claim_resume_parse",
    "extract_profile_candidates",
    "list_resume_artifacts",
    "mark_parse_state",
    "new_operation_key",
    "persist_extracted_resume",
    "read_resume_text",
    "register_resume_artifact",
    "resolve_owned_resume",
    "set_default_resume_artifact",
]
