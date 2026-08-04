import logging
import os
import re
from pathlib import Path

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import settings

logger = logging.getLogger(__name__)

s3_client = boto3.client(
    "s3",
    aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
    aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
    region_name=settings.AWS_REGION,
    endpoint_url=settings.AWS_ENDPOINT_URL,
)

_public_endpoint = settings.S3_PUBLIC_ENDPOINT_URL.strip()
s3_signing_client = (
    boto3.client(
        "s3",
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        region_name=settings.AWS_REGION,
        endpoint_url=_public_endpoint,
    )
    if _public_endpoint and _public_endpoint != settings.AWS_ENDPOINT_URL
    else s3_client
)


def sanitize_filename(filename: str) -> str:
    """Return a path-safe display filename while keeping a useful extension."""
    name = Path(filename or "upload.bin").name
    stem, ext = os.path.splitext(name)
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._") or "upload"
    ext = re.sub(r"[^A-Za-z0-9.]+", "", ext)[:16]
    return f"{stem[:80]}{ext or '.bin'}"


def build_owned_object_key(user_id: str, upload_id: str, filename: str) -> str:
    safe_user = re.sub(r"[^A-Za-z0-9._-]+", "_", user_id).strip("._")
    if not safe_user:
        raise ValueError("Invalid user id for storage key")
    return f"uploads/{safe_user}/{upload_id}/{sanitize_filename(filename)}"


def parse_s3_uri(s3_uri: str) -> tuple[str, str]:
    if not s3_uri.startswith("s3://"):
        raise ValueError(f"Invalid s3 URI: {s3_uri}")
    parts = s3_uri.replace("s3://", "").split("/", 1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ValueError(f"Unable to parse S3 URI: {s3_uri}")
    return parts[0], parts[1]


def storage_uri_for_key(object_key: str) -> str:
    return f"s3://{settings.S3_BUCKET_NAME}/{object_key}"


def generate_presigned_upload_url_for_key(
    object_key: str,
    content_type: str = "application/octet-stream",
    expiration: int = 3600,
) -> dict:
    """Generate a presigned URL for an already-owned object key."""
    try:
        response = s3_signing_client.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": settings.S3_BUCKET_NAME,
                "Key": object_key,
                "ContentType": content_type or "application/octet-stream",
            },
            ExpiresIn=expiration,
        )

        file_url = storage_uri_for_key(object_key)
        logger.info("Generated presigned upload URL for %s", file_url)

        return {
            "upload_url": response,
            "file_path": file_url,
            "storage_uri": file_url,
            "object_key": object_key,
        }
    except ClientError as exc:
        logger.error("Failed to generate S3 presigned upload URL: %s", exc)
        raise


def download_file_from_s3(s3_uri: str, local_path: str):
    """Download an S3 URI to a local worker path."""
    bucket, key = parse_s3_uri(s3_uri)
    try:
        logger.info("[Worker] Downloading %s to %s", s3_uri, local_path)
        s3_client.download_file(bucket, key, local_path)
        logger.info("[Worker] S3 download completed.")
    except ClientError as exc:
        logger.error("[Worker] S3 download failed: %s", exc)
        raise


def generate_presigned_get_url(s3_uri: str, expiration: int = 600) -> str:
    """Build a short-lived presigned GET URL for ``s3_uri``.

    Used by endpoints that 307-redirect the browser straight to S3/MinIO
    (avatar render, etc) so the byte stream never traverses the FastAPI
    process. Default 10 min — long enough that the browser can also reuse
    the cached image without us re-signing on every page nav, short enough
    that a leaked URL goes stale fast.
    """
    bucket, key = parse_s3_uri(s3_uri)
    return s3_signing_client.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": key},
        ExpiresIn=expiration,
    )


def head_object(storage_uri: str) -> dict | None:
    """Return ``{size_bytes, content_type}`` for a stored object, or ``None``
    if it doesn't exist. Used by the file-asset confirm step to prove the
    client actually completed the presigned PUT before a business object
    consumes the asset. Supports ``s3://`` and ``local://`` URIs.
    """
    if is_local_uri(storage_uri):
        try:
            local_path = parse_local_uri(storage_uri)
        except ValueError:
            return None
        if not local_path.is_file():
            return None
        return {"size_bytes": local_path.stat().st_size, "content_type": None}
    try:
        bucket, key = parse_s3_uri(storage_uri)
        resp = s3_client.head_object(Bucket=bucket, Key=key)
        return {
            "size_bytes": resp.get("ContentLength"),
            "content_type": resp.get("ContentType"),
        }
    except (ClientError, BotoCoreError):
        # Missing key (404) OR a transient storage outage — either way the
        # object isn't confirmable right now. Caller treats None as "not
        # present"; the user re-uploads on a genuine outage.
        return None


def read_object_head(storage_uri: str, num_bytes: int = 32) -> bytes | None:
    """Read the first ``num_bytes`` of a stored object, or ``None`` if it
    doesn't exist / isn't reachable. Used by the confirm/consume-time
    magic-byte check — 32 bytes covers every signature file_validation
    recognises. Supports ``s3://`` (ranged GET) and ``local://`` URIs.
    """
    if is_local_uri(storage_uri):
        try:
            local_path = parse_local_uri(storage_uri)
        except ValueError:
            return None
        if not local_path.is_file():
            return None
        try:
            with open(local_path, "rb") as f:
                return f.read(num_bytes)
        except OSError:
            return None
    try:
        bucket, key = parse_s3_uri(storage_uri)
        resp = s3_client.get_object(
            Bucket=bucket,
            Key=key,
            Range=f"bytes=0-{num_bytes - 1}",
        )
        return resp["Body"].read()
    except (ClientError, BotoCoreError, ValueError):
        return None


def delete_s3_object(storage_uri: str) -> None:
    bucket, key = parse_s3_uri(storage_uri)
    if bucket != settings.S3_BUCKET_NAME:
        raise ValueError("Refusing to delete object outside configured bucket")
    s3_client.delete_object(Bucket=bucket, Key=key)


def upload_file_to_owned_key(
    file_obj, object_key: str, content_type: str | None = None
) -> str:
    """Upload a file object to a pre-created owned object key.

    Returns the URI the bytes actually landed at: ``s3://…`` normally, or a
    ``local://…`` URI when S3 is unreachable and the write fell back to local
    disk. Callers MUST persist the returned URI — recording the planned
    ``s3://`` URI while the bytes sit on local disk makes every later read
    fail (UP-8).
    """
    try:
        s3_client.upload_fileobj(
            file_obj,
            settings.S3_BUCKET_NAME,
            object_key,
            ExtraArgs={"ContentType": content_type or "application/octet-stream"},
        )
        return storage_uri_for_key(object_key)
    except ClientError as exc:
        logger.error("S3 upload failed, falling back to local storage: %s", exc)
        return _fallback_local_save(file_obj, object_key)
    except Exception as exc:  # noqa: BLE001
        logger.warning("S3 client unavailable, falling back to local storage: %s", exc)
        return _fallback_local_save(file_obj, object_key)


def _fallback_local_save(file_obj, relative_path: str) -> str:
    """Write the upload to local disk when S3 isn't reachable; return its
    ``local://`` URI rather than an absolute filesystem path.

    Hardened against path traversal: even though ``relative_path`` is
    constructed internally by ``build_owned_object_key`` (which sanitises
    inputs), a future caller could pass an attacker-influenced key. We
    resolve the final destination and assert it stays under STORAGE_DIR.
    """
    import shutil
    from pathlib import Path

    base_dir = Path(settings.STORAGE_DIR).resolve()
    # Reject absolute paths up-front; ``base / abs`` silently discards
    # ``base`` on POSIX, which is exactly the traversal we want to block.
    candidate = Path(relative_path)
    if candidate.is_absolute() or any(part == ".." for part in candidate.parts):
        raise ValueError(
            f"Refusing unsafe object key for local save: {relative_path!r}"
        )

    full_path = (base_dir / candidate).resolve()
    try:
        full_path.relative_to(base_dir)
    except ValueError as exc:
        raise ValueError(
            f"Refusing object key that resolves outside STORAGE_DIR: {relative_path!r}"
        ) from exc

    full_path.parent.mkdir(parents=True, exist_ok=True)
    file_obj.seek(0)
    with open(full_path, "wb") as f:
        shutil.copyfileobj(file_obj, f)
    normalised = str(candidate).replace(os.sep, "/")
    return f"{LOCAL_URI_PREFIX}{normalised}"


# ── local:// URI scheme ─────────────────────────────────────────────────
# When S3 is unreachable we still want a graceful-degradation path so an
# upload doesn't error out completely. The bytes land on local disk and
# we record a ``local://<rel_path>`` URI in DB instead of ``s3://...``.
# Downstream consumers that understand ``local://`` (the avatar serializer
# + the /static/avatars file mount) can serve the bytes without ever
# talking to S3.

LOCAL_URI_PREFIX = "local://"


def is_local_uri(uri: str | None) -> bool:
    return bool(uri) and uri.startswith(LOCAL_URI_PREFIX)


def _safe_relative(rel_path: str) -> Path:
    """Reject absolute paths, .. segments, and any input that would escape
    STORAGE_DIR. Returns the validated relative ``Path``.
    """
    if not rel_path:
        raise ValueError("Empty relative path")
    candidate = Path(rel_path)
    if candidate.is_absolute() or any(part == ".." for part in candidate.parts):
        raise ValueError(f"Unsafe relative path: {rel_path!r}")
    return candidate


def parse_local_uri(uri: str) -> Path:
    """``local://avatars/u/x.png`` → absolute ``Path`` under STORAGE_DIR.

    Raises ``ValueError`` if the URI is malformed or attempts to escape the
    storage root.
    """
    if not is_local_uri(uri):
        raise ValueError(f"Not a local URI: {uri!r}")
    rel = uri[len(LOCAL_URI_PREFIX) :].lstrip("/")
    candidate = _safe_relative(rel)
    base = Path(settings.STORAGE_DIR).resolve()
    full = (base / candidate).resolve()
    try:
        full.relative_to(base)
    except ValueError as exc:
        raise ValueError(f"local URI escapes STORAGE_DIR: {uri!r}") from exc
    return full


def delete_local_uri(uri: str) -> None:
    """Best-effort unlink of a ``local://`` URI. Missing files are a no-op."""
    if not is_local_uri(uri):
        return
    try:
        full = parse_local_uri(uri)
    except ValueError:
        return
    try:
        if full.is_file():
            full.unlink()
    except OSError as exc:
        logger.warning("Failed to delete local upload %s: %s", uri, exc)
