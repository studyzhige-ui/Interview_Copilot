from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from app.models.career_profile import CareerProfile
from app.models.chat import Conversation, ConversationMessage
from app.models.user import User
from app.schemas.career_profile import (
    CareerProfileCandidateBatchResolutionInput,
    CareerProfileCandidateDecisionInput,
    CareerProfileDraftInput,
    ConfirmationInput,
    DirectionDraftChange,
    DirectionInput,
    EducationFactInput,
    FactDraftChange,
    SkillFactInput,
)
from app.services.career_profile_service import (
    CareerProfileConflictError,
    CareerProfileSourceError,
    accept_profile_draft_change,
    create_profile_draft_change,
    ensure_career_profile,
    get_career_profile,
    profile_draft_view,
    reject_profile_draft_change,
    resolve_profile_candidate_items,
    upsert_personal_fact,
    upsert_profile_direction,
)
from app.services.resume import resume_artifact_service


def _user(db_session, prefix: str = "profile") -> User:
    user = User(
        username=f"{prefix}-{uuid.uuid4().hex}",
        hashed_password="test-hash",
    )
    db_session.add(user)
    db_session.flush()
    return user


def _owned_message(db_session, user: User, content: str = "I confirm this"):
    conversation = Conversation(user_id=user.id)
    db_session.add(conversation)
    db_session.flush()
    message = ConversationMessage(
        conversation_id=conversation.id,
        seq=1,
        role="user",
        content=content,
    )
    db_session.add(message)
    db_session.flush()
    return message


def _resume_version(db_session, user: User, *, suffix: str):
    return resume_artifact_service.create_resume_artifact(
        db_session,
        user_pk=user.id,
        operation_key=f"profile-source-{suffix}",
        title="Imported resume",
        file_asset_id=None,
        raw_text="Canonical resume source",
        make_default=True,
    ).current_version


def test_profile_is_single_owner_for_confirmed_facts_and_multiple_directions(
    db_session,
):
    user = _user(db_session)
    profile = ensure_career_profile(db_session, user_pk=user.id)

    view = upsert_personal_fact(
        db_session,
        user_pk=user.id,
        expected_profile_version=1,
        fact=EducationFactInput(
            kind="education",
            institution="Example University",
            degree="BSc",
        ),
        confirmation=ConfirmationInput(kind="user_edit"),
    )
    first_fact_id = view.personal_facts[0].id
    assert view.version == 2
    assert view.personal_facts[0].confirmed_source_kind == "user_edit"

    view = upsert_profile_direction(
        db_session,
        user_pk=user.id,
        expected_profile_version=2,
        direction=DirectionInput(
            label="Backend",
            lifecycle="active",
            priority=10,
            criteria={"role_keywords": ["backend engineer"]},
        ),
        confirmation=ConfirmationInput(kind="user_edit"),
    )
    view = upsert_profile_direction(
        db_session,
        user_pk=user.id,
        expected_profile_version=3,
        direction=DirectionInput(
            label="Platform",
            lifecycle="exploring",
            priority=10,
            criteria={"technologies": ["Kubernetes"]},
        ),
        confirmation=ConfirmationInput(kind="user_edit"),
    )

    assert view.id == profile.id
    assert view.version == 4
    assert {direction.label for direction in view.directions} == {
        "Backend",
        "Platform",
    }
    assert view.personal_facts[0].id == first_fact_id

    duplicate_root = CareerProfile(user_id=user.id, personal_facts_json=[], version=1)
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.add(duplicate_root)
            db_session.flush()


def test_profile_writes_are_owner_checked_and_versioned(db_session):
    owner = _user(db_session)
    other = _user(db_session, "other")
    ensure_career_profile(db_session, user_pk=owner.id)
    ensure_career_profile(db_session, user_pk=other.id)
    foreign_message = _owned_message(db_session, other)

    with pytest.raises(CareerProfileSourceError):
        upsert_personal_fact(
            db_session,
            user_pk=owner.id,
            expected_profile_version=1,
            fact=SkillFactInput(kind="skill", name="Python"),
            confirmation=ConfirmationInput(
                kind="conversation_message",
                source_message_id=foreign_message.id,
            ),
        )

    view = upsert_personal_fact(
        db_session,
        user_pk=owner.id,
        expected_profile_version=1,
        fact=SkillFactInput(kind="skill", name="Python"),
        confirmation=ConfirmationInput(kind="user_edit"),
    )
    assert view.version == 2

    with pytest.raises(CareerProfileConflictError):
        upsert_personal_fact(
            db_session,
            user_pk=owner.id,
            expected_profile_version=1,
            fact=SkillFactInput(kind="skill", name="Go"),
            confirmation=ConfirmationInput(kind="user_edit"),
        )


def test_durable_draft_is_not_canonical_until_explicit_acceptance(db_session):
    user = _user(db_session)
    ensure_career_profile(db_session, user_pk=user.id)
    resume_version = _resume_version(db_session, user, suffix="durable")

    draft = create_profile_draft_change(
        db_session,
        user_pk=user.id,
        draft=CareerProfileDraftInput(
            source_kind="artifact_version",
            source_id=resume_version.id,
            proposed_facts=[
                FactDraftChange(
                    operation="upsert",
                    fact=SkillFactInput(kind="skill", name="Rust"),
                )
            ],
            proposed_directions=[
                DirectionDraftChange(
                    operation="upsert",
                    direction=DirectionInput(
                        label="Systems",
                        criteria={"role_keywords": ["systems engineer"]},
                    ),
                )
            ],
        ),
    )

    before = get_career_profile(db_session, user_pk=user.id)
    assert before.version == 1
    assert before.personal_facts == []
    assert before.directions == []
    assert draft.status == "pending"

    accepted = accept_profile_draft_change(
        db_session,
        user_pk=user.id,
        draft_id=draft.id,
        expected_draft_version=1,
        expected_profile_version=1,
    )
    assert accepted.version == 2
    assert accepted.personal_facts[0].value.name == "Rust"
    assert accepted.personal_facts[0].confirmed_source_kind == "draft_acceptance"
    assert accepted.directions[0].label == "Systems"

    db_session.refresh(draft)
    assert draft.status == "accepted"
    assert draft.version == 2


def test_rejected_or_stale_draft_never_changes_canonical_profile(db_session):
    user = _user(db_session)
    ensure_career_profile(db_session, user_pk=user.id)
    message = _owned_message(db_session, user)
    draft = create_profile_draft_change(
        db_session,
        user_pk=user.id,
        draft=CareerProfileDraftInput(
            source_kind="conversation_message",
            source_id=str(message.id),
            proposed_facts=[
                FactDraftChange(
                    operation="upsert",
                    fact=SkillFactInput(kind="skill", name="SQL"),
                )
            ],
        ),
    )
    upsert_personal_fact(
        db_session,
        user_pk=user.id,
        expected_profile_version=1,
        fact=SkillFactInput(kind="skill", name="Python"),
        confirmation=ConfirmationInput(kind="user_edit"),
    )

    with pytest.raises(CareerProfileConflictError, match="review it again"):
        accept_profile_draft_change(
            db_session,
            user_pk=user.id,
            draft_id=draft.id,
            expected_draft_version=1,
            expected_profile_version=2,
        )

    rejected = reject_profile_draft_change(
        db_session,
        user_pk=user.id,
        draft_id=draft.id,
        expected_draft_version=1,
        resolution_note="outdated",
    )
    assert rejected.status == "rejected"
    view = get_career_profile(db_session, user_pk=user.id)
    assert [fact.value.name for fact in view.personal_facts] == ["Python"]


def test_temporary_search_is_not_a_profile_draft_source():
    with pytest.raises(ValidationError):
        CareerProfileDraftInput(
            source_kind="search",  # type: ignore[arg-type]
            source_id="search-1",
            proposed_facts=[
                FactDraftChange(
                    operation="upsert",
                    fact=SkillFactInput(kind="skill", name="Unconfirmed"),
                )
            ],
        )

    with pytest.raises(ValidationError):
        CareerProfileDraftInput(
            source_kind="resume",  # type: ignore[arg-type]
            source_id="rsm_retired",
            proposed_facts=[
                FactDraftChange(
                    operation="upsert",
                    fact=SkillFactInput(kind="skill", name="Unconfirmed"),
                )
            ],
        )


def test_candidate_items_highlight_conflicts_and_support_partial_resolution(
    db_session,
):
    user = _user(db_session)
    ensure_career_profile(db_session, user_pk=user.id)
    profile = upsert_personal_fact(
        db_session,
        user_pk=user.id,
        expected_profile_version=1,
        fact=SkillFactInput(kind="skill", name="Python", category="backend"),
        confirmation=ConfirmationInput(kind="user_edit"),
    )
    resume_version = _resume_version(db_session, user, suffix="conflict")
    draft = create_profile_draft_change(
        db_session,
        user_pk=user.id,
        draft=CareerProfileDraftInput(
            source_kind="artifact_version",
            source_id=resume_version.id,
            proposed_facts=[
                FactDraftChange(
                    operation="upsert",
                    fact=SkillFactInput(kind="skill", name="Python", category="data"),
                ),
                FactDraftChange(
                    operation="upsert",
                    fact=SkillFactInput(kind="skill", name="Rust"),
                ),
            ],
        ),
    )
    view = profile_draft_view(db_session, user_pk=user.id, draft_id=draft.id)
    conflict, clean = view.candidates
    assert conflict.conflict_kind == "conflict"
    assert conflict.current_value["value"]["category"] == "backend"
    assert clean.conflict_kind == "none"

    result = resolve_profile_candidate_items(
        db_session,
        user_pk=user.id,
        draft_id=draft.id,
        resolution=CareerProfileCandidateBatchResolutionInput(
            expected_draft_version=1,
            expected_profile_version=profile.version,
            decisions=[
                CareerProfileCandidateDecisionInput(
                    item_id=clean.id,
                    expected_version=clean.version,
                    decision="accept",
                )
            ],
        ),
    )
    assert result.draft.status == "pending"
    assert result.draft.version == 2
    assert {fact.value.name for fact in result.profile.personal_facts} == {
        "Python",
        "Rust",
    }
    remaining = next(
        item for item in result.draft.candidates if item.status == "pending"
    )
    assert remaining.conflict_kind == "conflict"

    accepted = accept_profile_draft_change(
        db_session,
        user_pk=user.id,
        draft_id=draft.id,
        expected_draft_version=result.draft.version,
        expected_profile_version=result.profile.version,
    )
    facts = {fact.value.name: fact for fact in accepted.personal_facts}
    assert set(facts) == {"Python", "Rust"}
    assert facts["Python"].value.category == "data"


def test_rejecting_remaining_candidates_preserves_partially_accepted_draft(
    db_session,
):
    user = _user(db_session)
    profile = ensure_career_profile(db_session, user_pk=user.id)
    resume_version = _resume_version(db_session, user, suffix="partial")
    draft = create_profile_draft_change(
        db_session,
        user_pk=user.id,
        draft=CareerProfileDraftInput(
            source_kind="artifact_version",
            source_id=resume_version.id,
            proposed_facts=[
                FactDraftChange(
                    operation="upsert",
                    fact=SkillFactInput(kind="skill", name="Python"),
                ),
                FactDraftChange(
                    operation="upsert",
                    fact=SkillFactInput(kind="skill", name="Rust"),
                ),
            ],
        ),
    )
    draft_view = profile_draft_view(db_session, user_pk=user.id, draft_id=draft.id)
    first = draft_view.candidates[0]
    partial = resolve_profile_candidate_items(
        db_session,
        user_pk=user.id,
        draft_id=draft.id,
        resolution=CareerProfileCandidateBatchResolutionInput(
            expected_draft_version=draft_view.version,
            expected_profile_version=profile.version,
            decisions=[
                CareerProfileCandidateDecisionInput(
                    item_id=first.id,
                    expected_version=first.version,
                    decision="accept",
                )
            ],
        ),
    )

    resolved = reject_profile_draft_change(
        db_session,
        user_pk=user.id,
        draft_id=draft.id,
        expected_draft_version=partial.draft.version,
        resolution_note="只保留已确认项",
    )
    assert resolved.status == "accepted"
    assert [
        fact.value.name
        for fact in get_career_profile(db_session, user_pk=user.id).personal_facts
    ] == ["Python"]
    candidate_statuses = {
        item.status
        for item in profile_draft_view(
            db_session, user_pk=user.id, draft_id=draft.id
        ).candidates
    }
    assert candidate_statuses == {"accepted", "rejected"}
