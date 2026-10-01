"""Real PostgreSQL row-lock ordering for immutable streamed FileAsset uploads.

Uses the shared isolated migrated PostgreSQL fixture. Required CI sets
REQUIRE_TEST_POSTGRES=1; an unavailable database then fails rather than skips.
The HTTP endpoint runs against actual sessions and filesystem bytes. Only the
ASGI receive channel is controlled, so no local listening socket is required.
"""

from concurrent.futures import ThreadPoolExecutor
import asyncio
import hashlib
from threading import Event
import time
from urllib.parse import parse_qs, urlsplit

from fastapi import HTTPException, Request, Response
import pytest
from sqlalchemy import text

from app.api.file_assets import upload_file_content
from app.core import storage
from app.files.application.file_asset_service import (
    create_file_asset,
    confirm_file_asset,
)
from app.files.application.file_asset_deletion_service import (
    FileAssetDeletionConflictError,
    permanently_delete_file_asset,
    preview_file_asset_deletion,
)
from app.models.file_asset import FileAsset
from app.models.outbox_job import OutboxJob
from app.models.user import User

PAYLOAD = b"%PDF-1.7 original immutable bytes"


@pytest.fixture
def transfer(database, monkeypatch, tmp_path):
    _, _, factory = database
    monkeypatch.setattr(storage.settings, "STORAGE_BACKEND", "filesystem")
    monkeypatch.setattr(storage.settings, "STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(storage.settings, "STORAGE_MIN_FREE_BYTES", 0)
    with factory() as db:
        owner = User(username="storage-race", hashed_password="synthetic")
        db.add(owner)
        db.commit()
        asset, info = create_file_asset(
            db,
            user_id=owner.username,
            filename="original.pdf",
            purpose="resume",
            content_type="application/pdf",
            size_bytes=len(PAYLOAD),
        )
        return (
            factory,
            owner.id,
            asset.id,
            asset.storage_uri,
            info["upload_url"],
            tmp_path,
        )


def run_put(transfer, *, entered=None, release=None, pid_ready=None, payload=PAYLOAD):
    factory, _, asset_id, _, url, _ = transfer
    token = parse_qs(urlsplit(url).query)["token"][0]
    with factory() as db:
        if pid_ready is not None:
            pid_ready["pid"] = db.scalar(text("SELECT pg_backend_pid()"))
            pid_ready["ready"].set()
        reads = 0

        async def receive():
            nonlocal reads
            reads += 1
            if release is not None and reads == 1:
                return {"type": "http.request", "body": payload[:5], "more_body": True}
            if reads > (2 if release is not None else 1):
                raise AssertionError("unexpected extra ASGI read")
            if entered is not None:
                entered.set()
            if release is not None:
                if not await asyncio.to_thread(release.wait, 15):
                    raise TimeoutError("test did not release upload")
            return {
                "type": "http.request",
                "body": payload[5:] if release is not None else payload,
                "more_body": False,
            }

        request = Request(
            {
                "type": "http",
                "method": "PUT",
                "path": "/",
                "headers": [
                    (b"content-type", b"application/pdf"),
                    (b"content-length", str(len(payload)).encode()),
                ],
            },
            receive=receive,
        )
        endpoint = getattr(upload_file_content, "__wrapped__", upload_file_content)
        try:
            return asyncio.run(
                endpoint(request, Response(), asset_id, token, db)
            ).status_code
        except HTTPException as exc:
            return exc.status_code


def wait_for_real_pg_lock(factory, state):
    assert state["ready"].wait(10), "competing session never started"
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        with factory() as db:
            waiting = db.scalar(
                text("SELECT wait_event_type FROM pg_stat_activity WHERE pid=:pid"),
                {"pid": state["pid"]},
            )
        if waiting == "Lock":
            return
        time.sleep(0.02)
    pytest.fail("competing operation did not wait on a real PostgreSQL lock")


def test_competing_puts_commit_exactly_one_original(transfer):
    factory, _, asset_id, uri, _, root = transfer
    entered, release = Event(), Event()
    state = {"ready": Event()}
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(run_put, transfer, entered=entered, release=release)
        try:
            assert entered.wait(10)
            second = pool.submit(
                run_put, transfer, pid_ready=state, payload=b"X" * len(PAYLOAD)
            )
            wait_for_real_pg_lock(factory, state)
        finally:
            release.set()
        assert first.result(timeout=15) == 204
        assert second.result(timeout=15) == 409
    assert storage.read_object_head(uri, len(PAYLOAD)) == PAYLOAD
    with factory() as db:
        asset = confirm_file_asset(db, file_asset_id=asset_id, user_id="storage-race")
        assert asset.upload_status == "uploaded"
        assert asset.checksum_sha256 == hashlib.sha256(PAYLOAD).hexdigest()
    assert run_put(transfer, payload=b"Y" * len(PAYLOAD)) == 409
    assert storage.read_object_head(uri, len(PAYLOAD)) == PAYLOAD
    assert not list(root.rglob(".upload-*"))


def test_confirm_waits_for_complete_upload_not_partial_file(transfer):
    factory, _, asset_id, uri, _, _ = transfer
    entered, release = Event(), Event()
    state = {"ready": Event()}

    def confirm():
        with factory() as db:
            state["pid"] = db.scalar(text("SELECT pg_backend_pid()"))
            state["ready"].set()
            asset = confirm_file_asset(
                db, file_asset_id=asset_id, user_id="storage-race"
            )
            return asset.upload_status, asset.validation_status

    with ThreadPoolExecutor(max_workers=2) as pool:
        upload = pool.submit(run_put, transfer, entered=entered, release=release)
        try:
            assert entered.wait(10)
            assert storage.head_object(uri) is None
            confirmed = pool.submit(confirm)
            wait_for_real_pg_lock(factory, state)
        finally:
            release.set()
        assert upload.result(timeout=15) == 204
        assert confirmed.result(timeout=15) == ("uploaded", "passed")
    assert storage.read_object_head(uri, len(PAYLOAD)) == PAYLOAD


def test_delete_waits_then_requires_fresh_confirmation_and_revokes_upload(transfer):
    factory, owner, asset_id, uri, _, _ = transfer
    with factory() as db:
        preview = preview_file_asset_deletion(db, user_pk=owner, file_asset_id=asset_id)
    entered, release = Event(), Event()
    state = {"ready": Event()}

    def delete_stale():
        with factory() as db:
            state["pid"] = db.scalar(text("SELECT pg_backend_pid()"))
            state["ready"].set()
            with pytest.raises(FileAssetDeletionConflictError):
                permanently_delete_file_asset(
                    db,
                    user_pk=owner,
                    file_asset_id=asset_id,
                    confirmation_token=preview.confirmation_token,
                    confirm_file_asset_id=asset_id,
                    confirm_filename=preview.filename,
                )
            db.rollback()
            return "stale"

    with ThreadPoolExecutor(max_workers=2) as pool:
        upload = pool.submit(run_put, transfer, entered=entered, release=release)
        try:
            assert entered.wait(10)
            deleted = pool.submit(delete_stale)
            wait_for_real_pg_lock(factory, state)
        finally:
            release.set()
        assert upload.result(timeout=15) == 204
        assert deleted.result(timeout=15) == "stale"
    assert storage.read_object_head(uri, len(PAYLOAD)) == PAYLOAD
    with factory() as db:
        fresh = preview_file_asset_deletion(db, user_pk=owner, file_asset_id=asset_id)
        permanently_delete_file_asset(
            db,
            user_pk=owner,
            file_asset_id=asset_id,
            confirmation_token=fresh.confirmation_token,
            confirm_file_asset_id=asset_id,
            confirm_filename=fresh.filename,
        )
        db.commit()
    assert run_put(transfer) == 404
    from app.platform.outbox import _handle_delete_object

    with factory() as db:
        job = (
            db.query(OutboxJob)
            .filter(
                OutboxJob.aggregate_id == asset_id,
                OutboxJob.job_type == "delete_object",
            )
            .one()
        )
        _handle_delete_object(db, job)
        db.commit()
        assert db.get(FileAsset, asset_id).upload_status == "deleted"
    assert storage.head_object(uri) is None


def test_upload_waits_for_delete_commit_and_cannot_resurrect_bytes(transfer):
    factory, owner, asset_id, uri, _, _ = transfer
    state = {"ready": Event()}
    with factory() as deletion:
        preview = preview_file_asset_deletion(
            deletion, user_pk=owner, file_asset_id=asset_id
        )
        permanently_delete_file_asset(
            deletion,
            user_pk=owner,
            file_asset_id=asset_id,
            confirmation_token=preview.confirmation_token,
            confirm_file_asset_id=asset_id,
            confirm_filename=preview.filename,
        )
        with ThreadPoolExecutor(max_workers=1) as pool:
            upload = pool.submit(run_put, transfer, pid_ready=state)
            try:
                wait_for_real_pg_lock(factory, state)
            finally:
                deletion.commit()
            assert upload.result(timeout=15) == 404
    assert storage.head_object(uri) is None
