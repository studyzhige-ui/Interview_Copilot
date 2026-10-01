"""Private immutable object storage. Dispatch reads by persisted URI, never defaults.

The filesystem provider shares STORAGE_DIR between API and workers. S3 is optional;
its clients are lazy so local startup neither probes nor requires an object store.
Ownership and lifecycle belong to the FileAsset application service.
"""

from __future__ import annotations

from contextlib import contextmanager
import logging
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile
import time
import uuid

import boto3
from botocore.exceptions import ClientError

from app.core.config import settings

logger = logging.getLogger(__name__)
LOCAL_URI_PREFIX = "local://"
MAX_OBJECT_BYTES = 500 * 1024 * 1024


class StorageConfigurationError(RuntimeError):
    """A persisted S3 object needs explicit operator configuration."""


def validate_s3_configuration():
    required = (
        "AWS_ENDPOINT_URL",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "S3_BUCKET_NAME",
    )
    missing = [
        name for name in required if not str(getattr(settings, name) or "").strip()
    ]
    if missing:
        raise StorageConfigurationError("S3 存储未配置，请设置 " + "、".join(missing))
    from urllib.parse import urlsplit

    endpoint = urlsplit(settings.AWS_ENDPOINT_URL)
    if endpoint.scheme not in {"http", "https"} or not endpoint.hostname:
        raise StorageConfigurationError("S3 存储地址无效，请检查 AWS_ENDPOINT_URL")


class _LazyS3Client:
    def __init__(self, public=False):
        self.public = public
        self.client = None

    def __getattr__(self, name):
        if self.client is None:
            validate_s3_configuration()
            from botocore.config import Config

            self.client = boto3.client(
                "s3",
                aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
                region_name=settings.AWS_REGION,
                endpoint_url=(
                    settings.S3_PUBLIC_ENDPOINT_URL.strip() if self.public else ""
                )
                or settings.AWS_ENDPOINT_URL,
                config=Config(
                    connect_timeout=5,
                    read_timeout=10,
                    retries={"total_max_attempts": 1},
                ),
            )
        return getattr(self.client, name)


s3_client = _LazyS3Client()
s3_signing_client = _LazyS3Client(public=True)


def sanitize_filename(filename: str) -> str:
    name = Path(filename or "upload.bin").name
    stem, ext = os.path.splitext(name)
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._") or "upload"
    ext = re.sub(r"[^A-Za-z0-9.]+", "", ext)[:16]
    return f"{stem[:80]}{ext or '.bin'}"


def build_owned_object_key(user_id: str, upload_id: str, filename: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", str(user_id)) or not re.fullmatch(
        r"[A-Za-z0-9_-]+", upload_id
    ):
        raise ValueError("Invalid storage identity")
    return f"uploads/{user_id}/{upload_id}/{sanitize_filename(filename)}"


def _safe_relative(key: str) -> Path:
    if not key or "\\" in key or "\x00" in key or key.startswith("/"):
        raise ValueError("Unsafe object key")
    if any(part in {"", ".", ".."} for part in key.split("/")):
        raise ValueError("Unsafe object key")
    return Path(*PurePosixPath(key).parts)


def parse_s3_uri(uri: str) -> tuple[str, str]:
    if not uri.startswith("s3://"):
        raise ValueError("Invalid S3 URI")
    parts = uri[5:].split("/", 1)
    if len(parts) != 2 or not parts[0] or parts[0] != settings.S3_BUCKET_NAME:
        raise ValueError("Object outside configured bucket")
    _safe_relative(parts[1])
    return parts[0], parts[1]


def object_key_from_uri(uri: str) -> str:
    if is_local_uri(uri):
        key = uri[len(LOCAL_URI_PREFIX) :]
        _safe_relative(key)
        return key
    return parse_s3_uri(uri)[1]


def storage_uri_for_key(object_key: str) -> str:
    _safe_relative(object_key)
    if settings.STORAGE_BACKEND == "filesystem":
        return f"{LOCAL_URI_PREFIX}{object_key}"
    validate_s3_configuration()
    return f"s3://{settings.S3_BUCKET_NAME}/{object_key}"


def is_local_uri(uri: str | None) -> bool:
    return bool(uri) and uri.startswith(LOCAL_URI_PREFIX)


def parse_local_uri(uri: str) -> Path:
    if not is_local_uri(uri):
        raise ValueError("Not a local URI")
    candidate = _safe_relative(uri[len(LOCAL_URI_PREFIX) :])
    root = Path(settings.STORAGE_DIR).absolute()
    # Reject symlinks even when they happen to resolve inside the root.
    current = root
    for part in candidate.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("Symlink in object path")
    if root.is_symlink() or root.resolve() != root:
        raise ValueError("Symlink storage root")
    return root / candidate


@contextmanager
def _parent_fd(uri: str, *, create=False):
    """Walk with openat/O_NOFOLLOW; pin directories against symlink swaps."""
    path = parse_local_uri(uri)
    root = Path(settings.STORAGE_DIR).absolute()
    if create:
        root.mkdir(parents=True, exist_ok=True)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open(root, flags)
    try:
        for part in path.relative_to(root).parts[:-1]:
            if create:
                try:
                    os.mkdir(part, mode=0o700, dir_fd=fd)
                except FileExistsError:
                    pass
            child = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = child
        yield fd, path.name
    finally:
        os.close(fd)


@contextmanager
def open_local_object(uri: str):
    with _parent_fd(uri) as (parent, name):
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    with os.fdopen(fd, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError("Object is not a regular file")
        yield stream


def head_object(uri: str) -> dict | None:
    if is_local_uri(uri):
        try:
            with open_local_object(uri) as stream:
                return {
                    "size_bytes": os.fstat(stream.fileno()).st_size,
                    "content_type": None,
                }
        except FileNotFoundError:
            return None
    bucket, key = parse_s3_uri(uri)
    try:
        result = s3_client.head_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        if str(exc.response.get("Error", {}).get("Code")) in {
            "404",
            "NoSuchKey",
            "NotFound",
        }:
            return None
        raise
    return {
        "size_bytes": result["ContentLength"],
        "content_type": result.get("ContentType"),
    }


@contextmanager
def open_object(uri: str, *, start=0, end=None):
    if is_local_uri(uri):
        with open_local_object(uri) as stream:
            stream.seek(start)
            yield stream
    else:
        bucket, key = parse_s3_uri(uri)
        kwargs = {"Bucket": bucket, "Key": key}
        if start or end is not None:
            kwargs["Range"] = f"bytes={start}-{end if end is not None else ''}"
        result = s3_client.get_object(**kwargs)
        try:
            yield result["Body"]
        finally:
            result["Body"].close()


def read_object_head(uri: str, num_bytes: int = 32) -> bytes | None:
    if not 1 <= num_bytes <= MAX_OBJECT_BYTES:
        raise ValueError("Invalid bounded read size")
    try:
        with open_object(uri, end=num_bytes - 1) as stream:
            return stream.read(num_bytes)
    except FileNotFoundError:
        return None
    except ClientError as exc:
        if str(exc.response.get("Error", {}).get("Code")) in {"416", "InvalidRange"}:
            meta = head_object(uri)
            if meta is not None and meta["size_bytes"] == 0:
                return b""
        if str(exc.response.get("Error", {}).get("Code")) in {
            "404",
            "NoSuchKey",
            "NotFound",
        }:
            return None
        raise


def download_file_from_storage(
    uri: str, local_path: str, *, max_bytes=MAX_OBJECT_BYTES, deadline=None
):
    """Copy to a caller-owned temporary file with a hard byte bound."""
    size = head_object(uri)
    if size is None:
        raise FileNotFoundError("Object not found")
    if size["size_bytes"] > max_bytes:
        raise ValueError("Object exceeds read limit")
    total = 0
    try:
        with open_object(uri) as source, open(local_path, "wb") as target:
            while block := source.read(64 * 1024):
                if deadline is not None and time.monotonic() >= deadline:
                    raise TimeoutError("Object read deadline")
                total += len(block)
                if total > max_bytes or total > size["size_bytes"]:
                    raise ValueError("Object exceeds read limit")
                target.write(block)
        if total != size["size_bytes"]:
            raise ValueError("Incomplete object read")
    except BaseException:
        Path(local_path).unlink(missing_ok=True)
        raise


# Compatibility for external callers; URI dispatch is intentionally generic.
download_file_from_s3 = download_file_from_storage


def check_free_space(required_bytes=0):
    root = Path(settings.STORAGE_DIR)
    root.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(root).free < settings.STORAGE_MIN_FREE_BYTES + required_bytes:
        raise OSError(28, "Insufficient storage space")


def store_object(
    file_obj, uri: str, *, content_type=None, max_bytes=MAX_OBJECT_BYTES
) -> str:
    """Create-only atomic commit. Never overwrite bytes, including after confirm."""
    file_obj.seek(0, os.SEEK_END)
    size = file_obj.tell()
    file_obj.seek(0)
    if size > max_bytes:
        raise ValueError("Object exceeds write limit")
    if is_local_uri(uri):
        check_free_space(size)
        with _parent_fd(uri, create=True) as (parent, name):
            temporary = f".upload-{uuid.uuid4().hex}"
            fd = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=parent,
            )
            try:
                with os.fdopen(fd, "wb") as output:
                    shutil.copyfileobj(file_obj, output, 64 * 1024)
                    output.flush()
                    os.fsync(output.fileno())
                os.link(
                    temporary,
                    name,
                    src_dir_fd=parent,
                    dst_dir_fd=parent,
                    follow_symlinks=False,
                )
                os.fsync(parent)
            finally:
                os.unlink(temporary, dir_fd=parent)
    else:
        bucket, key = parse_s3_uri(uri)
        s3_client.put_object(
            Bucket=bucket,
            Key=key,
            Body=file_obj,
            ContentLength=size,
            ContentType=content_type or "application/octet-stream",
            IfNoneMatch="*",
        )
    return uri


def upload_file_to_owned_key(
    file_obj, object_key: str, content_type: str | None = None
) -> str:
    return store_object(
        file_obj, storage_uri_for_key(object_key), content_type=content_type
    )


def delete_local_uri(uri: str) -> None:
    try:
        with _parent_fd(uri) as (parent, name):
            # unlink removes the directory entry, never a symlink target.
            os.unlink(name, dir_fd=parent)
    except FileNotFoundError:
        pass


def delete_s3_object(uri: str) -> None:
    bucket, key = parse_s3_uri(uri)
    s3_client.delete_object(Bucket=bucket, Key=key)


def delete_object(uri: str) -> None:
    if is_local_uri(uri):
        delete_local_uri(uri)
    else:
        delete_s3_object(uri)


@contextmanager
def materialize_object(uri: str, *, max_bytes=MAX_OBJECT_BYTES, deadline=None):
    with tempfile.TemporaryDirectory(prefix="copilot-object-") as root:
        path = str(Path(root) / ("source" + Path(object_key_from_uri(uri)).suffix))
        download_file_from_storage(uri, path, max_bytes=max_bytes, deadline=deadline)
        yield path


def generate_presigned_get_url(uri: str, expiration: int = 600) -> str:
    bucket, key = parse_s3_uri(uri)
    return s3_signing_client.generate_presigned_url(
        "get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=expiration
    )


def generate_presigned_upload_url_for_key(
    object_key: str, content_type="application/octet-stream", expiration=3600
) -> dict:
    """Legacy adapter retained for integrations; first-party uploads use asset capabilities."""
    uri = f"s3://{settings.S3_BUCKET_NAME}/{object_key}"
    _safe_relative(object_key)
    url = s3_signing_client.generate_presigned_url(
        "put_object",
        Params={
            "Bucket": settings.S3_BUCKET_NAME,
            "Key": object_key,
            "ContentType": content_type,
            "IfNoneMatch": "*",
        },
        ExpiresIn=expiration,
    )
    return {
        "upload_url": url,
        "file_path": uri,
        "storage_uri": uri,
        "object_key": object_key,
    }
