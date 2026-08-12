"""Review dispatch owns the handoff from live runtime to durable review."""

from __future__ import annotations

import pytest
from app.models.chat import Conversation
from app.services.interview import mock_flow, mock_runtime_service
from app.services.interview.interview_record_service import (
    STATUS_MOCK_IN_PROGRESS,
    STATUS_PROCESSING_REVIEW,
    STATUS_REVIEW_FAILED,
    interview_record_service,
)


@pytest.fixture(autouse=True)
def _seed_user(db_session):
    from app.models.user import User

    db_session.add(User(username="alice", hashed_password="x"))
    db_session.flush()


def _make_run(db, *, status: str, with_runtime: bool = True):
    from app.models.user import User

    record = interview_record_service.create_for_mock(
        user_id="alice",
        title="模拟面试",
        db=db,
    )
    record.status = status
    db.add(record)
    runtime = None
    if with_runtime:
        user_pk = db.query(User.id).filter(User.username == "alice").scalar()
        conversation = Conversation(
            id=f"conv_{record.id}",
            user_id=user_pk,
            title="模拟面试",
            type="mock_interview",
            mode="chat",
            subject_type="interview_record",
            subject_id=record.id,
        )
        db.add(conversation)
        db.flush()
        opening = mock_flow.append_message(
            db,
            conversation.id,
            "assistant",
            "请做个自我介绍。",
        )
        runtime = mock_runtime_service.create_runtime(
            db,
            user_id="alice",
            interview_record_id=record.id,
            conversation_id=conversation.id,
            plan=[{"key": "self_intro", "title": "自我介绍"}],
            interviewer_style="professional",
            target_question_count=20,
            current_stage_key="self_intro",
            current_question_message_id=opening.id,
        )
    db.commit()
    return record, runtime


def _broker_down(monkeypatch):
    def _raise(*_args, **_kwargs):
        raise ConnectionError("broker down")

    monkeypatch.setattr(mock_flow, "dispatch_mock_interview_review", _raise)


def test_finish_dispatch_failure_restores_record_and_keeps_runtime(
    db_session, monkeypatch
):
    record, runtime = _make_run(db_session, status=STATUS_PROCESSING_REVIEW)
    _broker_down(monkeypatch)

    with pytest.raises(ConnectionError):
        mock_flow.dispatch_review(
            db_session,
            record.id,
            delete_live_runtime=True,
        )

    db_session.refresh(record)
    assert record.status == STATUS_MOCK_IN_PROGRESS
    assert (
        mock_runtime_service.get_runtime_for_record(
            db_session, interview_record_id=record.id
        )
        is runtime
    )


def test_retry_dispatch_failure_restores_review_failed_without_runtime(
    db_session, monkeypatch
):
    record, _ = _make_run(
        db_session,
        status=STATUS_PROCESSING_REVIEW,
        with_runtime=False,
    )
    _broker_down(monkeypatch)

    with pytest.raises(ConnectionError):
        mock_flow.dispatch_review(
            db_session,
            record.id,
            rollback_status=STATUS_REVIEW_FAILED,
        )

    db_session.refresh(record)
    assert record.status == STATUS_REVIEW_FAILED
    assert (
        mock_runtime_service.get_runtime_for_record(
            db_session, interview_record_id=record.id
        )
        is None
    )


def test_dispatch_success_stamps_task_id_and_deletes_runtime(db_session, monkeypatch):
    record, _ = _make_run(db_session, status=STATUS_PROCESSING_REVIEW)
    monkeypatch.setattr(
        mock_flow,
        "dispatch_mock_interview_review",
        lambda *_args, **_kwargs: type("Task", (), {"id": "celery-task-1"})(),
    )

    task = mock_flow.dispatch_review(
        db_session,
        record.id,
        delete_live_runtime=True,
    )

    db_session.refresh(record)
    assert task.id == "celery-task-1"
    assert record.status == STATUS_PROCESSING_REVIEW
    assert record.celery_task_id == "celery-task-1"
    assert (
        mock_runtime_service.get_runtime_for_record(
            db_session, interview_record_id=record.id
        )
        is None
    )
