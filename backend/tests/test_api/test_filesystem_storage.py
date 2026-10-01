"""Real private-storage HTTP flow without external services or model calls."""

from io import BytesIO
from urllib.parse import urlsplit, parse_qs

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.file_assets import router
from app.core import storage
from app.core.security import get_current_user
from app.db.database import get_db
from app.models.file_asset import FileAsset
from app.models.user import User
from app.files.application.storage_access import asset_url


@pytest.fixture
def env(db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(storage.settings, "STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(storage.settings, "STORAGE_BACKEND", "filesystem")
    monkeypatch.setattr(storage.settings, "STORAGE_MIN_FREE_BYTES", 0)
    owner = User(username="local-owner", hashed_password="x")
    other = User(username="other-owner", hashed_password="x")
    db_session.add_all([owner, other])
    db_session.commit()
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: owner
    with TestClient(app) as client:
        yield client, db_session, owner, other, tmp_path


def reserve(
    env,
    *,
    purpose="resume",
    content=b"%PDF-1.7 test",
    mime="application/pdf",
    filename="test.pdf",
):
    client, db, *_ = env
    response = client.post(
        "/api/v1/file-assets/upload-url",
        json={
            "purpose": purpose,
            "filename": filename,
            "content_type": mime,
            "size_bytes": len(content),
        },
    )
    assert response.status_code == 200, response.text
    info = response.json()
    return info, db.get(FileAsset, info["file_asset_id"])


def put_confirm(env, **kwargs):
    client = env[0]
    content = kwargs.get("content", b"%PDF-1.7 test")
    mime = kwargs.get("mime", "application/pdf")
    info, asset = reserve(env, **kwargs)
    response = client.put(
        info["upload_url"], content=content, headers={"Content-Type": mime}
    )
    assert response.status_code == 204, response.text
    response = client.post(f"/api/v1/file-assets/{asset.id}/confirm")
    assert response.status_code == 200, response.text
    assert response.json()["validation_status"] == "passed", response.text
    return info, asset


@pytest.mark.parametrize(
    "purpose,mime,filename,content",
    [
        ("resume", "application/pdf", "cv.pdf", b"%PDF-1.7 test"),
        ("jd", "text/plain", "jd.txt", b"job description"),
        ("knowledge_document", "text/markdown", "note.md", b"knowledge"),
        ("interview_audio", "audio/mpeg", "audio.mp3", b"ID3audio"),
        ("mock_audio_clip", "audio/mpeg", "audio.mp3", b"ID3audio"),
        ("avatar", "image/png", "avatar.png", b"\x89PNG\r\n\x1a\nimage"),
        ("agent_output", "text/plain", "output.txt", b"output"),
    ],
)
def test_seven_purposes_roundtrip_use_download_delete(
    env, purpose, mime, filename, content
):
    client, db, owner, _, root = env
    info, asset = put_confirm(
        env, purpose=purpose, mime=mime, filename=filename, content=content
    )
    from app.files.application.file_asset_service import mark_file_asset_consumed

    mark_file_asset_consumed(db, asset)
    db.commit()
    assert client.get(f"/api/v1/file-assets/{asset.id}/download").content == content
    url = asset_url(asset, owner=owner, operation="read")
    assert client.get(url).content == content
    assert (
        client.put(
            info["upload_url"], content=content, headers={"Content-Type": mime}
        ).status_code
        == 409
    )
    storage.delete_object(asset.storage_uri)
    assert client.get(url).status_code == 404
    assert not list(root.rglob(".upload-*"))


def test_audio_range_head_and_invalid_range(env):
    client, _, owner, *_ = env
    _, asset = put_confirm(
        env,
        purpose="interview_audio",
        mime="audio/mpeg",
        filename="a.mp3",
        content=b"ID30123456789",
    )
    url = asset_url(asset, owner=owner, operation="read")
    response = client.get(url, headers={"Range": "bytes=3-6"})
    assert response.status_code == 206 and response.content == b"0123"
    assert response.headers["content-range"] == "bytes 3-6/13"
    assert response.headers["content-length"] == "4"
    assert response.headers["content-disposition"].startswith("inline")
    assert client.get(url, headers={"Range": "bytes=-3"}).content == b"789"
    response = client.head(url)
    assert (
        response.status_code == 200
        and response.content == b""
        and response.headers["content-length"] == "13"
    )
    for value in ["bytes=99-", "bytes=4-1", "bytes=-0", "bytes=1-2,4-5"]:
        response = client.get(url, headers={"Range": value})
        assert (
            response.status_code == 416
            and response.headers["content-range"] == "bytes */13"
        )


def test_capability_wrong_asset_method_owner_purpose_expiry_and_revocation(env):
    client, db, owner, other, _ = env
    info, asset = put_confirm(env)
    read_url = asset_url(asset, owner=owner, operation="read")
    assert client.get(info["upload_url"]).status_code == 403
    assert client.put(read_url, content=b"bad").status_code == 403
    assert client.get(read_url.replace(asset.id, "fa_other")).status_code == 404
    assert (
        client.get(
            asset_url(asset, owner=owner, operation="read", expiration=-1)
        ).status_code
        == 403
    )
    asset.purpose = "jd"
    db.commit()
    assert client.get(read_url).status_code == 404
    asset.purpose = "resume"
    asset.user_id = other.id
    db.commit()
    assert client.get(read_url).status_code == 404
    asset.user_id = owner.id
    db.commit()
    owner.token_version += 1
    db.commit()
    assert client.get(read_url).status_code == 403
    fresh = asset_url(asset, owner=owner, operation="read")
    owner.is_active = False
    db.commit()
    assert client.get(fresh).status_code == 403


def test_no_replay_even_before_confirm_and_checksum_version(env):
    import hashlib

    client, db, owner, *_ = env
    info, asset = reserve(env)
    for expected in [204, 409]:
        assert (
            client.put(
                info["upload_url"],
                content=b"%PDF-1.7 test",
                headers={"Content-Type": "application/pdf"},
            ).status_code
            == expected
        )
    assert asset.checksum_sha256 == hashlib.sha256(b"%PDF-1.7 test").hexdigest()
    client.post(f"/api/v1/file-assets/{asset.id}/confirm")
    url = asset_url(asset, owner=owner, operation="read")
    asset.checksum_sha256 = "changed"
    db.commit()
    assert client.get(url).status_code == 404


def test_wrong_mime_partial_oversize_and_diskfull_leave_retryable(env, monkeypatch):
    client, _, _, _, root = env
    info, asset = reserve(env)
    assert (
        client.put(
            info["upload_url"],
            content=b"%PDF-1.7 test",
            headers={"Content-Type": "text/plain"},
        ).status_code
        == 415
    )
    assert (
        client.put(
            info["upload_url"],
            content=b"short",
            headers={"Content-Type": "application/pdf"},
        ).status_code
        == 400
    )
    assert (
        client.put(
            info["upload_url"],
            content=b"x",
            headers={
                "Content-Type": "application/pdf",
                "Content-Length": str(21 * 1024 * 1024),
            },
        ).status_code
        == 413
    )
    with monkeypatch.context() as m:
        m.setattr(
            storage,
            "check_free_space",
            lambda *a: (_ for _ in ()).throw(OSError(28, "full")),
        )
        assert (
            client.put(
                info["upload_url"],
                content=b"%PDF-1.7 test",
                headers={"Content-Type": "application/pdf"},
            ).status_code
            == 507
        )
    assert storage.head_object(asset.storage_uri) is None
    assert asset.upload_status == "pending_upload"
    assert (
        client.put(
            info["upload_url"],
            content=b"%PDF-1.7 test",
            headers={"Content-Type": "application/pdf"},
        ).status_code
        == 204
    )
    assert not list(root.rglob(".upload-*"))


def test_owner_usage_and_documents_never_inline(env):
    client, db, owner, other, _ = env
    _, asset = put_confirm(
        env,
        purpose="agent_output",
        mime="text/html",
        filename="x.html",
        content=b"<script>bad()</script>",
    )
    result = client.get(asset_url(asset, owner=owner, operation="read"))
    assert result.headers["content-disposition"].startswith("attachment")
    assert result.headers["x-content-type-options"] == "nosniff"
    usage = client.get("/api/v1/file-assets/storage-usage").json()
    assert usage["asset_count"] == 1 and usage["used_bytes"] == asset.size_bytes
    assert usage["backend"] == "filesystem" and usage["free_bytes"] > 0
    assert "storage" not in str(usage.keys())
    asset.user_id = other.id
    db.commit()
    assert client.get(f"/api/v1/file-assets/{asset.id}/download").status_code == 404
    assert client.get("/api/v1/file-assets/storage-usage").json()["asset_count"] == 0


def test_capability_cannot_be_access_token(env):
    from app.core.security import decode_token

    info, _ = reserve(env)
    token = parse_qs(urlsplit(info["upload_url"]).query)["token"][0]
    with pytest.raises(Exception):
        decode_token(token)


def test_s3_still_uploads_and_reads_when_default_changes(env, monkeypatch):
    from unittest.mock import MagicMock

    client, _, owner, *_ = env
    monkeypatch.setattr(storage.settings, "STORAGE_BACKEND", "s3")
    monkeypatch.setattr(
        storage.settings, "AWS_ENDPOINT_URL", "https://s3.example.invalid"
    )
    monkeypatch.setattr(storage.settings, "AWS_ACCESS_KEY_ID", "synthetic")
    monkeypatch.setattr(storage.settings, "AWS_SECRET_ACCESS_KEY", "synthetic")
    fake = MagicMock()
    data = {}
    from botocore.exceptions import ClientError

    def head(**kwargs):
        if not data:
            raise ClientError({"Error": {"Code": "404"}}, "HeadObject")
        return {"ContentLength": len(data["bytes"]), "ContentType": "application/pdf"}

    def put(**kwargs):
        assert kwargs["IfNoneMatch"] == "*"
        data["bytes"] = kwargs["Body"].read()

    fake.head_object.side_effect = head
    fake.put_object.side_effect = put
    fake.get_object.side_effect = lambda **kwargs: {"Body": BytesIO(data["bytes"])}
    monkeypatch.setattr(storage, "s3_client", fake)
    _, asset = put_confirm(env)
    monkeypatch.setattr(storage.settings, "STORAGE_BACKEND", "filesystem")
    assert asset.storage_uri.startswith("s3://")
    assert (
        client.get(asset_url(asset, owner=owner, operation="read")).content
        == b"%PDF-1.7 test"
    )


def test_disconnected_upload_cleans_scratch_and_can_retry(env):
    import asyncio
    from fastapi import Request, Response
    from starlette.requests import ClientDisconnect
    from app.api.file_assets import upload_file_content

    client, db, *_ = env
    info, asset = reserve(env)
    token = parse_qs(urlsplit(info["upload_url"]).query)["token"][0]
    messages = iter(
        [
            {"type": "http.request", "body": b"%PDF-", "more_body": True},
            {"type": "http.disconnect"},
        ]
    )

    async def receive():
        return next(messages)

    request = Request(
        {
            "type": "http",
            "method": "PUT",
            "path": "/",
            "headers": [(b"content-type", b"application/pdf")],
        },
        receive=receive,
    )
    endpoint = getattr(upload_file_content, "__wrapped__", upload_file_content)
    with pytest.raises(ClientDisconnect):
        asyncio.run(endpoint(request, Response(), asset.id, token, db))
    assert storage.head_object(asset.storage_uri) is None
    assert (
        client.put(
            info["upload_url"],
            content=b"%PDF-1.7 test",
            headers={"Content-Type": "application/pdf"},
        ).status_code
        == 204
    )


def test_failed_atomic_commit_cleans_temporary_and_keeps_original(env, monkeypatch):
    info, asset = reserve(env)
    client = env[0]
    with monkeypatch.context() as m:
        m.setattr(
            storage.os,
            "link",
            lambda *a, **k: (_ for _ in ()).throw(OSError(28, "full")),
        )
        response = client.put(
            info["upload_url"],
            content=b"%PDF-1.7 test",
            headers={"Content-Type": "application/pdf"},
        )
        assert response.status_code == 507
    assert storage.head_object(asset.storage_uri) is None
    assert not list(env[4].rglob(".upload-*"))
    assert (
        client.put(
            info["upload_url"],
            content=b"%PDF-1.7 test",
            headers={"Content-Type": "application/pdf"},
        ).status_code
        == 204
    )


def test_read_capability_revoked_by_deletion_and_pending_not_readable(env):
    from app.db.types import utc_now

    client, db, owner, *_ = env
    _, pending = reserve(env)
    assert (
        client.get(asset_url(pending, owner=owner, operation="read")).status_code == 404
    )
    _, asset = put_confirm(env)
    url = asset_url(asset, owner=owner, operation="read")
    asset.deleted_at = utc_now()
    db.commit()
    assert client.get(url).status_code == 404


def test_batch_signer_rejects_corrupt_cross_owner_reference(env):
    from app.files.application.file_asset_service import presigned_get_urls

    _, db, owner, other, _ = env
    _, asset = put_confirm(
        env,
        purpose="mock_audio_clip",
        mime="audio/mpeg",
        filename="a.mp3",
        content=b"ID3test",
    )
    assert asset.id in presigned_get_urls(
        db, [asset.id], owner_id=owner.id, purpose="mock_audio_clip"
    )
    assert (
        presigned_get_urls(db, [asset.id], owner_id=other.id, purpose="mock_audio_clip")
        == {}
    )
    assert presigned_get_urls(db, [asset.id], owner_id=owner.id, purpose="avatar") == {}


def test_capability_query_redacted_only_for_file_routes():
    import logging
    from app.core.http_log_redaction import SensitiveQueryAccessLogFilter

    for path, redacted in [
        ("/api/v1/file-assets/fa_a/content?token=secret", True),
        ("/api/v1/file-assets/fa_a/content/?token=secret", True),
        ("/api/v1/file-assets/fa_a/content///?token=secret", True),
        ("/api/v1/file-assets/fa_a/content/rejected?token=secret", True),
        ("/api/v1/file-assets/storage-usage?x=1", False),
    ]:
        record = logging.LogRecord(
            "uvicorn.access",
            logging.INFO,
            "",
            1,
            "%s %s %s",
            ("peer", "GET", path),
            None,
        )
        SensitiveQueryAccessLogFilter().filter(record)
        assert ("sensitive-query-redacted" in record.args[2]) == redacted


def test_new_and_legacy_avatar_serializers_are_private_and_revocable(env):
    from app.identity.application.avatar_service import public_avatar_url, swap_avatar

    client, db, owner, other, root = env
    _, asset = put_confirm(
        env,
        purpose="avatar",
        mime="image/png",
        filename="a.png",
        content=b"\x89PNG\r\n\x1a\nimage",
    )
    swap_avatar(db, owner, asset)
    url = public_avatar_url(owner)
    assert url.startswith("/api/v1/file-assets/") and "static" not in url
    assert client.get(url).status_code == 200
    legacy = root / "avatars" / "legacy.png"
    legacy.parent.mkdir()
    legacy.write_bytes(b"\x89PNG\r\n\x1a\nlegacy")
    owner.avatar_url = "local://avatars/legacy.png"
    db.commit()
    url = public_avatar_url(owner)
    assert client.get(url).content == legacy.read_bytes()
    owner.avatar_url = None
    db.commit()
    assert client.get(url).status_code == 404


def test_local_jd_consumer_materializes_worker_temp_and_cleans_it(env, monkeypatch):
    from pathlib import Path
    from app.interviews.application.analysis_intake import extract_text_snapshot

    _, db, owner, *_ = env
    _, asset = put_confirm(
        env, purpose="jd", mime="text/plain", filename="jd.txt", content=b"job context"
    )
    paths = []

    def extract(path):
        paths.append(path)
        return Path(path).read_text()

    monkeypatch.setattr(
        "app.interviews.application.document_text.extract_document_text", extract
    )
    assert extract_text_snapshot(db, asset.id, owner.username) == "job context"
    assert paths and not Path(paths[0]).exists()


def test_missing_s3_configuration_is_actionable_and_never_falls_back(env, monkeypatch):
    client, db, _, _, root = env
    monkeypatch.setattr(storage.settings, "STORAGE_BACKEND", "s3")
    monkeypatch.setattr(storage.settings, "AWS_ENDPOINT_URL", "")
    monkeypatch.setattr(storage.settings, "AWS_ACCESS_KEY_ID", "")
    monkeypatch.setattr(storage.settings, "AWS_SECRET_ACCESS_KEY", "")
    monkeypatch.setattr(
        storage.boto3,
        "client",
        lambda *a, **k: pytest.fail("must not probe default endpoint"),
    )
    response = client.post(
        "/api/v1/file-assets/upload-url",
        json={"purpose": "resume", "filename": "cv.pdf"},
    )
    assert response.status_code == 503
    assert "AWS_ENDPOINT_URL" in response.json()["detail"]
    assert db.query(FileAsset).count() == 0
    assert not list(root.iterdir())
    monkeypatch.setattr(storage.settings, "STORAGE_BACKEND", "filesystem")
    _, asset = put_confirm(env)
    asset.storage_uri = f"s3://{storage.settings.S3_BUCKET_NAME}/{asset.object_key}"
    db.commit()
    monkeypatch.setattr(storage, "s3_client", storage._LazyS3Client())
    response = client.get(f"/api/v1/file-assets/{asset.id}/download")
    assert (
        response.status_code == 503 and "AWS_ENDPOINT_URL" in response.json()["detail"]
    )


def test_trailing_slash_capability_redirect_is_redacted(env):
    import logging
    from app.core.http_log_redaction import SensitiveQueryAccessLogFilter

    client, _, owner, *_ = env
    _, asset = put_confirm(env)
    url = asset_url(asset, owner=owner, operation="read")
    redirected = url.replace("/content?", "/content/?")
    response = client.get(redirected, follow_redirects=False)
    assert response.status_code == 307
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        "",
        1,
        "%s %s %s",
        ("peer", "GET", redirected),
        None,
    )
    SensitiveQueryAccessLogFilter().filter(record)
    assert "token=" not in record.args[2]
    assert "sensitive-query-redacted" in record.args[2]


def test_browser_audio_mime_parameters_preserve_upload_and_inline_playback(env):
    client, _, owner, *_ = env
    _, asset = put_confirm(
        env,
        purpose="interview_audio",
        mime="audio/webm;codecs=opus",
        filename="recording.webm",
        content=b"\x1a\x45\xdf\xa3webm",
    )
    response = client.get(asset_url(asset, owner=owner, operation="read"))
    assert response.status_code == 200
    assert response.headers["content-disposition"].startswith("inline")
    assert response.headers["content-type"].startswith("audio/webm")
