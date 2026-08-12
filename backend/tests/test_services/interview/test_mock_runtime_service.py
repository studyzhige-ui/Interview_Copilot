"""Tests for mock_interview_runtime lifecycle (CONVERSATION-MOCK)."""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError
from app.services.interview import mock_runtime_service as svc


@pytest.fixture(autouse=True)
def _seed_users(db_session):
    """The runtime now keys on users.id — the service resolves the username, so
    a matching ``users`` row must exist."""
    from app.models.user import User

    db_session.add_all(
        [
            User(username="alice", hashed_password="x"),
            User(username="bob", hashed_password="x"),
        ]
    )
    db_session.flush()


def _create(db, user_id="alice", record_id="ir_1", **kw):
    return svc.create_runtime(
        db,
        user_id=user_id,
        interview_record_id=record_id,
        conversation_id=f"conv_{record_id}",
        plan=[{"key": "self_intro", "title": "自我介绍"}],
        interviewer_style="professional",
        target_question_count=20,
        current_stage_key="self_intro",
        current_question_message_id=1,
        **kw,
    )


def test_create_runtime_is_in_progress_with_plan(db_session):
    r = _create(db_session)
    assert r.interview_record_id == "ir_1"
    assert r.conversation_id == "conv_ir_1"
    assert r.plan_json[0]["key"] == "self_intro"


def test_get_active_runtime_returns_in_progress(db_session):
    r = _create(db_session)
    got = svc.get_active_runtime(db_session, user_id="alice")
    assert got is not None and got.interview_record_id == r.interview_record_id


def test_get_active_runtime_none_after_delete(db_session):
    r = _create(db_session)
    svc.delete_runtime(db_session, r)
    assert svc.get_active_runtime(db_session, user_id="alice") is None


def test_get_active_runtime_user_scoped(db_session):
    _create(db_session, user_id="alice")
    assert svc.get_active_runtime(db_session, user_id="bob") is None


def test_database_allows_only_one_active_runtime_per_user(db_session):
    _create(db_session, user_id="alice", record_id="ir_first")
    with pytest.raises(IntegrityError):
        _create(db_session, user_id="alice", record_id="ir_second")
    db_session.rollback()


def test_advance_runtime_updates_position(db_session):
    r = _create(db_session)
    before = r.last_activity_at
    svc.advance_runtime(
        db_session,
        r,
        current_stage_key="role_technical_assessment",
        current_question_message_id=42,
    )
    assert r.current_stage_key == "role_technical_assessment"
    assert r.current_question_message_id == 42
    # advance bumps last_activity_at — the column "resume most-recent" orders by.
    assert r.last_activity_at >= before


def test_delete_runtime_removes_it(db_session):
    r = _create(db_session)
    svc.delete_runtime(db_session, r)
    assert svc.get_runtime_for_record(db_session, interview_record_id="ir_1") is None
