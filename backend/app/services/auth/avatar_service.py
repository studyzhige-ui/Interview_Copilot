"""Avatar storage business logic: validation, URL translation, cleanup.

The avatar bytes go straight to object storage via the unified presigned
flow, so the server never sees them at upload time. Everything here runs
at *set*-time (magic-byte check on the object head) or *read*-time
(translating the stored URI into a browser-fetchable URL).
"""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy.orm import Session

from app.core.storage import (
    delete_local_uri,
    delete_s3_object,
    generate_presigned_get_url,
    is_local_uri,
)
from app.db.types import utc_now
from app.models.user import User
from app.services.uploads.file_asset_service import UPLOAD_STATUS_DELETED

logger = logging.getLogger(__name__)

# Avatar safety limits — validated at set-time against the uploaded object.
#   * content-type restricted to four common image MIMEs
#   * 1 MiB hard cap (matches the file_assets 'avatar' purpose limit)
#   * magic-byte verification on the object head — keeps a renamed executable
#     from riding a permissive image/png MIME onto the user row
AVATAR_MAX_BYTES = 1024 * 1024
AVATAR_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}

# Each entry: list of valid magic-byte prefixes for the format. WEBP also
# requires the bytes 8..12 to equal "WEBP" since 4..8 is the file size.
_MAGIC_PREFIXES: dict[str, tuple[bytes, ...]] = {
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/gif": (b"GIF87a", b"GIF89a"),
    # WEBP is RIFF + "WEBP" 4 bytes later; handled specially below.
    "image/webp": (b"RIFF",),
}

_LOCAL_AVATAR_URI_PREFIX = "local://avatars/"
_LOCAL_AVATAR_STATIC_PATH = "/api/v1/static/avatars/"


def matches_magic(content_type: str, body: bytes) -> bool:
    """True iff ``body`` actually starts with the magic bytes for ``content_type``."""
    prefixes = _MAGIC_PREFIXES.get(content_type)
    if not prefixes:
        return False
    if content_type == "image/webp":
        # RIFF<size:4>WEBP<...>  — guard against the size bytes being anything.
        return len(body) >= 12 and body[:4] == b"RIFF" and body[8:12] == b"WEBP"
    return any(body.startswith(p) for p in prefixes)


def read_object_head(storage_uri: str, n: int = 32) -> bytes:
    """Read the first ``n`` bytes of an S3 object.

    Used to magic-byte-validate an avatar uploaded via the presigned flow: the
    bytes went straight to object storage, so the server reads the head here to
    confirm the declared image type matches the real content.
    """
    from app.core.storage import parse_s3_uri, s3_client

    bucket, key = parse_s3_uri(storage_uri)
    obj = s3_client.get_object(Bucket=bucket, Key=key, Range=f"bytes=0-{n - 1}")
    return obj["Body"].read()


def public_avatar_url(user: User) -> Optional[str]:
    """Translate the stored ``avatar_url`` to a browser-fetchable URL.

    Three storage shapes are supported:
      * ``s3://bucket/...``           → presigned GET URL (15-min TTL); the
        browser fetches bytes straight from S3 / MinIO.
      * ``local://avatars/<rel>...``  → ``/api/v1/static/avatars/<rel>`` —
        S3-fallback storage, served by FastAPI's StaticFiles mount.
      * ``http(s)://...``              → user-supplied public URL, verbatim.
      * ``None`` / ``""``              → no avatar.
    """
    raw = (user.avatar_url or "").strip()
    if not raw:
        return None
    if raw.startswith("s3://"):
        try:
            return generate_presigned_get_url(raw, expiration=900)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Presign avatar GET failed for user=%s: %s",
                user.username,
                exc,
            )
            return None
    if raw.startswith(_LOCAL_AVATAR_URI_PREFIX):
        # Strip the ``local://avatars/`` prefix and prepend the static mount
        # so the browser hits FastAPI for the bytes. URL-quote the segments
        # so spaces / unicode in usernames don't break the route.
        rel_under_mount = raw[len(_LOCAL_AVATAR_URI_PREFIX) :]
        from urllib.parse import quote

        return f"{_LOCAL_AVATAR_STATIC_PATH}{quote(rel_under_mount, safe='/')}"
    if raw.startswith("http://") or raw.startswith("https://"):
        return raw
    # Anything else (e.g. ``local://resumes/...``, a stray absolute path) is
    # not avatar-shaped — refuse rather than leak server-internal URIs.
    logger.warning(
        "Unrecognized avatar_url scheme for user=%s: %r",
        user.username,
        raw[:32],
    )
    return None


def delete_previous_avatar(previous_uri: str) -> None:
    """Best-effort cleanup of whichever store the previous avatar lived in.

    Failure is logged but never re-raised — orphan blobs are an operational
    annoyance, not a correctness problem.
    """
    if not previous_uri:
        return
    if previous_uri.startswith("s3://"):
        try:
            delete_s3_object(previous_uri)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to delete previous avatar %s: %s", previous_uri, exc)
    elif is_local_uri(previous_uri):
        # ``delete_local_uri`` is already best-effort.
        delete_local_uri(previous_uri)
    # http(s):// / unknown — nothing on disk to clean.


def swap_avatar(db: Session, user: User, asset) -> None:
    """Point ``users.avatar_url`` at the validated asset and retire the old one.

    Marks the asset consumed, commits, then cleans up the REPLACED avatar —
    but never when re-setting the same asset (previous_uri == new
    storage_uri), which would delete the bytes we just pointed at. If the
    previous avatar was itself a file_asset, its row is soft-deleted so it
    doesn't linger as a 'consumed' asset pointing at deleted bytes.
    """
    from app.services.uploads.file_asset_service import mark_file_asset_consumed

    previous_uri = (user.avatar_url or "").strip()
    user.avatar_url = asset.storage_uri
    mark_file_asset_consumed(db, asset)
    db.add(user)
    db.commit()
    db.refresh(user)

    if previous_uri and previous_uri != asset.storage_uri:
        from app.models.file_asset import FileAsset

        prev = (
            db.query(FileAsset)
            .filter(
                FileAsset.user_id == user.id,
                FileAsset.storage_uri == previous_uri,
            )
            .first()
        )
        if prev is not None:
            prev.upload_status = UPLOAD_STATUS_DELETED
            prev.deleted_at = utc_now()
            db.add(prev)
            db.commit()
        delete_previous_avatar(previous_uri)
