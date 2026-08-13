"""Application Service for source-grounded inferred AbilitySignal state.

This service validates explicit real-owner references and lifecycle CAS.  It
does not run a model, write CareerProfile or a source record, or interact with
Long-term Memory.  Source dispatch is intentionally a closed set of direct
queries here, not a reusable owner/Evidence registry.
"""

from __future__ import annotations

import json
import hashlib
import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from app.db.types import utc_now
from app.models.ability_signal import AbilitySignal, AbilitySignalSourceRef
from app.models.agent_execution import AgentToolCall
from app.models.artifact import Artifact, ArtifactVersion
from app.models.career_profile import CareerProfile, CareerProfileDirection
from app.models.chat import Conversation, ConversationMessage
from app.models.interview_qa import InterviewQA
from app.models.interview_record import InterviewRecord
from app.models.job_opportunity import JobOpportunity, ProcessEvent
from app.models.user import User
from app.schemas.ability_signal import (
    AbilitySignalCreateInput,
    AbilitySignalSourceView,
    AbilitySignalView,
    AbilitySourceRefInput,
)


class AbilitySignalError(ValueError):
    pass


class AbilitySignalNotFoundError(AbilitySignalError):
    pass


class AbilitySignalOwnershipError(AbilitySignalError):
    pass


class AbilitySignalConflictError(AbilitySignalError):
    pass


class AbilitySignalSourceError(AbilitySignalError):
    pass


def create_ability_signal(
    db: Session,
    *,
    user_pk: int,
    assessment: AbilitySignalCreateInput,
    supersedes_signal_id: str | None = None,
    expected_superseded_version: int | None = None,
    producer_key: str | None = None,
) -> AbilitySignalView:
    """Persist an upstream assessment after validating scope and every source.

    A revision/recompute creates a new signal and CAS-supersedes the old one;
    historical inference is never rewritten in place.
    """

    if db.get(User, user_pk) is None:
        raise AbilitySignalOwnershipError(f"Unknown user {user_pk}")
    normalized_producer_key = producer_key.strip() if producer_key else None
    if normalized_producer_key and len(normalized_producer_key) > 240:
        raise AbilitySignalConflictError("AbilitySignal producer key is too long")
    if normalized_producer_key:
        existing = (
            db.query(AbilitySignal)
            .filter(
                AbilitySignal.user_id == user_pk,
                AbilitySignal.producer_key == normalized_producer_key,
            )
            .one_or_none()
        )
        if existing is not None:
            return _signal_view(db, existing)
    _validate_scope(
        db,
        user_pk=user_pk,
        scope_kind=assessment.scope.kind,
        scope_ref_id=assessment.scope.ref_id,
    )
    seen: set[tuple[str, str]] = set()
    resolved_sources: list[tuple[AbilitySourceRefInput, str | None]] = []
    for source in assessment.sources:
        identity = (source.kind, source.source_id)
        if identity in seen:
            raise AbilitySignalSourceError(
                f"Duplicate AbilitySignal source {source.kind}/{source.source_id}"
            )
        seen.add(identity)
        resolved_sources.append(
            (
                source,
                _source_version(db, user_pk=user_pk, source=source),
            )
        )

    previous = None
    if supersedes_signal_id is not None:
        if expected_superseded_version is None:
            raise AbilitySignalConflictError(
                "expected_superseded_version is required for a revision"
            )
        previous = _owned_signal(db, user_pk=user_pk, signal_id=supersedes_signal_id)
        if previous.status not in {"active", "disputed"}:
            raise AbilitySignalConflictError(
                f"Signal {previous.id} cannot be superseded from {previous.status}"
            )
    elif expected_superseded_version is not None:
        raise AbilitySignalConflictError(
            "expected_superseded_version requires supersedes_signal_id"
        )

    signal_id = _id("as")
    now = utc_now()
    with db.begin_nested():
        if previous is not None:
            changed = (
                db.query(AbilitySignal)
                .filter(
                    AbilitySignal.id == previous.id,
                    AbilitySignal.user_id == user_pk,
                    AbilitySignal.status.in_(("active", "disputed")),
                    AbilitySignal.version == expected_superseded_version,
                )
                .update(
                    {
                        AbilitySignal.status: "superseded",
                        AbilitySignal.status_reason: f"Superseded by {signal_id}",
                        AbilitySignal.status_changed_at: now,
                        AbilitySignal.updated_at: now,
                        AbilitySignal.version: AbilitySignal.version + 1,
                    },
                    synchronize_session=False,
                )
            )
            if changed != 1:
                raise AbilitySignalConflictError(
                    f"Signal {previous.id} changed before it could be superseded"
                )

        row = AbilitySignal(
            id=signal_id,
            user_id=user_pk,
            topic=assessment.topic.strip(),
            signal_type=assessment.signal_type.strip(),
            level=assessment.level.strip() if assessment.level else None,
            score=assessment.score,
            summary=assessment.summary.strip(),
            confidence=assessment.confidence,
            limitations=(
                assessment.limitations.strip() if assessment.limitations else None
            ),
            scope_kind=assessment.scope.kind,
            scope_ref_id=assessment.scope.ref_id,
            formed_at=assessment.formed_at,
            rubric_version=(
                assessment.rubric_version.strip() if assessment.rubric_version else None
            ),
            status="active",
            supersedes_signal_id=previous.id if previous is not None else None,
            producer_key=normalized_producer_key,
            version=1,
            status_changed_at=now,
        )
        db.add(row)
        db.flush()
        for source, source_version in resolved_sources:
            db.add(
                AbilitySignalSourceRef(
                    ability_signal_id=row.id,
                    source_kind=source.kind,
                    source_id=source.source_id,
                    source_version=source_version,
                )
            )
        db.flush()
    return _signal_view(db, row)


def get_ability_signal(
    db: Session, *, user_pk: int, signal_id: str
) -> AbilitySignalView:
    return _signal_view(
        db,
        _owned_signal(db, user_pk=user_pk, signal_id=signal_id),
    )


def list_ability_signals(
    db: Session,
    *,
    user_pk: int,
    include_inactive: bool = False,
) -> list[AbilitySignalView]:
    query = db.query(AbilitySignal).filter(AbilitySignal.user_id == user_pk)
    if not include_inactive:
        query = query.filter(AbilitySignal.status.in_(("active", "disputed")))
    rows = query.order_by(AbilitySignal.formed_at.desc()).all()
    return [_signal_view(db, row) for row in rows]


def dispute_ability_signal(
    db: Session,
    *,
    user_pk: int,
    signal_id: str,
    expected_version: int,
    reason: str,
) -> AbilitySignalView:
    return _change_status(
        db,
        user_pk=user_pk,
        signal_id=signal_id,
        expected_version=expected_version,
        from_statuses=("active",),
        to_status="disputed",
        reason=reason,
    )


def invalidate_ability_signal(
    db: Session,
    *,
    user_pk: int,
    signal_id: str,
    expected_version: int,
    reason: str,
) -> AbilitySignalView:
    return _change_status(
        db,
        user_pk=user_pk,
        signal_id=signal_id,
        expected_version=expected_version,
        from_statuses=("active", "disputed"),
        to_status="invalidated",
        reason=reason,
    )


def invalidate_ability_signals_for_interview_delete(
    db: Session,
    *,
    user_pk: int,
    interview_record_id: str,
    conversation_ids: tuple[str, ...] = (),
) -> int:
    """Invalidate live signals whose scope or final sources are deleted.

    This is the narrow deterministic synchronizer for the InterviewRecord
    delete command. Direct identities remain as provenance tombstones on the
    signal; they do not become a generic Source or Evidence owner.
    """

    normalized_record_id = interview_record_id.strip()
    if not normalized_record_id:
        raise AbilitySignalSourceError("interview_record_id cannot be blank")

    removed_sources: set[tuple[str, str]] = {("interview_record", normalized_record_id)}
    removed_sources.update(
        ("interview_qa", str(source_id))
        for (source_id,) in db.query(InterviewQA.id)
        .filter(InterviewQA.record_id == normalized_record_id)
        .all()
    )

    normalized_conversation_ids = tuple(
        dict.fromkeys(
            conversation_id.strip()
            for conversation_id in conversation_ids
            if conversation_id and conversation_id.strip()
        )
    )
    if normalized_conversation_ids:
        removed_sources.update(
            ("conversation_message", str(source_id))
            for (source_id,) in db.query(ConversationMessage.id)
            .filter(
                ConversationMessage.conversation_id.in_(normalized_conversation_ids)
            )
            .all()
        )
        removed_sources.update(
            ("agent_tool_call", str(source_id))
            for (source_id,) in db.query(AgentToolCall.id)
            .filter(AgentToolCall.session_id.in_(normalized_conversation_ids))
            .all()
        )

    signals = (
        db.query(AbilitySignal)
        .filter(
            AbilitySignal.user_id == user_pk,
            AbilitySignal.status.in_(("active", "disputed")),
        )
        .with_for_update()
        .all()
    )
    if not signals:
        return 0

    refs_by_signal: dict[str, list[tuple[str, str]]] = {
        signal.id: [] for signal in signals
    }
    for ref in (
        db.query(AbilitySignalSourceRef)
        .filter(AbilitySignalSourceRef.ability_signal_id.in_(refs_by_signal))
        .all()
    ):
        refs_by_signal[ref.ability_signal_id].append((ref.source_kind, ref.source_id))

    now = utc_now()
    changed = 0
    for signal in signals:
        sources = refs_by_signal[signal.id]
        scope_deleted = (
            signal.scope_kind == "interview_record"
            and signal.scope_ref_id == normalized_record_id
        )
        all_sources_deleted = bool(sources) and all(
            source in removed_sources for source in sources
        )
        if not scope_deleted and not all_sources_deleted:
            continue
        signal.status = "invalidated"
        signal.status_reason = (
            f"InterviewRecord {normalized_record_id} was deleted; "
            + (
                "the signal applicability scope no longer exists"
                if scope_deleted
                else "all supporting sources were removed"
            )
        )
        signal.status_changed_at = now
        signal.updated_at = now
        signal.version = int(signal.version) + 1
        changed += 1

    db.flush()
    return changed


def project_interview_ability_signals(
    db: Session,
    *,
    user_pk: int,
    interview_record_id: str,
    force_new_generation: bool = False,
) -> list[AbilitySignalView]:
    """Project bounded ability judgements from a persisted Interview analysis.

    Each radar dimension becomes one canonical signal with direct
    InterviewRecord and scored InterviewQA identities. Replays of the same
    generation are idempotent; an explicit recompute advances the record's
    generation and supersedes the previous live projection.
    """

    record = (
        db.query(InterviewRecord)
        .filter(
            InterviewRecord.id == interview_record_id,
            InterviewRecord.user_id == user_pk,
        )
        .with_for_update()
        .one_or_none()
    )
    if record is None:
        raise AbilitySignalSourceError(
            f"Owned interview_record {interview_record_id} does not exist"
        )
    try:
        analysis = (
            json.loads(record.analysis_json)
            if isinstance(record.analysis_json, str)
            else (record.analysis_json or {})
        )
    except (TypeError, json.JSONDecodeError) as exc:
        raise AbilitySignalSourceError("Interview analysis is not readable") from exc
    radar = analysis.get("skill_radar") if isinstance(analysis, dict) else None
    if not isinstance(radar, dict):
        raise AbilitySignalSourceError(
            "Interview analysis has no structured skill_radar"
        )
    if force_new_generation:
        record.ability_signal_generation = int(record.ability_signal_generation) + 1
        db.add(record)
        db.flush()
    generation = int(record.ability_signal_generation)
    if generation < 1:
        record.ability_signal_generation = 1
        generation = 1
        db.add(record)
        db.flush()

    qas = (
        db.query(InterviewQA)
        .filter(InterviewQA.record_id == record.id, InterviewQA.score.isnot(None))
        .order_by(InterviewQA.order_idx.asc())
        .all()
    )
    all_qa_count = (
        db.query(InterviewQA.id).filter(InterviewQA.record_id == record.id).count()
    )
    sources = [
        AbilitySourceRefInput(kind="interview_record", source_id=record.id),
        *[
            AbilitySourceRefInput(kind="interview_qa", source_id=qa.id)
            for qa in qas[:99]
        ],
    ]
    coverage = len(qas) / max(1, all_qa_count)
    confidence = round(min(0.9, 0.55 + 0.35 * coverage), 2)
    formed_at = max(
        (qa.analyzed_at or qa.created_at for qa in qas),
        default=record.updated_at or record.created_at or utc_now(),
    )
    created: list[AbilitySignalView] = []
    current_keys: set[str] = set()
    for raw_topic, raw_score in sorted(radar.items(), key=lambda item: str(item[0])):
        if raw_score is None:
            continue
        try:
            score = float(raw_score)
        except (TypeError, ValueError):
            continue
        if not 0 <= score <= 10:
            continue
        topic = str(raw_topic).strip()[:200]
        if not topic:
            continue
        topic_key = hashlib.sha256(topic.encode("utf-8")).hexdigest()[:16]
        producer_key = f"interview:{record.id}:g{generation}:{topic_key}"
        current_keys.add(producer_key)
        previous = _latest_live_interview_signal(
            db,
            user_pk=user_pk,
            interview_record_id=record.id,
            topic=topic,
            exclude_producer_key=producer_key,
        )
        created.append(
            create_ability_signal(
                db,
                user_pk=user_pk,
                assessment=AbilitySignalCreateInput(
                    topic=topic,
                    signal_type=(
                        "mock_interview_performance"
                        if record.source == "mock"
                        else "interview_performance"
                    ),
                    level=_score_level(score),
                    score=round(score, 1),
                    summary=(
                        f"本次{'模拟' if record.source == 'mock' else '真实'}面试中，"
                        f"{topic}相关回答的聚合评分为 {score:.1f}/10。"
                    ),
                    confidence=confidence,
                    limitations=(
                        "仅适用于这次面试及其题目覆盖；评分会受题目难度、岗位匹配、"
                        "表达状态和评分 rubric 影响，不能解释为稳定人格或总体能力定论。"
                    ),
                    scope={"kind": "interview_record", "ref_id": record.id},
                    formed_at=formed_at,
                    rubric_version=f"interview_analysis_v{record.analysis_schema_version}",
                    sources=sources,
                ),
                supersedes_signal_id=previous.id if previous is not None else None,
                expected_superseded_version=(
                    previous.version if previous is not None else None
                ),
                producer_key=producer_key,
            )
        )

    # A recompute may remove a formerly scored dimension. Such a signal cannot
    # survive as an unexplained live judgement.
    live_for_record = _live_interview_signals(
        db, user_pk=user_pk, interview_record_id=record.id
    )
    now = utc_now()
    for signal in live_for_record:
        if not (signal.producer_key or "").startswith(f"interview:{record.id}:"):
            continue
        if signal.producer_key in current_keys:
            continue
        signal.status = "invalidated"
        signal.status_reason = (
            f"Interview analysis generation {generation} no longer produced "
            "this dimension"
        )
        signal.status_changed_at = now
        signal.updated_at = now
        signal.version = int(signal.version) + 1
    db.flush()
    return created


def invalidate_ability_signals_for_interview_reanalysis(
    db: Session,
    *,
    user_pk: int,
    interview_record_id: str,
) -> int:
    """Invalidate the prior projection before its source analysis is reset."""

    rows = _live_interview_signals(
        db, user_pk=user_pk, interview_record_id=interview_record_id
    )
    now = utc_now()
    for row in rows:
        row.status = "invalidated"
        row.status_reason = "Interview analysis was reset for recomputation"
        row.status_changed_at = now
        row.updated_at = now
        row.version = int(row.version) + 1
    db.flush()
    return len(rows)


def _live_interview_signals(
    db: Session, *, user_pk: int, interview_record_id: str
) -> list[AbilitySignal]:
    return (
        db.query(AbilitySignal)
        .join(
            AbilitySignalSourceRef,
            AbilitySignalSourceRef.ability_signal_id == AbilitySignal.id,
        )
        .filter(
            AbilitySignal.user_id == user_pk,
            AbilitySignal.status.in_(("active", "disputed")),
            AbilitySignalSourceRef.source_kind == "interview_record",
            AbilitySignalSourceRef.source_id == interview_record_id,
            AbilitySignal.producer_key.like(f"interview:{interview_record_id}:%"),
        )
        .distinct()
        .all()
    )


def _latest_live_interview_signal(
    db: Session,
    *,
    user_pk: int,
    interview_record_id: str,
    topic: str,
    exclude_producer_key: str,
) -> AbilitySignal | None:
    return (
        db.query(AbilitySignal)
        .join(
            AbilitySignalSourceRef,
            AbilitySignalSourceRef.ability_signal_id == AbilitySignal.id,
        )
        .filter(
            AbilitySignal.user_id == user_pk,
            AbilitySignal.topic == topic,
            AbilitySignal.status.in_(("active", "disputed")),
            AbilitySignalSourceRef.source_kind == "interview_record",
            AbilitySignalSourceRef.source_id == interview_record_id,
            AbilitySignal.producer_key.like(f"interview:{interview_record_id}:%"),
            AbilitySignal.producer_key != exclude_producer_key,
        )
        .order_by(AbilitySignal.formed_at.desc())
        .first()
    )


def _score_level(score: float) -> str:
    if score >= 8.5:
        return "本次表现突出"
    if score >= 7:
        return "本次表现良好"
    if score >= 5.5:
        return "本次表现中等"
    return "本次表现需要改进"


def _change_status(
    db: Session,
    *,
    user_pk: int,
    signal_id: str,
    expected_version: int,
    from_statuses: tuple[str, ...],
    to_status: str,
    reason: str,
) -> AbilitySignalView:
    normalized_reason = reason.strip()
    if not normalized_reason:
        raise AbilitySignalError("A status change requires a reason")
    row = _owned_signal(db, user_pk=user_pk, signal_id=signal_id)
    now = utc_now()
    changed = (
        db.query(AbilitySignal)
        .filter(
            AbilitySignal.id == row.id,
            AbilitySignal.user_id == user_pk,
            AbilitySignal.status.in_(from_statuses),
            AbilitySignal.version == expected_version,
        )
        .update(
            {
                AbilitySignal.status: to_status,
                AbilitySignal.status_reason: normalized_reason,
                AbilitySignal.status_changed_at: now,
                AbilitySignal.updated_at: now,
                AbilitySignal.version: AbilitySignal.version + 1,
            },
            synchronize_session=False,
        )
    )
    if changed != 1:
        current = (
            db.query(AbilitySignal.status, AbilitySignal.version)
            .filter(AbilitySignal.id == row.id)
            .one()
        )
        raise AbilitySignalConflictError(
            f"Signal {row.id} is {current.status}/version={current.version}"
        )
    db.flush()
    return _signal_view(db, row)


def _owned_signal(db: Session, *, user_pk: int, signal_id: str) -> AbilitySignal:
    row = db.query(AbilitySignal).filter(AbilitySignal.id == signal_id).one_or_none()
    if row is None:
        raise AbilitySignalNotFoundError(f"AbilitySignal {signal_id} not found")
    if row.user_id != user_pk:
        raise AbilitySignalOwnershipError(
            f"User {user_pk} does not own AbilitySignal {signal_id}"
        )
    return row


def _validate_scope(
    db: Session,
    *,
    user_pk: int,
    scope_kind: str,
    scope_ref_id: str | None,
) -> None:
    if scope_kind == "general":
        return
    if scope_kind == "career_direction":
        exists = (
            db.query(CareerProfileDirection.id)
            .join(
                CareerProfile,
                CareerProfile.id == CareerProfileDirection.career_profile_id,
            )
            .filter(
                CareerProfileDirection.id == scope_ref_id,
                CareerProfile.user_id == user_pk,
            )
            .scalar()
        )
    elif scope_kind == "job_opportunity":
        exists = (
            db.query(JobOpportunity.id)
            .filter(
                JobOpportunity.id == scope_ref_id, JobOpportunity.user_id == user_pk
            )
            .scalar()
        )
    elif scope_kind == "interview_record":
        exists = (
            db.query(InterviewRecord.id)
            .filter(
                InterviewRecord.id == scope_ref_id, InterviewRecord.user_id == user_pk
            )
            .scalar()
        )
    else:
        raise AbilitySignalSourceError(f"Unsupported AbilitySignal scope {scope_kind}")
    if exists is None:
        raise AbilitySignalSourceError(
            f"Owned {scope_kind} scope {scope_ref_id} does not exist"
        )


def _source_version(
    db: Session,
    *,
    user_pk: int,
    source: AbilitySourceRefInput,
) -> str | None:
    source_id = source.source_id
    if source.kind == "interview_record":
        row = (
            db.query(InterviewRecord)
            .filter(InterviewRecord.id == source_id, InterviewRecord.user_id == user_pk)
            .one_or_none()
        )
        version = (
            f"analysis:{row.analysis_schema_version}@{_timestamp(row.updated_at)}"
            if row is not None
            else None
        )
    elif source.kind == "interview_qa":
        row = (
            db.query(InterviewQA)
            .join(InterviewRecord, InterviewRecord.id == InterviewQA.record_id)
            .filter(InterviewQA.id == source_id, InterviewRecord.user_id == user_pk)
            .one_or_none()
        )
        version = _timestamp(row.analyzed_at or row.created_at) if row else None
    elif source.kind == "conversation_message":
        row = _integer_owned_source(
            db,
            source_id=source_id,
            model=ConversationMessage,
            owner_join=Conversation,
            owner_join_on=Conversation.id == ConversationMessage.conversation_id,
            owner_filter=Conversation.user_id == user_pk,
        )
        version = _timestamp(row.created_at) if row else None
    elif source.kind == "agent_tool_call":
        row = _integer_owned_source(
            db,
            source_id=source_id,
            model=AgentToolCall,
            owner_filter=AgentToolCall.user_id == user_pk,
        )
        version = _timestamp(row.completed_at or row.started_at) if row else None
    elif source.kind == "process_event":
        row = (
            db.query(ProcessEvent)
            .join(
                JobOpportunity,
                JobOpportunity.id == ProcessEvent.job_opportunity_id,
            )
            .filter(ProcessEvent.id == source_id, JobOpportunity.user_id == user_pk)
            .one_or_none()
        )
        version = _timestamp(row.created_at) if row else None
    elif source.kind == "artifact_version":
        row = (
            db.query(ArtifactVersion)
            .join(Artifact, Artifact.id == ArtifactVersion.artifact_id)
            .filter(ArtifactVersion.id == source_id, Artifact.user_id == user_pk)
            .one_or_none()
        )
        version = f"version:{row.version_no}" if row else None
    else:
        raise AbilitySignalSourceError(
            f"Unsupported AbilitySignal source {source.kind}"
        )
    if row is None:
        raise AbilitySignalSourceError(
            f"Owned {source.kind} source {source_id} does not exist"
        )
    return version


def _integer_owned_source(
    db: Session,
    *,
    source_id: str,
    model,
    owner_filter,
    owner_join=None,
    owner_join_on=None,
):
    try:
        integer_id = int(source_id)
    except ValueError as exc:
        raise AbilitySignalSourceError(
            f"Invalid numeric source id {source_id}"
        ) from exc
    query = db.query(model)
    if owner_join is not None:
        query = query.join(owner_join, owner_join_on)
    return query.filter(model.id == integer_id, owner_filter).one_or_none()


def _signal_view(db: Session, row: AbilitySignal) -> AbilitySignalView:
    row = (
        db.query(AbilitySignal)
        .populate_existing()
        .filter(AbilitySignal.id == row.id)
        .one()
    )
    sources = (
        db.query(AbilitySignalSourceRef)
        .filter(AbilitySignalSourceRef.ability_signal_id == row.id)
        .order_by(AbilitySignalSourceRef.created_at.asc())
        .all()
    )
    return AbilitySignalView(
        **{
            column: getattr(row, column)
            for column in (
                "id",
                "user_id",
                "topic",
                "signal_type",
                "level",
                "score",
                "summary",
                "confidence",
                "limitations",
                "scope_kind",
                "scope_ref_id",
                "formed_at",
                "rubric_version",
                "status",
                "status_reason",
                "supersedes_signal_id",
                "version",
                "created_at",
                "updated_at",
                "status_changed_at",
            )
        },
        sources=[AbilitySignalSourceView.model_validate(source) for source in sources],
    )


def _timestamp(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


__all__ = [
    "AbilitySignalConflictError",
    "AbilitySignalError",
    "AbilitySignalNotFoundError",
    "AbilitySignalOwnershipError",
    "AbilitySignalSourceError",
    "create_ability_signal",
    "dispute_ability_signal",
    "get_ability_signal",
    "invalidate_ability_signal",
    "invalidate_ability_signals_for_interview_delete",
    "invalidate_ability_signals_for_interview_reanalysis",
    "list_ability_signals",
    "project_interview_ability_signals",
]
