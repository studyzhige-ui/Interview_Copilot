"""Tests for the file-asset + outbox services (UPLOAD-FILE-ASSETS)."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.models.outbox_job import OutboxJob
from app.models.user import User
from app.services import outbox as outbox_service
from app.services.uploads import file_asset_service


def _make_user(db, username="alice") -> User:
    user = User(username=username, email=f"{username}@e.com", hashed_password="x")
    db.add(user)
    db.flush()
    return user


@pytest.fixture(autouse=True)
def _stub_presign(monkeypatch):
    """create_file_asset mints a presigned URL — stub the S3 call out.
    Records the TTL each call used so tests can pin UP-7."""
    calls = {}

    def _fake(object_key, content_type="application/octet-stream", expiration=600):
        calls["expiration"] = expiration
        return {
            "upload_url": f"https://signed.example/{object_key}",
            "storage_uri": f"s3://bucket/{object_key}",
            "object_key": object_key,
        }

    monkeypatch.setattr(
        file_asset_service,
        "generate_presigned_upload_url_for_key",
        _fake,
    )
    return calls


@pytest.fixture(autouse=True)
def _stub_magic_gate(monkeypatch):
    """Confirm runs a head read + magic check (UP-6). Lifecycle tests aren't
    about the byte-level detectors (those have their own unit tests in
    test_file_validation_detect.py), so stub the gate open by default; the
    magic/transient-specific tests override per-case."""
    from app.services.uploads import file_validation

    monkeypatch.setattr(
        file_asset_service,
        "read_object_head",
        lambda uri, num_bytes=32: b"stub-head",
    )
    monkeypatch.setattr(
        file_validation,
        "detect_head_format",
        lambda head, kind, ext="": "stub",
    )


def test_create_file_asset_resolves_user_and_returns_url(db_session):
    user = _make_user(db_session)
    db_session.commit()

    asset, url_info = file_asset_service.create_file_asset(
        db_session,
        user_id="alice",
        filename="cv.pdf",
        purpose="resume",
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
            db_session,
            user_id="ghost",
            filename="x.pdf",
            purpose="resume",
        )


def test_confirm_passes_when_object_present(db_session, monkeypatch):
    _make_user(db_session)
    db_session.commit()
    asset, _ = file_asset_service.create_file_asset(
        db_session,
        user_id="alice",
        filename="a.mp3",
        purpose="interview_audio",
        size_bytes=2048,
    )
    monkeypatch.setattr(
        file_asset_service,
        "head_object",
        lambda uri: {"size_bytes": 2048, "content_type": "audio/mpeg"},
    )
    confirmed = file_asset_service.confirm_file_asset(
        db_session,
        file_asset_id=asset.id,
        user_id="alice",
    )
    assert confirmed.upload_status == "uploaded"
    assert confirmed.validation_status == "passed"


def test_confirm_missing_object_fails_and_enqueues_cleanup(db_session, monkeypatch):
    _make_user(db_session)
    db_session.commit()
    asset, _ = file_asset_service.create_file_asset(
        db_session,
        user_id="alice",
        filename="a.mp3",
        purpose="interview_audio",
    )
    monkeypatch.setattr(file_asset_service, "head_object", lambda uri: None)
    confirmed = file_asset_service.confirm_file_asset(
        db_session,
        file_asset_id=asset.id,
        user_id="alice",
    )
    assert confirmed.upload_status == "failed"
    assert confirmed.validation_status == "failed"
    # A cleanup job was enqueued for the orphaned object.
    job = (
        db_session.query(OutboxJob)
        .filter(
            OutboxJob.job_type == "cleanup_failed_upload",
        )
        .first()
    )
    assert job is not None and job.aggregate_id == asset.id


def test_confirm_size_mismatch_fails(db_session, monkeypatch):
    _make_user(db_session)
    db_session.commit()
    asset, _ = file_asset_service.create_file_asset(
        db_session,
        user_id="alice",
        filename="a.pdf",
        purpose="resume",
        size_bytes=100,
    )
    monkeypatch.setattr(
        file_asset_service,
        "head_object",
        lambda uri: {"size_bytes": 999, "content_type": None},
    )
    confirmed = file_asset_service.confirm_file_asset(
        db_session,
        file_asset_id=asset.id,
        user_id="alice",
    )
    assert confirmed.validation_status == "failed"
    assert "size mismatch" in confirmed.validation_error


def test_get_owned_file_asset_enforces_ownership(db_session):
    _make_user(db_session, "alice")
    _make_user(db_session, "bob")
    db_session.commit()
    asset, _ = file_asset_service.create_file_asset(
        db_session,
        user_id="alice",
        filename="a.pdf",
        purpose="resume",
    )
    assert (
        file_asset_service.get_owned_file_asset(
            db_session,
            file_asset_id=asset.id,
            user_id="alice",
        )
        is not None
    )
    # Bob can't see alice's asset.
    assert (
        file_asset_service.get_owned_file_asset(
            db_session,
            file_asset_id=asset.id,
            user_id="bob",
        )
        is None
    )


# ── outbox ──────────────────────────────────────────────────────────────────


def test_enqueue_job_is_idempotent(db_session):
    user = _make_user(db_session)
    db_session.commit()
    j1 = outbox_service.enqueue_job(
        db_session,
        user_pk=user.id,
        job_type="delete_object",
        payload={"storage_uri": "s3://b/k"},
        idempotency_key="k1",
    )
    db_session.commit()
    j2 = outbox_service.enqueue_job(
        db_session,
        user_pk=user.id,
        job_type="delete_object",
        payload={"storage_uri": "s3://b/k"},
        idempotency_key="k1",
    )
    db_session.commit()
    assert j1.id == j2.id
    assert db_session.query(OutboxJob).count() == 1


def test_enqueue_job_coalesces_before_caller_commit(db_session):
    user = _make_user(db_session)
    db_session.flush()

    first = outbox_service.enqueue_job(
        db_session,
        user_pk=user.id,
        job_type="delete_object",
        idempotency_key="same-transaction",
    )
    second = outbox_service.enqueue_job(
        db_session,
        user_pk=user.id,
        job_type="delete_object",
        idempotency_key="same-transaction",
    )

    assert first.id == second.id
    assert db_session.query(OutboxJob).count() == 1


def test_run_due_outbox_jobs_runs_handler(db_session, monkeypatch):
    user = _make_user(db_session)
    db_session.commit()
    outbox_service.enqueue_job(
        db_session,
        user_pk=user.id,
        job_type="delete_object",
        payload={"storage_uri": "local://tmp/x"},
        idempotency_key="d1",
    )
    db_session.commit()

    seen = {}
    monkeypatch.setitem(
        outbox_service._HANDLERS,
        "delete_object",
        lambda db, job: seen.update(
            {"uri": json.loads(job.payload_json)["storage_uri"]}
        ),
    )
    processed = outbox_service.run_due_outbox_jobs(db_session)
    assert processed == 1
    assert seen["uri"] == "local://tmp/x"
    job = db_session.query(OutboxJob).first()
    assert job.status == "succeeded"


def test_run_due_outbox_jobs_claims_only_requested_resource_class(
    db_session, monkeypatch
):
    user = _make_user(db_session)
    db_session.commit()
    for job_type in ("delete_object", "extract_memory_realtime"):
        outbox_service.enqueue_job(
            db_session,
            user_pk=user.id,
            job_type=job_type,
            payload={},
        )
    db_session.commit()
    seen: list[str] = []
    monkeypatch.setitem(
        outbox_service._HANDLERS,
        "delete_object",
        lambda db, job: seen.append(job.job_type),
    )

    processed = outbox_service.run_due_outbox_jobs(
        db_session,
        job_types={"delete_object", "cleanup_failed_upload"},
    )

    assert processed == 1
    assert seen == ["delete_object"]
    statuses = {job.job_type: job.status for job in db_session.query(OutboxJob).all()}
    assert statuses == {
        "delete_object": "succeeded",
        "extract_memory_realtime": "pending",
    }


def test_run_due_outbox_jobs_retries_on_failure(db_session, monkeypatch):
    user = _make_user(db_session)
    db_session.commit()
    outbox_service.enqueue_job(
        db_session,
        user_pk=user.id,
        job_type="delete_object",
        payload={},
        idempotency_key="f1",
        max_attempts=3,
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


def test_delete_object_handler_enforces_owner_prefix(monkeypatch):
    from app.core import storage

    deleted = []
    monkeypatch.setattr(storage, "delete_s3_object", deleted.append)
    owned_job = SimpleNamespace(
        job_type="delete_object",
        user_id=7,
        payload_json=json.dumps(
            {
                "storage_uri": "s3://bucket/uploads/7/asset/file.pdf",
                "user_id": 7,
            }
        ),
    )
    outbox_service._handle_delete_object(None, owned_job)
    assert deleted == ["s3://bucket/uploads/7/asset/file.pdf"]

    cross_tenant_job = SimpleNamespace(
        job_type="delete_object",
        user_id=7,
        payload_json=json.dumps(
            {
                "storage_uri": "s3://bucket/uploads/8/asset/file.pdf",
                "user_id": 7,
            }
        ),
    )
    with pytest.raises(PermissionError, match="outside its owner prefix"):
        outbox_service._handle_delete_object(None, cross_tenant_job)


# ── Phase 2: registry caps + confirm-on-consume + magic gate ────────────


def test_create_file_asset_rejects_unknown_purpose(db_session):
    _make_user(db_session)
    db_session.commit()
    with pytest.raises(file_asset_service.UnknownUploadPurpose):
        file_asset_service.create_file_asset(
            db_session,
            user_id="alice",
            filename="x.bin",
            purpose="mystery",
        )


def test_create_file_asset_rejects_oversized_declaration(db_session):
    _make_user(db_session)
    db_session.commit()
    with pytest.raises(file_asset_service.UploadTooLarge):
        file_asset_service.create_file_asset(
            db_session,
            user_id="alice",
            filename="cv.pdf",
            purpose="resume",
            size_bytes=21 * 1024 * 1024,  # registry cap: 20MB
        )


def test_confirm_rejects_actual_size_over_cap(db_session, monkeypatch):
    """UP-4: the declared size is client-controlled — the cap must bind on
    the ACTUAL stored size (declared small, PUT huge)."""
    _make_user(db_session)
    db_session.commit()
    asset, _ = file_asset_service.create_file_asset(
        db_session,
        user_id="alice",
        filename="cv.pdf",
        purpose="resume",
        size_bytes=None,  # nothing declared -> size-reconcile can't catch it
    )
    monkeypatch.setattr(
        file_asset_service,
        "head_object",
        lambda uri: {"size_bytes": 21 * 1024 * 1024, "content_type": None},
    )
    confirmed = file_asset_service.confirm_file_asset(
        db_session,
        file_asset_id=asset.id,
        user_id="alice",
    )
    assert confirmed.upload_status == "failed"
    assert "limit" in (confirmed.validation_error or "")


def test_confirm_rejects_wrong_magic(db_session, monkeypatch):
    """UP-6: content that fails the purpose's magic detection fails confirm."""
    from app.services.uploads import file_validation

    _make_user(db_session)
    db_session.commit()
    asset, _ = file_asset_service.create_file_asset(
        db_session,
        user_id="alice",
        filename="cv.pdf",
        purpose="resume",
        size_bytes=64,
    )
    monkeypatch.setattr(
        file_asset_service,
        "head_object",
        lambda uri: {"size_bytes": 64, "content_type": "application/pdf"},
    )
    monkeypatch.setattr(
        file_validation,
        "detect_head_format",
        lambda head, kind, ext="": None,
    )
    confirmed = file_asset_service.confirm_file_asset(
        db_session,
        file_asset_id=asset.id,
        user_id="alice",
    )
    assert confirmed.upload_status == "failed"
    assert "magic" in (confirmed.validation_error or "")
    # Cleanup for the rejected object was queued.
    job = (
        db_session.query(OutboxJob)
        .filter(
            OutboxJob.job_type == "cleanup_failed_upload",
            OutboxJob.aggregate_id == asset.id,
        )
        .first()
    )
    assert job is not None


def test_ensure_uploaded_verifies_pending_asset(db_session, monkeypatch):
    """UP-1 confirm-on-consume: consuming without /confirm still verifies."""
    _make_user(db_session)
    db_session.commit()
    asset, _ = file_asset_service.create_file_asset(
        db_session,
        user_id="alice",
        filename="a.mp3",
        purpose="interview_audio",
        size_bytes=2048,
    )
    monkeypatch.setattr(
        file_asset_service,
        "head_object",
        lambda uri: {"size_bytes": 2048, "content_type": "audio/mpeg"},
    )
    out = file_asset_service.ensure_uploaded(db_session, asset)
    assert out.upload_status == "uploaded"
    assert out.validation_status == "passed"


def test_ensure_uploaded_never_regresses_consumed(db_session, monkeypatch):
    _make_user(db_session)
    db_session.commit()
    asset, _ = file_asset_service.create_file_asset(
        db_session,
        user_id="alice",
        filename="a.mp3",
        purpose="interview_audio",
    )
    asset.upload_status = "consumed"
    db_session.commit()
    monkeypatch.setattr(
        file_asset_service,
        "head_object",
        lambda uri: (_ for _ in ()).throw(AssertionError("must not HEAD")),
    )
    out = file_asset_service.ensure_uploaded(db_session, asset)
    assert out.upload_status == "consumed"


def test_enqueue_asset_blob_delete_is_idempotent(db_session):
    """UP-2: one delete_object job per asset, no matter how many delete
    paths race."""
    _make_user(db_session)
    db_session.commit()
    asset, _ = file_asset_service.create_file_asset(
        db_session,
        user_id="alice",
        filename="a.mp3",
        purpose="interview_audio",
    )
    file_asset_service.enqueue_asset_blob_delete(db_session, asset)
    file_asset_service.enqueue_asset_blob_delete(db_session, asset)
    db_session.commit()
    jobs = (
        db_session.query(OutboxJob)
        .filter(
            OutboxJob.job_type == "delete_object",
            OutboxJob.aggregate_id == asset.id,
        )
        .all()
    )
    assert len(jobs) == 1
    assert json.loads(jobs[0].payload_json)["storage_uri"] == asset.storage_uri


def test_presign_ttl_follows_purpose(db_session, _stub_presign):
    """UP-7: interview audio keeps the 1h window, documents drop to 10min."""
    _make_user(db_session)
    db_session.commit()
    file_asset_service.create_file_asset(
        db_session,
        user_id="alice",
        filename="a.mp3",
        purpose="interview_audio",
    )
    assert _stub_presign["expiration"] == 3600
    file_asset_service.create_file_asset(
        db_session,
        user_id="alice",
        filename="cv.pdf",
        purpose="resume",
    )
    assert _stub_presign["expiration"] == 600


def test_transient_head_read_failure_keeps_asset_pending(db_session, monkeypatch):
    """A storage blip during the ranged head read must NOT destroy the
    upload: the asset stays pending (retryable), no cleanup job."""
    _make_user(db_session)
    db_session.commit()
    asset, _ = file_asset_service.create_file_asset(
        db_session,
        user_id="alice",
        filename="a.mp3",
        purpose="interview_audio",
        size_bytes=2048,
    )
    monkeypatch.setattr(
        file_asset_service,
        "head_object",
        lambda uri: {"size_bytes": 2048, "content_type": "audio/mpeg"},
    )
    monkeypatch.setattr(
        file_asset_service,
        "read_object_head",
        lambda uri, num_bytes=32: None,
    )
    out = file_asset_service.confirm_file_asset(
        db_session,
        file_asset_id=asset.id,
        user_id="alice",
    )
    assert out.upload_status == "pending_upload"
    assert out.validation_error  # user-visible retry hint
    assert db_session.query(OutboxJob).count() == 0

    # And a later retry (storage recovered) succeeds.
    monkeypatch.setattr(
        file_asset_service,
        "read_object_head",
        lambda uri, num_bytes=32: b"ID3ok",
    )
    out = file_asset_service.confirm_file_asset(
        db_session,
        file_asset_id=asset.id,
        user_id="alice",
    )
    assert out.upload_status == "uploaded"
