"""UP-2: deleting an interview record queues blob deletes for the storage
it exclusively owns (audio recording, ad-hoc JD/resume uploads) instead of
leaving 500MB orphans in MinIO forever."""
from __future__ import annotations

import pytest

from app.models.file_asset import FileAsset
from app.models.interview_record import InterviewRecord
from app.models.outbox_job import OutboxJob
from app.services.interview import record_admin


@pytest.fixture(autouse=True)
def _seed_user(db_session):
    from app.models.user import User

    db_session.add(User(username="alice", hashed_password="x"))
    db_session.flush()


def _pk(db):
    from app.models.user import User

    return db.query(User.id).filter(User.username == "alice").scalar()


def _asset(db, asset_id: str, purpose: str) -> FileAsset:
    asset = FileAsset(
        id=asset_id,
        user_id=_pk(db),
        purpose=purpose,
        original_filename=f"{asset_id}.bin",
        object_key=f"uploads/1/{asset_id}/f.bin",
        storage_uri=f"s3://b/uploads/1/{asset_id}/f.bin",
        upload_status="consumed",
    )
    db.add(asset)
    return asset


def test_delete_record_cascade_queues_owned_blob_deletes(db_session):
    _asset(db_session, "fa_audio", "interview_audio")
    _asset(db_session, "fa_jd", "jd")
    record = InterviewRecord(
        id="ir_del",
        user_id=_pk(db_session),
        source="upload",
        status="completed",
        audio_file_asset_id="fa_audio",
        jd_file_asset_id="fa_jd",
    )
    db_session.add(record)
    db_session.commit()

    record_admin.delete_record_cascade(db_session, record)

    # Record + asset rows gone; one delete_object job per blob.
    assert db_session.query(InterviewRecord).count() == 0
    assert db_session.query(FileAsset).count() == 0
    jobs = {
        j.aggregate_id
        for j in db_session.query(OutboxJob).filter(
            OutboxJob.job_type == "delete_object"
        )
    }
    assert jobs == {"fa_audio", "fa_jd"}


def test_delete_record_cascade_without_assets_is_clean(db_session):
    record = InterviewRecord(
        id="ir_plain", user_id=_pk(db_session), source="mock", status="review_ready",
    )
    db_session.add(record)
    db_session.commit()

    record_admin.delete_record_cascade(db_session, record)

    assert db_session.query(InterviewRecord).count() == 0
    assert db_session.query(OutboxJob).count() == 0


def test_delete_record_cascade_spares_assets_other_entities_reference(db_session):
    """A resume asset shared with a personal Resume entity must survive the
    record cascade — deleting it would break the FK / orphan the resume."""
    from app.models.resume import Resume

    shared = _asset(db_session, "fa_shared_resume", "resume")
    _asset(db_session, "fa_audio2", "interview_audio")
    db_session.add(Resume(
        id="res_1", user_id=_pk(db_session), file_asset_id=shared.id, title="我的简历",
    ))
    record = InterviewRecord(
        id="ir_shared",
        user_id=_pk(db_session),
        source="upload",
        status="completed",
        audio_file_asset_id="fa_audio2",
        resume_file_asset_id="fa_shared_resume",
    )
    db_session.add(record)
    db_session.commit()

    record_admin.delete_record_cascade(db_session, record)

    # Audio blob queued for deletion; the shared resume asset untouched.
    surviving = {a.id for a in db_session.query(FileAsset).all()}
    assert surviving == {"fa_shared_resume"}
    jobs = {
        j.aggregate_id
        for j in db_session.query(OutboxJob).filter(
            OutboxJob.job_type == "delete_object"
        )
    }
    assert jobs == {"fa_audio2"}


# ── ANA-7: reanalyze ─────────────────────────────────────────────────────


def _mk_record(db, rid, *, source="upload", status="failed", **kw):
    rec = InterviewRecord(
        id=rid, user_id=_pk(db), source=source, status=status, **kw,
    )
    db.add(rec)
    db.commit()
    return rec


def test_reanalyze_resets_and_dispatches(db_session, monkeypatch):
    from types import SimpleNamespace

    rec = _mk_record(
        db_session, "ir_re1", status="failed",
        analysis_json='{"overall": {}}', error_message="boom",
        debrief_summary="旧摘要", analyzed_qa_count=7,
    )
    monkeypatch.setattr(
        record_admin, "process_interview_analysis",
        SimpleNamespace(delay=lambda rid: SimpleNamespace(id="task-9")),
        raising=False,
    )
    import app.worker.tasks as wt

    monkeypatch.setattr(
        wt, "process_interview_analysis",
        SimpleNamespace(delay=lambda rid: SimpleNamespace(id="task-9")),
    )

    task = record_admin.reanalyze_record(db_session, rec)

    db_session.refresh(rec)
    assert task.id == "task-9"
    assert rec.status == "pending"
    assert rec.analysis_json is None
    assert rec.error_message is None
    assert rec.debrief_summary is None      # regenerates from the new report
    assert rec.analyzed_qa_count == 0
    assert rec.celery_task_id == "task-9"


def test_reanalyze_rejects_mock_and_inflight(db_session):
    import pytest as _pytest

    mock_rec = _mk_record(db_session, "ir_re2", source="mock", status="review_failed")
    with _pytest.raises(record_admin.ReanalyzeNotAllowed):
        record_admin.reanalyze_record(db_session, mock_rec)

    running = _mk_record(db_session, "ir_re3", status="analyzing")
    with _pytest.raises(record_admin.ReanalyzeNotAllowed):
        record_admin.reanalyze_record(db_session, running)


def test_reanalyze_dispatch_failure_rolls_back_to_failed(db_session, monkeypatch):
    from types import SimpleNamespace

    rec = _mk_record(db_session, "ir_re4", status="completed")
    import app.worker.tasks as wt

    def _raise(rid):
        raise ConnectionError("broker down")

    monkeypatch.setattr(
        wt, "process_interview_analysis", SimpleNamespace(delay=_raise),
    )
    import pytest as _pytest

    with _pytest.raises(ConnectionError):
        record_admin.reanalyze_record(db_session, rec)
    db_session.refresh(rec)
    assert rec.status == "failed"
    assert "派发失败" in (rec.error_message or "")
