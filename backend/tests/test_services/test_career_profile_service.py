from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from app.models.career_profile import CareerProfile
from app.models.chat import Conversation, ConversationMessage
from app.models.resume import Resume
from app.models.user import User
from app.schemas.career_profile import (
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
    reject_profile_draft_change,
    upsert_personal_fact,
    upsert_profile_direction,
)


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
    resume = Resume(user_id=user.id, title="Imported resume")
    db_session.add(resume)
    db_session.flush()

    draft = create_profile_draft_change(
        db_session,
        user_pk=user.id,
        draft=CareerProfileDraftInput(
            source_kind="resume",
            source_id=resume.id,
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
