"""Tests for mock_interview_runtime lifecycle (CONVERSATION-MOCK)."""
from __future__ import annotations

import json

import pytest

from app.services.interview import mock_runtime_service as svc


@pytest.fixture(autouse=True)
def _seed_users(db_session):
    """The runtime now keys on users.id — the service resolves the username, so
    a matching ``users`` row must exist."""
    from app.models.user import User

    db_session.add_all([
        User(username="alice", hashed_password="x"),
        User(username="bob", hashed_password="x"),
    ])
    db_session.flush()


def _create(db, user_id="alice", record_id="ir_1", **kw):
    return svc.create_runtime(
        db, user_id=user_id, interview_record_id=record_id,
        plan=[{"key": "self_intro", "title": "自我介绍"}], **kw,
    )


def test_create_runtime_is_in_progress_with_plan(db_session):
    r = _create(db_session)
    assert r.id.startswith("mir_")
    assert r.status == "in_progress"
    assert r.plan_template_key == "general"
    plan = json.loads(r.plan_json)
    assert plan[0]["key"] == "self_intro"


def test_get_active_runtime_returns_in_progress(db_session):
    r = _create(db_session)
    got = svc.get_active_runtime(db_session, user_id="alice")
    assert got is not None and got.id == r.id


def test_get_active_runtime_none_after_finish(db_session):
    r = _create(db_session)
    svc.set_status(db_session, r, "completed")
    assert svc.get_active_runtime(db_session, user_id="alice") is None


def test_get_active_runtime_user_scoped(db_session):
    _create(db_session, user_id="alice")
    assert svc.get_active_runtime(db_session, user_id="bob") is None


def test_advance_runtime_updates_position(db_session):
    r = _create(db_session)
    before = r.last_activity_at
    svc.advance_runtime(
        db_session, r,
        current_stage_key="role_technical_assessment", stage_index=2,
        current_question_text="讲讲你对索引的理解", current_question_message_id=42,
    )
    assert r.current_stage_key == "role_technical_assessment"
    assert r.stage_index == 2
    assert r.current_question_text == "讲讲你对索引的理解"
    assert r.current_question_message_id == 42
    # advance bumps last_activity_at — the column "resume most-recent" orders by.
    assert r.last_activity_at >= before


def test_set_status_stamps_ended_at_on_terminal(db_session):
    r = _create(db_session)
    assert r.ended_at is None
    svc.set_status(db_session, r, "processing_review")
    assert r.ended_at is not None
    assert r.status == "processing_review"


def test_set_status_stamps_ended_at_only_once(db_session):
    """ended_at = interview-end time, not review-finish time — stamped once."""
    r = _create(db_session)
    svc.set_status(db_session, r, "processing_review")
    first_ended = r.ended_at
    svc.set_status(db_session, r, "completed")
    assert r.status == "completed"
    assert r.ended_at == first_ended  # not re-stamped on the later transition


def test_delete_runtime_removes_it(db_session):
    r = _create(db_session)
    svc.delete_runtime(db_session, r)
    assert svc.get_runtime_for_record(db_session, interview_record_id="ir_1") is None
