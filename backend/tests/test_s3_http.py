"""Opt-in real S3 protocol contract; never uses a user's object key."""

import io
import os
import uuid

import boto3
import pytest
from botocore.config import Config
from botocore.exceptions import ClientError


def test_create_only_storage_and_range_over_http(monkeypatch):
    endpoint = os.environ.get("TEST_S3_ENDPOINT")
    if not endpoint:
        if os.environ.get("REQUIRE_TEST_S3") == "1":
            pytest.fail("TEST_S3_ENDPOINT is required")
        pytest.skip("explicit disposable S3 fixture required")
    from app.core import storage

    bucket = os.environ["TEST_S3_BUCKET"]
    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=os.environ["TEST_S3_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["TEST_S3_SECRET_ACCESS_KEY"],
        region_name="us-east-1",
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )
    try:
        client.head_bucket(Bucket=bucket)
    except ClientError as exc:
        if exc.response["ResponseMetadata"]["HTTPStatusCode"] != 404:
            raise
        client.create_bucket(Bucket=bucket)
    monkeypatch.setattr(storage, "s3_client", client)
    monkeypatch.setattr(storage.settings, "S3_BUCKET_NAME", bucket)
    uri = f"s3://{bucket}/contract-tests/{uuid.uuid4().hex}"
    try:
        storage.store_object(io.BytesIO(b"original-bytes"), uri)
        assert storage.head_object(uri)["size_bytes"] == 14
        with storage.open_object(uri, start=2, end=5) as stream:
            assert stream.read() == b"igin"
        with pytest.raises((ClientError, FileExistsError)):
            storage.store_object(io.BytesIO(b"replacement"), uri)
        with storage.open_object(uri) as stream:
            assert stream.read() == b"original-bytes"
    finally:
        storage.delete_object(uri)
    assert storage.head_object(uri) is None
