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
        id="ir_plain",
        user_id=_pk(db_session),
        source="mock",
        status="review_ready",
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
    db_session.add(
        Resume(
            id="res_1",
            user_id=_pk(db_session),
            file_asset_id=shared.id,
            title="我的简历",
        )
    )
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
