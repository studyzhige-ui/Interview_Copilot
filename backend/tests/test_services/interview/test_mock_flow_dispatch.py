"""dispatch_review rollback semantics (MOCK-1).

The finish path and the retry path roll back to DIFFERENT statuses on a
broker failure — finish revives the runtime (user hits 结束面试 again),
retry must NOT (the interview is over; an ACTIVE runtime would resurface
a finished interview in the resume banner).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

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


def _make_run(db, *, status: str, runtime_status: str):
    record = interview_record_service.create_for_mock(
        user_id="alice",
        title="模拟面试",
        db=db,
    )
    record.status = status
    db.add(record)
    runtime = mock_runtime_service.create_runtime(
        db,
        user_id="alice",
        interview_record_id=record.id,
        plan=[{"key": "self_intro", "title": "自我介绍"}],
    )
    if runtime_status != mock_runtime_service.ACTIVE_STATUS:
        mock_runtime_service.set_status(db, runtime, runtime_status)
    db.commit()
    return record, runtime


def _broker_down(monkeypatch):
    def _raise(*a, **k):
        raise ConnectionError("broker down")

    monkeypatch.setattr(
        mock_flow,
        "process_interview_analysis",
        SimpleNamespace(delay=_raise),
    )


def test_finish_dispatch_failure_rolls_back_to_in_progress_and_reactivates(
    db_session,
    monkeypatch,
):
    # Finish endpoint flips both to processing_review before dispatching.
    record, runtime = _make_run(
        db_session,
        status=STATUS_PROCESSING_REVIEW,
        runtime_status="processing_review",
    )
    _broker_down(monkeypatch)

    with pytest.raises(ConnectionError):
        mock_flow.dispatch_review(db_session, record.id)

    db_session.refresh(record)
    db_session.refresh(runtime)
    assert record.status == STATUS_MOCK_IN_PROGRESS
    assert runtime.status == mock_runtime_service.ACTIVE_STATUS  # resumable


def test_retry_dispatch_failure_rolls_back_to_review_failed_only(
    db_session,
    monkeypatch,
):
    record, runtime = _make_run(
        db_session,
        status=STATUS_PROCESSING_REVIEW,
        runtime_status="processing_review",
    )
    _broker_down(monkeypatch)

    with pytest.raises(ConnectionError):
        mock_flow.dispatch_review(
            db_session,
            record.id,
            rollback_status=STATUS_REVIEW_FAILED,
        )

    db_session.refresh(record)
    db_session.refresh(runtime)
    assert record.status == STATUS_REVIEW_FAILED
    # The runtime must stay non-active — no resurrected resume banner.
    assert runtime.status != mock_runtime_service.ACTIVE_STATUS


def test_dispatch_success_stamps_task_id_and_processing_review(db_session, monkeypatch):
    record, _ = _make_run(
        db_session,
        status=STATUS_MOCK_IN_PROGRESS,
        runtime_status="in_progress",
    )
    monkeypatch.setattr(
        mock_flow,
        "process_interview_analysis",
        SimpleNamespace(delay=lambda *a, **k: SimpleNamespace(id="celery-task-1")),
    )

    task = mock_flow.dispatch_review(db_session, record.id)

    db_session.refresh(record)
    assert task.id == "celery-task-1"
    assert record.status == STATUS_PROCESSING_REVIEW
    assert record.celery_task_id == "celery-task-1"
