"""HTTP contracts for owner-scoped FileAsset reads."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api import file_assets as file_assets_api
from app.core.security import get_current_user
from app.db.database import get_db
from app.models.file_asset import FileAsset
from app.models.user import User


@pytest.fixture
def users(db_session: Session) -> tuple[User, User]:
    alice = User(
        username="file-asset-alice",
        email="file-asset-alice@example.com",
        hashed_password="x",
    )
    bob = User(
        username="file-asset-bob",
        email="file-asset-bob@example.com",
        hashed_password="x",
    )
    db_session.add_all([alice, bob])
    db_session.commit()
    return alice, bob


@pytest.fixture
def client(db_session: Session, users: tuple[User, User]) -> Iterator[TestClient]:
    alice, _bob = users

    def fake_db() -> Iterator[Session]:
        yield db_session

    app = FastAPI()
    app.include_router(file_assets_api.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = lambda: alice
    app.dependency_overrides[get_db] = fake_db
    with TestClient(app) as test_client:
        yield test_client


def _asset(
    db: Session,
    *,
    owner: User,
    asset_id: str,
    storage_uri: str,
    filename: str = "求职报告.md",
    upload_status: str = "uploaded",
    validation_status: str = "passed",
    deleted: bool = False,
    size_bytes: int | None = None,
) -> FileAsset:
    row = FileAsset(
        id=asset_id,
        user_id=owner.id,
        purpose="agent_output",
        original_filename=filename,
        object_key=f"opaque/{asset_id}",
        storage_uri=storage_uri,
        content_type="text/markdown",
        size_bytes=size_bytes,
        upload_status=upload_status,
        validation_status=validation_status,
        deleted_at=datetime.now(timezone.utc) if deleted else None,
    )
    db.add(row)
    db.commit()
    return row


class _ObjectBody:
    def __init__(self, content: bytes):
        self.content = content
        self.closed = False

    def iter_chunks(self, *, chunk_size: int):
        yield from (
            self.content[offset : offset + chunk_size]
            for offset in range(0, len(self.content), chunk_size)
        )

    def close(self) -> None:
        self.closed = True


def test_download_streams_owned_s3_asset_without_disclosing_locator(
    client: TestClient,
    db_session: Session,
    users: tuple[User, User],
    monkeypatch: pytest.MonkeyPatch,
):
    from app.core import storage

    alice, _bob = users
    content = b"generated export"
    asset = _asset(
        db_session,
        owner=alice,
        asset_id="fa_download_s3",
        storage_uri="s3://private-test-bucket/users/alice/secret-object.md",
        size_bytes=len(content),
    )
    body = _ObjectBody(content)
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(storage.settings, "S3_BUCKET_NAME", "private-test-bucket")
    monkeypatch.setattr(
        storage.s3_client,
        "get_object",
        lambda *, Bucket, Key: calls.append((Bucket, Key)) or {"Body": body},
    )

    response = client.get(f"/api/v1/file-assets/{asset.id}/download")

    assert response.status_code == 200
    assert response.content == content
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "filename*=UTF-8''" in response.headers["content-disposition"]
    assert calls == [("private-test-bucket", "users/alice/secret-object.md")]
    assert body.closed is True
    response_metadata = repr(dict(response.headers))
    assert asset.storage_uri not in response_metadata
    assert asset.object_key not in response_metadata


def test_upload_reservation_does_not_expose_storage_locator(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        file_assets_api,
        "create_file_asset",
        lambda *_args, **_kwargs: (
            SimpleNamespace(
                id="fa_reserved",
                original_filename="resume.pdf",
                storage_uri="s3://private-bucket/uploads/1/fa_reserved/resume.pdf",
                object_key="uploads/1/fa_reserved/resume.pdf",
            ),
            {
                "upload_url": "https://storage.example/presigned-secret",
                "storage_uri": "s3://private-bucket/uploads/1/fa_reserved/resume.pdf",
                "object_key": "uploads/1/fa_reserved/resume.pdf",
            },
        ),
    )

    response = client.post(
        "/api/v1/file-assets/upload-url",
        json={
            "purpose": "resume",
            "filename": "resume.pdf",
            "content_type": "application/pdf",
            "size_bytes": 1_024,
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "file_asset_id": "fa_reserved",
        "upload_url": "https://storage.example/presigned-secret",
        "filename": "resume.pdf",
    }
    assert "storage_uri" not in response.text
    assert "object_key" not in response.text


def test_download_is_owner_scoped_and_rejects_unreadable_lifecycle_states(
    client: TestClient,
    db_session: Session,
    users: tuple[User, User],
    monkeypatch: pytest.MonkeyPatch,
):
    from app.core import storage

    alice, bob = users
    other_owner = _asset(
        db_session,
        owner=bob,
        asset_id="fa_download_other",
        storage_uri="s3://private-test-bucket/bob/private.txt",
    )
    unvalidated = _asset(
        db_session,
        owner=alice,
        asset_id="fa_download_unvalidated",
        storage_uri="s3://private-test-bucket/alice/unvalidated.txt",
        validation_status="pending",
    )
    deleted = _asset(
        db_session,
        owner=alice,
        asset_id="fa_download_deleted",
        storage_uri="s3://private-test-bucket/alice/deleted.txt",
        deleted=True,
    )
    monkeypatch.setattr(
        storage.s3_client,
        "get_object",
        lambda **_kwargs: pytest.fail("unreadable asset reached object storage"),
    )

    for asset in (other_owner, unvalidated, deleted):
        response = client.get(f"/api/v1/file-assets/{asset.id}/download")
        assert response.status_code == 404
        assert response.json() == {"detail": "文件资产不存在或不可下载"}


def test_download_serves_only_validated_local_uri_under_storage_root(
    client: TestClient,
    db_session: Session,
    users: tuple[User, User],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    from app.core.config import settings

    alice, _bob = users
    export_dir = tmp_path / "exports"
    export_dir.mkdir()
    export_path = export_dir / "result.txt"
    export_path.write_bytes(b"local export")
    monkeypatch.setattr(settings, "STORAGE_DIR", str(tmp_path))
    safe = _asset(
        db_session,
        owner=alice,
        asset_id="fa_download_local",
        storage_uri="local://exports/result.txt",
        filename="result.txt",
        size_bytes=12,
    )
    unsafe = _asset(
        db_session,
        owner=alice,
        asset_id="fa_download_unsafe_local",
        storage_uri="local://../outside.txt",
        filename="outside.txt",
    )

    response = client.get(f"/api/v1/file-assets/{safe.id}/download")
    assert response.status_code == 200
    assert response.content == b"local export"
    assert response.headers["cache-control"] == "private, no-store"
    assert str(tmp_path) not in repr(dict(response.headers))

    rejected = client.get(f"/api/v1/file-assets/{unsafe.id}/download")
    assert rejected.status_code == 404
    assert rejected.json() == {"detail": "文件资产不可下载"}
