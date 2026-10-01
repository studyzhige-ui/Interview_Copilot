"""Filesystem-default provider and optional S3 regression contracts."""

from io import BytesIO
from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError
from app.core import storage


@pytest.fixture(autouse=True)
def root(monkeypatch, tmp_path):
    monkeypatch.setattr(storage.settings, "STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(storage.settings, "STORAGE_BACKEND", "filesystem")
    monkeypatch.setattr(storage.settings, "STORAGE_MIN_FREE_BYTES", 0)
    monkeypatch.setattr(
        storage.settings, "AWS_ENDPOINT_URL", "https://s3.example.invalid"
    )
    monkeypatch.setattr(storage.settings, "AWS_ACCESS_KEY_ID", "synthetic")
    monkeypatch.setattr(storage.settings, "AWS_SECRET_ACCESS_KEY", "synthetic")
    return tmp_path


def test_local_atomic_immutable_roundtrip(root):
    uri = storage.upload_file_to_owned_key(BytesIO(b"bytes"), "uploads/1/fa_a/a.txt")
    assert uri == "local://uploads/1/fa_a/a.txt"
    assert storage.head_object(uri)["size_bytes"] == 5
    assert storage.read_object_head(uri) == b"bytes"
    with pytest.raises(FileExistsError):
        storage.upload_file_to_owned_key(BytesIO(b"changed"), "uploads/1/fa_a/a.txt")
    assert storage.read_object_head(uri) == b"bytes"
    with storage.materialize_object(uri) as path:
        from pathlib import Path

        assert Path(path).read_bytes() == b"bytes"
    assert not Path(path).exists()
    storage.delete_object(uri)
    storage.delete_object(uri)
    assert storage.head_object(uri) is None
    assert not list(root.rglob(".upload-*"))


@pytest.mark.parametrize(
    "key", ["../x", "/x", "a/../x", "a//x", "a/./x", "a\\x", "a\x00x"]
)
def test_reject_traversal(key):
    with pytest.raises(ValueError):
        storage.upload_file_to_owned_key(BytesIO(b"x"), key)


def test_reject_symlink(root):
    (root / "real").mkdir()
    (root / "link").symlink_to(root / "real", target_is_directory=True)
    with pytest.raises(ValueError):
        storage.upload_file_to_owned_key(BytesIO(b"x"), "link/a.txt")


def test_s3_optional_create_only_and_no_fallback(monkeypatch, root):
    monkeypatch.setattr(storage.settings, "STORAGE_BACKEND", "s3")
    client = MagicMock()
    monkeypatch.setattr(storage, "s3_client", client)
    uri = storage.upload_file_to_owned_key(BytesIO(b"x"), "uploads/1/fa_a/a.txt")
    assert uri.startswith("s3://")
    assert client.put_object.call_args.kwargs["IfNoneMatch"] == "*"
    client.put_object.side_effect = ClientError(
        {"Error": {"Code": "ServiceUnavailable"}}, "PutObject"
    )
    with pytest.raises(ClientError):
        storage.upload_file_to_owned_key(BytesIO(b"x"), "uploads/1/fa_b/a.txt")
    assert not list(root.iterdir())


def test_s3_persisted_uri_ignores_default_and_closes_body(monkeypatch):
    client = MagicMock()
    monkeypatch.setattr(storage, "s3_client", client)
    client.head_object.return_value = {"ContentLength": 5, "ContentType": "text/plain"}
    body = BytesIO(b"bytes")
    client.get_object.return_value = {"Body": body}
    uri = f"s3://{storage.settings.S3_BUCKET_NAME}/uploads/1/fa_a/a.txt"
    assert storage.head_object(uri)["size_bytes"] == 5
    assert storage.read_object_head(uri) == b"bytes"
    assert body.closed


def test_storage_outage_is_not_missing(monkeypatch):
    client = MagicMock()
    monkeypatch.setattr(storage, "s3_client", client)
    client.head_object.side_effect = ClientError(
        {"Error": {"Code": "503"}}, "HeadObject"
    )
    with pytest.raises(ClientError):
        storage.head_object(
            f"s3://{storage.settings.S3_BUCKET_NAME}/uploads/1/fa_a/a.txt"
        )


def test_create_only_s3_signing_client(monkeypatch):
    signer = MagicMock()
    monkeypatch.setattr(storage, "s3_signing_client", signer)
    storage.generate_presigned_upload_url_for_key("uploads/1/fa_a/a.txt")
    assert (
        signer.generate_presigned_url.call_args.kwargs["Params"]["IfNoneMatch"] == "*"
    )


def test_missing_s3_configuration_never_initializes_client(monkeypatch):
    monkeypatch.setattr(storage.settings, "AWS_ENDPOINT_URL", "")
    monkeypatch.setattr(
        storage.boto3,
        "client",
        lambda *a, **k: pytest.fail("must not probe any endpoint"),
    )
    client = storage._LazyS3Client()
    with pytest.raises(storage.StorageConfigurationError, match="AWS_ENDPOINT_URL"):
        client.head_object(Bucket="unused", Key="unused")


def test_special_files_rejected_without_blocking(root):
    import os

    os.mkfifo(root / "fifo")
    with pytest.raises(ValueError, match="regular"):
        storage.head_object("local://fifo")


def test_empty_s3_head_handles_invalid_range(monkeypatch):
    client = MagicMock()
    monkeypatch.setattr(storage, "s3_client", client)
    client.get_object.side_effect = ClientError(
        {"Error": {"Code": "InvalidRange"}}, "GetObject"
    )
    client.head_object.return_value = {"ContentLength": 0}
    uri = f"s3://{storage.settings.S3_BUCKET_NAME}/uploads/1/fa_a/empty.txt"
    assert storage.read_object_head(uri) == b""
    client.head_object.return_value = {"ContentLength": 3}
    with pytest.raises(ClientError):
        storage.read_object_head(uri)
