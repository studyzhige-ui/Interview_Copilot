from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from app.db.types import utc_now
from app.models.ability_signal import AbilitySignal
from app.models.career_profile import CareerProfile
from app.models.interview_qa import InterviewQA
from app.models.interview_record import InterviewRecord
from app.models.user import User
from app.schemas.ability_signal import (
    AbilityScopeInput,
    AbilitySignalCreateInput,
    AbilitySourceRefInput,
)
from app.services.ability_signal_service import (
    AbilitySignalConflictError,
    AbilitySignalSourceError,
    create_ability_signal,
    dispute_ability_signal,
    invalidate_ability_signal,
    invalidate_ability_signals_for_interview_reanalysis,
    project_interview_ability_signals,
)
from app.services.career_profile_service import ensure_career_profile


def _user(db_session, prefix: str = "ability") -> User:
    user = User(
        username=f"{prefix}-{uuid.uuid4().hex}",
        hashed_password="test-hash",
    )
    db_session.add(user)
    db_session.flush()
    return user


def _interview_sources(db_session, user: User):
    record = InterviewRecord(
        user_id=user.id,
        source="mock",
        title="Backend mock",
        status="review_ready",
    )
    db_session.add(record)
    db_session.flush()
    qa = InterviewQA(
        record_id=record.id,
        order_idx=0,
        question="How do transactions work?",
        answer="With atomicity and isolation.",
        score=7.5,
        analyzed_at=utc_now(),
    )
    db_session.add(qa)
    db_session.flush()
    return record, qa


def _assessment(record, qa, *, summary="Strong transaction fundamentals"):
    return AbilitySignalCreateInput(
        topic="Database transactions",
        signal_type="knowledge_topic",
        level="stable",
        score=7.5,
        summary=summary,
        confidence=0.78,
        limitations="Based on one mock interview; production depth untested.",
        scope=AbilityScopeInput(kind="interview_record", ref_id=record.id),
        formed_at=utc_now(),
        rubric_version="interview-rubric-v1",
        sources=[
            AbilitySourceRefInput(kind="interview_record", source_id=record.id),
            AbilitySourceRefInput(kind="interview_qa", source_id=qa.id),
        ],
    )


def test_signal_requires_real_owned_sources_and_does_not_write_profile(db_session):
    user = _user(db_session)
    profile = ensure_career_profile(db_session, user_pk=user.id)
    record, qa = _interview_sources(db_session, user)

    view = create_ability_signal(
        db_session,
        user_pk=user.id,
        assessment=_assessment(record, qa),
    )

    assert view.status == "active"
    assert view.confidence == 0.78
    assert view.scope_kind == "interview_record"
    assert {(source.source_kind, source.source_id) for source in view.sources} == {
        ("interview_record", record.id),
        ("interview_qa", qa.id),
    }
    assert all(source.source_version for source in view.sources)

    persisted_profile = db_session.get(CareerProfile, profile.id)
    assert persisted_profile.personal_facts_json == []
    assert persisted_profile.version == 1


def test_signal_rejects_foreign_or_duplicate_sources(db_session):
    user = _user(db_session)
    other = _user(db_session, "other-ability")
    foreign_record, foreign_qa = _interview_sources(db_session, other)

    with pytest.raises(AbilitySignalSourceError):
        create_ability_signal(
            db_session,
            user_pk=user.id,
            assessment=_assessment(foreign_record, foreign_qa),
        )

    owned_record, owned_qa = _interview_sources(db_session, user)
    assessment = _assessment(owned_record, owned_qa)
    assessment.sources.append(assessment.sources[0])
    with pytest.raises(AbilitySignalSourceError, match="Duplicate"):
        create_ability_signal(
            db_session,
            user_pk=user.id,
            assessment=assessment,
        )


def test_dispute_invalidate_and_version_cas(db_session):
    user = _user(db_session)
    record, qa = _interview_sources(db_session, user)
    signal = create_ability_signal(
        db_session,
        user_pk=user.id,
        assessment=_assessment(record, qa),
    )

    disputed = dispute_ability_signal(
        db_session,
        user_pk=user.id,
        signal_id=signal.id,
        expected_version=1,
        reason="The selected QA was not representative.",
    )
    assert disputed.status == "disputed"
    assert disputed.version == 2

    with pytest.raises(AbilitySignalConflictError):
        dispute_ability_signal(
            db_session,
            user_pk=user.id,
            signal_id=signal.id,
            expected_version=1,
            reason="stale replay",
        )

    invalidated = invalidate_ability_signal(
        db_session,
        user_pk=user.id,
        signal_id=signal.id,
        expected_version=2,
        reason="Source analysis was withdrawn.",
    )
    assert invalidated.status == "invalidated"
    assert invalidated.version == 3


def test_revision_creates_new_signal_and_supersedes_old_without_rewrite(db_session):
    user = _user(db_session)
    record, qa = _interview_sources(db_session, user)
    old = create_ability_signal(
        db_session,
        user_pk=user.id,
        assessment=_assessment(record, qa, summary="Initial inference"),
    )

    revised = create_ability_signal(
        db_session,
        user_pk=user.id,
        assessment=_assessment(record, qa, summary="Recomputed inference"),
        supersedes_signal_id=old.id,
        expected_superseded_version=1,
    )

    old_row = db_session.get(AbilitySignal, old.id)
    assert old_row.status == "superseded"
    assert old_row.summary == "Initial inference"
    assert old_row.version == 2
    assert revised.status == "active"
    assert revised.summary == "Recomputed inference"
    assert revised.supersedes_signal_id == old.id


def test_unknown_source_kind_and_missing_uncertainty_are_rejected():
    with pytest.raises(ValidationError):
        AbilitySourceRefInput(kind="evidence", source_id="free-text")  # type: ignore[arg-type]

    with pytest.raises(ValidationError):
        AbilitySignalCreateInput(
            topic="Communication",
            signal_type="communication",
            summary="Too certain",
            formed_at=utc_now(),
            sources=[
                AbilitySourceRefInput(
                    kind="interview_record",
                    source_id="ir_missing",
                )
            ],
        )


def test_interview_analysis_projects_recomputes_and_invalidates_signals(db_session):
    import json

    user = _user(db_session)
    record, qa = _interview_sources(db_session, user)
    record.analysis_json = json.dumps(
        {
            "schema_version": 3,
            "skill_radar": {"technical_depth": 7.5, "communication": 8.0},
        }
    )
    record.analysis_schema_version = 3
    db_session.add(record)
    db_session.flush()

    first = project_interview_ability_signals(
        db_session,
        user_pk=user.id,
        interview_record_id=record.id,
    )
    replay = project_interview_ability_signals(
        db_session,
        user_pk=user.id,
        interview_record_id=record.id,
    )
    assert {signal.id for signal in replay} == {signal.id for signal in first}
    assert {signal.topic for signal in first} == {
        "technical_depth",
        "communication",
    }
    assert all(signal.scope_ref_id == record.id for signal in first)
    assert all(len(signal.sources) == 2 for signal in first)

    record.analysis_json = json.dumps(
        {"schema_version": 3, "skill_radar": {"technical_depth": 8.5}}
    )
    db_session.add(record)
    db_session.flush()
    recomputed = project_interview_ability_signals(
        db_session,
        user_pk=user.id,
        interview_record_id=record.id,
        force_new_generation=True,
    )
    assert len(recomputed) == 1
    assert recomputed[0].score == 8.5
    assert recomputed[0].supersedes_signal_id is not None
    live = (
        db_session.query(AbilitySignal)
        .filter(AbilitySignal.user_id == user.id, AbilitySignal.status == "active")
        .all()
    )
    assert [row.topic for row in live] == ["technical_depth"]

    assert (
        invalidate_ability_signals_for_interview_reanalysis(
            db_session,
            user_pk=user.id,
            interview_record_id=record.id,
        )
        == 1
    )
    assert (
        db_session.query(AbilitySignal)
        .filter(AbilitySignal.user_id == user.id, AbilitySignal.status == "active")
        .count()
        == 0
    )
