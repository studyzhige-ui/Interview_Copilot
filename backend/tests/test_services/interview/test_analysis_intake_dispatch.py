"""INF-2: a broker failure at dispatch time must park the record in
``failed`` (user-visible, terminal) instead of leaving a zombie
``pending`` row no worker will ever pick up — and still re-raise so the
API returns an error."""

from __future__ import annotations

import pytest
from app.models.file_asset import FileAsset
from app.services.interview import analysis_intake
from app.services.interview.interview_record_service import (
    STATUS_FAILED,
    STATUS_PENDING,
)


@pytest.fixture(autouse=True)
def _seed_user(db_session):
    from app.models.user import User

    db_session.add(User(username="alice", hashed_password="x"))
    db_session.flush()


def _upload(db):
    from app.models.user import User

    pk = db.query(User.id).filter(User.username == "alice").scalar()
    asset = FileAsset(
        id="fa_audio_1",
        user_id=pk,
        purpose="interview_audio",
        original_filename="interview.mp3",
        object_key="k/interview.mp3",
        storage_uri="local://k/interview.mp3",
        upload_status="uploaded",
    )
    db.add(asset)
    db.commit()
    return asset


def _resume_ctx():
    return analysis_intake.ResumeContext(
        resume_id=None,
        resume_file_asset_id=None,
        resume_source=None,
        resume_title_snapshot=None,
        resume_text="",
    )


def test_dispatch_failure_parks_record_failed_and_reraises(db_session, monkeypatch):
    from app.services.interview import interview_record_service as irs_module

    # set_status opens its own SessionLocal — point it at the test session.
    class _NoClose:
        def __init__(self, inner):
            self._inner = inner

        def __getattr__(self, name):
            return getattr(self._inner, name)

        def close(self):
            self._inner.commit()

    monkeypatch.setattr(irs_module, "SessionLocal", lambda: _NoClose(db_session))

    def _raise(*a, **k):
        raise ConnectionError("broker down")

    monkeypatch.setattr(
        analysis_intake,
        "dispatch_interview_analysis",
        _raise,
    )

    with pytest.raises(ConnectionError):
        analysis_intake.create_record_and_dispatch(
            db_session,
            user_id="alice",
            upload=_upload(db_session),
            resume_ctx=_resume_ctx(),
            jd_text="",
            jd_file_asset_id=None,
            language="zh",
        )

    from app.models.interview_record import InterviewRecord

    record = db_session.query(InterviewRecord).one()
    assert record.status == STATUS_FAILED
    assert record.error_message and "派发失败" in record.error_message


def test_dispatch_success_leaves_record_pending_with_task_id(db_session, monkeypatch):
    from app.services.interview import interview_record_service as irs_module

    class _NoClose:
        def __init__(self, inner):
            self._inner = inner

        def __getattr__(self, name):
            return getattr(self._inner, name)

        def close(self):
            self._inner.commit()

    monkeypatch.setattr(irs_module, "SessionLocal", lambda: _NoClose(db_session))
    monkeypatch.setattr(
        analysis_intake,
        "dispatch_interview_analysis",
        lambda *a, **k: type("Task", (), {"id": "celery-task-9"})(),
    )

    record, task = analysis_intake.create_record_and_dispatch(
        db_session,
        user_id="alice",
        upload=_upload(db_session),
        resume_ctx=_resume_ctx(),
        jd_text="",
        jd_file_asset_id=None,
        language="zh",
    )

    db_session.refresh(record)
    assert task.id == "celery-task-9"
    assert record.status == STATUS_PENDING
    assert record.celery_task_id == "celery-task-9"
