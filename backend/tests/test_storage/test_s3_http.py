"""Opt-in protocol tests against a disposable S3-compatible HTTP service.

Required CI provides TEST_S3_ENDPOINT, TEST_S3_ACCESS_KEY_ID,
TEST_S3_SECRET_ACCESS_KEY, TEST_S3_BUCKET (a disposable bucket-name prefix), and
REQUIRE_TEST_S3=1. Only loopback or reserved Docker fixture hostnames are allowed;
these tests must never connect to a real cloud account. Each case creates and
removes its own uniquely named bucket. No server is started by this module.
"""

from io import BytesIO
import os
from pathlib import Path
import re
from urllib.parse import urlsplit
import uuid

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.api.file_assets import router
from app.core import storage
from app.core.security import get_current_user
from app.db.database import get_db
from app.files.application.storage_access import asset_url
from app.models.file_asset import FileAsset
from app.models.user import User


@pytest.fixture
def s3_http(monkeypatch, tmp_path):
    endpoint = os.environ.get("TEST_S3_ENDPOINT", "").strip()
    if not endpoint:
        if os.environ.get("REQUIRE_TEST_S3") == "1":
            pytest.fail(
                "REQUIRE_TEST_S3=1 requires the disposable TEST_S3_ENDPOINT fixture"
            )
        pytest.skip("Disposable S3 HTTP fixture not configured")
    parsed = urlsplit(endpoint)
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.username
        or parsed.password
        or parsed.hostname
        not in {
            "localhost",
            "127.0.0.1",
            "::1",
            "s3",
            "s3-fixture",
            "storage-fixture",
            "garage",
            "rustfs",
            "seaweedfs",
        }
    ):
        pytest.fail(
            "S3 tests allow only loopback or reserved disposable Docker fixture hosts"
        )
    access = os.environ.get("TEST_S3_ACCESS_KEY_ID", "").strip()
    secret = os.environ.get("TEST_S3_SECRET_ACCESS_KEY", "").strip()
    prefix = os.environ.get("TEST_S3_BUCKET", "").strip()
    if (
        not access
        or not secret
        or not re.fullmatch(r"[a-z][a-z0-9-]{1,40}[a-z0-9]", prefix)
    ):
        pytest.fail(
            "Configure explicit synthetic TEST_S3_ACCESS_KEY_ID, TEST_S3_SECRET_ACCESS_KEY and TEST_S3_BUCKET prefix"
        )
    bucket = f"{prefix}-{uuid.uuid4().hex[:12]}"
    admin = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access,
        aws_secret_access_key=secret,
        region_name="us-east-1",
        config=Config(
            connect_timeout=3,
            read_timeout=10,
            retries={"total_max_attempts": 1},
            s3={"addressing_style": "path"},
        ),
    )
    try:
        admin.create_bucket(Bucket=bucket)
    except Exception as exc:
        admin.close()
        pytest.fail(
            f"Configured disposable S3 fixture unavailable ({type(exc).__name__})"
        )
    monkeypatch.setattr(storage.settings, "STORAGE_BACKEND", "s3")
    monkeypatch.setattr(storage.settings, "STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(storage.settings, "STORAGE_MIN_FREE_BYTES", 0)
    monkeypatch.setattr(storage.settings, "AWS_ENDPOINT_URL", endpoint)
    monkeypatch.setattr(storage.settings, "AWS_ACCESS_KEY_ID", access)
    monkeypatch.setattr(storage.settings, "AWS_SECRET_ACCESS_KEY", secret)
    monkeypatch.setattr(storage.settings, "S3_BUCKET_NAME", bucket)
    private = storage._LazyS3Client()
    monkeypatch.setattr(storage, "s3_client", private)
    try:
        yield bucket, tmp_path
    finally:
        if private.client is not None:
            private.client.close()
        # This bucket was uniquely created by this fixture, never a user bucket.
        try:
            for page in admin.get_paginator("list_objects_v2").paginate(Bucket=bucket):
                for item in page.get("Contents", []):
                    admin.delete_object(Bucket=bucket, Key=item["Key"])
            admin.delete_bucket(Bucket=bucket)
        finally:
            admin.close()


def test_real_s3_put_head_range_immutable_switch_and_delete(s3_http, monkeypatch):
    bucket, root = s3_http
    content = b"original S3 protocol fixture bytes"
    key = "uploads/1/fa_protocol/original.txt"
    uri = storage.upload_file_to_owned_key(BytesIO(content), key, "text/plain")
    assert uri == f"s3://{bucket}/{key}"
    assert storage.head_object(uri) == {
        "size_bytes": len(content),
        "content_type": "text/plain",
    }
    with storage.open_object(uri, start=3, end=11) as body:
        assert body.read() == content[3:12]
    with pytest.raises(ClientError) as rejected:
        storage.store_object(BytesIO(b"replacement"), uri, content_type="text/plain")
    assert rejected.value.response["ResponseMetadata"]["HTTPStatusCode"] in {409, 412}
    monkeypatch.setattr(storage.settings, "STORAGE_BACKEND", "filesystem")
    with storage.open_object(uri) as body:
        assert body.read() == content
    with storage.materialize_object(uri) as path:
        assert Path(path).read_bytes() == content
    assert not Path(path).exists()
    assert not list(root.rglob("*")), (
        "S3 bytes must not silently fall back to local storage"
    )
    storage.delete_object(uri)
    assert storage.head_object(uri) is None


def test_real_s3_asset_http_confirm_range_replay_and_legacy_read(
    s3_http, db_session, monkeypatch
):
    owner = User(username="real-s3-fixture-owner", hashed_password="synthetic")
    db_session.add(owner)
    db_session.commit()
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: owner
    content = b"ID3 original media fixture bytes"
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/file-assets/upload-url",
            json={
                "purpose": "interview_audio",
                "filename": "original.mp3",
                "content_type": "audio/mpeg",
                "size_bytes": len(content),
            },
        )
        assert response.status_code == 200, response.text
        info = response.json()
        assert (
            client.put(
                info["upload_url"],
                content=content,
                headers={"Content-Type": "audio/mpeg"},
            ).status_code
            == 204
        )
        response = client.post(f"/api/v1/file-assets/{info['file_asset_id']}/confirm")
        assert (
            response.status_code == 200
            and response.json()["validation_status"] == "passed"
        )
        asset = db_session.get(FileAsset, info["file_asset_id"])
        url = asset_url(asset, owner=owner, operation="read")
        response = client.get(url, headers={"Range": "bytes=4-11"})
        assert response.status_code == 206 and response.content == content[4:12]
        assert response.headers["content-range"] == f"bytes 4-11/{len(content)}"
        assert client.head(url).headers["content-length"] == str(len(content))
        assert (
            client.put(
                info["upload_url"],
                content=b"X" * len(content),
                headers={"Content-Type": "audio/mpeg"},
            ).status_code
            == 409
        )
        monkeypatch.setattr(storage.settings, "STORAGE_BACKEND", "filesystem")
        assert client.get(f"/api/v1/file-assets/{asset.id}/download").content == content
        assert asset.storage_uri.startswith("s3://")
        storage.delete_object(asset.storage_uri)
        assert client.get(url).status_code == 404
