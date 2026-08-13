from __future__ import annotations

import pytest

from app.models.chat import Conversation, ConversationMessage
from app.models.interview_record import InterviewRecord
from app.models.user import User
from app.schemas.personalization import CopilotPreferenceUpdate, ScopedGuidanceUpdate
from app.services import personalization_service


class _SessionLease:
    def __init__(self, db):
        self.db = db

    def __enter__(self):
        return self.db

    def __exit__(self, *_args):
        return False


def _seed(db_session):
    user = User(username="preference-user", hashed_password="x")
    other = User(username="preference-other", hashed_password="x")
    db_session.add_all([user, other])
    db_session.flush()
    record = InterviewRecord(user_id=user.id, source="upload", title="onsite")
    db_session.add(record)
    db_session.flush()
    conversation = Conversation(
        id="preference-conversation",
        user_id=user.id,
        type="debrief",
        subject_type="interview_record",
        subject_id=record.id,
    )
    other_conversation = Conversation(
        id="other-conversation",
        user_id=other.id,
        type="general",
    )
    db_session.add_all([conversation, other_conversation])
    db_session.flush()
    source = ConversationMessage(
        conversation_id=conversation.id,
        seq=1,
        role="User",
        content="这个复盘对话里请先给结论。",
    )
    foreign_source = ConversationMessage(
        conversation_id=other_conversation.id,
        seq=1,
        role="User",
        content="foreign",
    )
    db_session.add_all([source, foreign_source])
    db_session.flush()
    return user, record, conversation, source, foreign_source


def test_three_guidance_lifetimes_keep_real_owners_and_resolve_broad_to_specific(
    db_session,
    monkeypatch,
):
    user, record, conversation, source, _ = _seed(db_session)

    global_view = personalization_service.replace_copilot_preference(
        db_session,
        user_pk=user.id,
        command=CopilotPreferenceUpdate(
            expected_version=0,
            instructions=["默认使用中文", "先给结论"],
        ),
    )
    conversation_view = personalization_service.update_conversation_guidance(
        db_session,
        user_pk=user.id,
        conversation_id=conversation.id,
        command=ScopedGuidanceUpdate(
            expected_version=0,
            guidance="本对话只讨论系统设计表达。",
            source_message_id=source.id,
        ),
    )
    debrief_view = personalization_service.update_debrief_guidance(
        db_session,
        user_pk=user.id,
        interview_record_id=record.id,
        command=ScopedGuidanceUpdate(
            expected_version=0,
            guidance="本次复盘优先分析沟通结构。",
        ),
    )
    monkeypatch.setattr(
        personalization_service,
        "SessionLocal",
        lambda: _SessionLease(db_session),
    )

    rendered = personalization_service.resolve_guidance_projection(
        conversation_id=conversation.id,
        user_pk=user.id,
    )

    assert global_view.version == 1
    assert conversation_view.source_message_id == source.id
    assert debrief_view.owner_id == record.id
    positions = [
        rendered.index("[Global CopilotPreference]"),
        rendered.index("[Current Debrief Guidance]"),
        rendered.index("[Current Conversation Guidance]"),
    ]
    assert positions == sorted(positions)
    assert "never grant Tool permission" in rendered


def test_guidance_cas_and_source_owner_fail_closed(db_session):
    user, _record, conversation, _source, foreign_source = _seed(db_session)

    with pytest.raises(personalization_service.PersonalizationConflictError):
        personalization_service.update_conversation_guidance(
            db_session,
            user_pk=user.id,
            conversation_id=conversation.id,
            command=ScopedGuidanceUpdate(
                expected_version=0,
                guidance="use a foreign source",
                source_message_id=foreign_source.id,
            ),
        )

    first = personalization_service.replace_copilot_preference(
        db_session,
        user_pk=user.id,
        command=CopilotPreferenceUpdate(
            expected_version=0,
            instructions=[" concise ", "concise"],
        ),
    )
    assert first.instructions == ["concise"]
    with pytest.raises(personalization_service.PersonalizationConflictError):
        personalization_service.replace_copilot_preference(
            db_session,
            user_pk=user.id,
            command=CopilotPreferenceUpdate(
                expected_version=0,
                instructions=["verbose"],
            ),
        )


def test_clearing_guidance_changes_only_that_owner(db_session):
    user, record, conversation, source, _ = _seed(db_session)
    personalization_service.replace_copilot_preference(
        db_session,
        user_pk=user.id,
        command=CopilotPreferenceUpdate(
            expected_version=0,
            instructions=["default concise"],
        ),
    )
    personalization_service.update_conversation_guidance(
        db_session,
        user_pk=user.id,
        conversation_id=conversation.id,
        command=ScopedGuidanceUpdate(
            expected_version=0,
            guidance="local",
            source_message_id=source.id,
        ),
    )

    cleared = personalization_service.update_conversation_guidance(
        db_session,
        user_pk=user.id,
        conversation_id=conversation.id,
        command=ScopedGuidanceUpdate(expected_version=1, guidance=None),
    )

    assert cleared.guidance is None
    assert cleared.version == 2
    assert personalization_service.get_copilot_preference(
        db_session, user_pk=user.id
    ).instructions == ["default concise"]
    assert (
        personalization_service.get_debrief_guidance(
            db_session,
            user_pk=user.id,
            interview_record_id=record.id,
        ).version
        == 0
    )
