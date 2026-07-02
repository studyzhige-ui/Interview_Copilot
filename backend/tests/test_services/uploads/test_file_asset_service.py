"""Tests for the file-asset + outbox services (UPLOAD-FILE-ASSETS)."""
from __future__ import annotations

import json

import pytest

from app.models.outbox_job import OutboxJob
from app.models.user import User
from app.services.uploads import file_asset_service, outbox_service


def _make_user(db, username="alice") -> User:
    user = User(username=username, email=f"{username}@e.com", hashed_password="x")
    db.add(user)
    db.flush()
    return user


@pytest.fixture(autouse=True)
def _stub_presign(monkeypatch):
    """create_file_asset mints a presigned URL — stub the S3 call out."""
    monkeypatch.setattr(
        file_asset_service,
        "generate_presigned_upload_url_for_key",
        lambda object_key, content_type="application/octet-stream": {
            "upload_url": f"https://signed.example/{object_key}",
            "storage_uri": f"s3://bucket/{object_key}",
            "object_key": object_key,
        },
    )


def test_create_file_asset_resolves_user_and_returns_url(db_session):
    user = _make_user(db_session)
    db_session.commit()

    asset, url_info = file_asset_service.create_file_asset(
        db_session, user_id="alice", filename="cv.pdf", purpose="resume",
        size_bytes=100,
    )
    assert asset.id.startswith("fa_")
    assert asset.user_id == user.id  # stable users.id, NOT username
    assert asset.upload_status == "pending_upload"
    assert asset.validation_status == "pending"
    assert url_info["upload_url"].startswith("https://signed.example/")


def test_create_file_asset_unknown_user_raises(db_session):
    with pytest.raises(ValueError):
        file_asset_service.create_file_asset(
            db_session, user_id="ghost", filename="x.pdf", purpose="resume",
        )


def test_confirm_passes_when_object_present(db_session, monkeypatch):
    _make_user(db_session)
    db_session.commit()
    asset, _ = file_asset_service.create_file_asset(
        db_session, user_id="alice", filename="a.mp3", purpose="interview_audio",
        size_bytes=2048,
    )
    monkeypatch.setattr(
        file_asset_service, "head_object",
        lambda uri: {"size_bytes": 2048, "content_type": "audio/mpeg"},
    )
    confirmed = file_asset_service.confirm_file_asset(
        db_session, file_asset_id=asset.id, user_id="alice",
    )
    assert confirmed.upload_status == "uploaded"
    assert confirmed.validation_status == "passed"


def test_confirm_missing_object_fails_and_enqueues_cleanup(db_session, monkeypatch):
    _make_user(db_session)
    db_session.commit()
    asset, _ = file_asset_service.create_file_asset(
        db_session, user_id="alice", filename="a.mp3", purpose="interview_audio",
    )
    monkeypatch.setattr(file_asset_service, "head_object", lambda uri: None)
    confirmed = file_asset_service.confirm_file_asset(
        db_session, file_asset_id=asset.id, user_id="alice",
    )
    assert confirmed.upload_status == "failed"
    assert confirmed.validation_status == "failed"
    # A cleanup job was enqueued for the orphaned object.
    job = db_session.query(OutboxJob).filter(
        OutboxJob.job_type == "cleanup_failed_upload",
    ).first()
    assert job is not None and job.aggregate_id == asset.id


def test_confirm_size_mismatch_fails(db_session, monkeypatch):
    _make_user(db_session)
    db_session.commit()
    asset, _ = file_asset_service.create_file_asset(
        db_session, user_id="alice", filename="a.pdf", purpose="resume",
        size_bytes=100,
    )
    monkeypatch.setattr(
        file_asset_service, "head_object",
        lambda uri: {"size_bytes": 999, "content_type": None},
    )
    confirmed = file_asset_service.confirm_file_asset(
        db_session, file_asset_id=asset.id, user_id="alice",
    )
    assert confirmed.validation_status == "failed"
    assert "size mismatch" in confirmed.validation_error


def test_get_owned_file_asset_enforces_ownership(db_session):
    _make_user(db_session, "alice")
    _make_user(db_session, "bob")
    db_session.commit()
    asset, _ = file_asset_service.create_file_asset(
        db_session, user_id="alice", filename="a.pdf", purpose="resume",
    )
    assert file_asset_service.get_owned_file_asset(
        db_session, file_asset_id=asset.id, user_id="alice",
    ) is not None
    # Bob can't see alice's asset.
    assert file_asset_service.get_owned_file_asset(
        db_session, file_asset_id=asset.id, user_id="bob",
    ) is None


# ── outbox ──────────────────────────────────────────────────────────────────


def test_enqueue_job_is_idempotent(db_session):
    user = _make_user(db_session)
    db_session.commit()
    j1 = outbox_service.enqueue_job(
        db_session, user_pk=user.id, job_type="delete_object",
        payload={"storage_uri": "s3://b/k"}, idempotency_key="k1",
    )
    db_session.commit()
    j2 = outbox_service.enqueue_job(
        db_session, user_pk=user.id, job_type="delete_object",
        payload={"storage_uri": "s3://b/k"}, idempotency_key="k1",
    )
    db_session.commit()
    assert j1.id == j2.id
    assert db_session.query(OutboxJob).count() == 1


def test_run_due_outbox_jobs_runs_handler(db_session, monkeypatch):
    user = _make_user(db_session)
    db_session.commit()
    outbox_service.enqueue_job(
        db_session, user_pk=user.id, job_type="delete_object",
        payload={"storage_uri": "local://tmp/x"}, idempotency_key="d1",
    )
    db_session.commit()

    seen = {}
    monkeypatch.setitem(
        outbox_service._HANDLERS, "delete_object",
        lambda db, job: seen.update({"uri": json.loads(job.payload_json)["storage_uri"]}),
    )
    processed = outbox_service.run_due_outbox_jobs(db_session)
    assert processed == 1
    assert seen["uri"] == "local://tmp/x"
    job = db_session.query(OutboxJob).first()
    assert job.status == "succeeded"


def test_run_due_outbox_jobs_retries_on_failure(db_session, monkeypatch):
    user = _make_user(db_session)
    db_session.commit()
    outbox_service.enqueue_job(
        db_session, user_pk=user.id, job_type="delete_object",
        payload={}, idempotency_key="f1", max_attempts=3,
    )
    db_session.commit()

    def _boom(db, job):
        raise RuntimeError("storage down")

    monkeypatch.setitem(outbox_service._HANDLERS, "delete_object", _boom)
    outbox_service.run_due_outbox_jobs(db_session)
    job = db_session.query(OutboxJob).first()
    assert job.status == "failed"  # retryable, not dead yet
    assert job.attempts == 1
    assert "storage down" in job.last_error
