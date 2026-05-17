"""One-shot data migration: convert legacy ``data:image/...;base64`` avatars
to S3 blobs (or local-fallback files), updating ``users.avatar_url`` in place.

Usage
-----
From the project root:

    python scripts/migrate_avatars.py              # actually migrate
    python scripts/migrate_avatars.py --dry-run    # just count + report

Safe to re-run: idempotent on rows that have already been migrated (they
won't match the ``data:`` predicate anymore). Each row is committed
individually so a mid-run crash leaves a consistent DB.

Why a script, not a startup hook
--------------------------------
Doing this at every uvicorn boot means scanning the table + S3 round-trips
on each restart — wasteful and inflates startup time. Doing it inside an
alembic migration runs in a context that can't easily talk to S3 (different
env, no app settings). A standalone script the operator runs once during
the deploy that introduces the new avatar code is cleanest.
"""

from __future__ import annotations

import argparse
import base64
import logging
import re
import sys
import uuid
from pathlib import Path
from typing import Iterable

# Make ``app.*`` importable when the script lives outside backend/.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.db.database import SessionLocal
from app.models.user import User
from app.services.storage_service import (
    save_blob_to_local,
    s3_client,
    storage_uri_for_key,
)
from app.core.config import settings

logger = logging.getLogger("migrate_avatars")


# Same MIME → ext map as auth.py, kept private so changes there don't drift.
_EXT_BY_MIME = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
}

_DATA_URL_RE = re.compile(
    r"^data:(?P<mime>image/(?:png|jpeg|webp|gif));base64,(?P<b64>[A-Za-z0-9+/=\s]+)$"
)


def _avatar_object_key(username: str, mime: str) -> str:
    """Mirror of auth.py._avatar_object_key (kept independent so this script
    keeps working if the API module evolves)."""
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", username).strip("._") or "anon"
    ext = _EXT_BY_MIME.get(mime, ".bin")
    return f"avatars/{safe}/{uuid.uuid4().hex}{ext}"


def _store_blob(body: bytes, object_key: str, mime: str, username: str) -> str:
    """Try S3 first, fall back to local. Mirrors the runtime path in auth.py."""
    import io
    try:
        s3_client.upload_fileobj(
            io.BytesIO(body),
            settings.S3_BUCKET_NAME,
            object_key,
            ExtraArgs={"ContentType": mime},
        )
        return storage_uri_for_key(object_key)
    except Exception as exc:  # noqa: BLE001
        logger.warning("S3 unavailable for user=%s, using local fallback: %s", username, exc)
    return save_blob_to_local(body, object_key)


def _iter_data_url_users(session) -> Iterable[User]:
    """Yield users whose ``avatar_url`` is still in legacy ``data:`` form."""
    return (
        session.query(User)
        .filter(User.avatar_url.isnot(None))
        .filter(User.avatar_url.like("data:%"))
        .yield_per(50)
    )


def migrate(dry_run: bool = False) -> tuple[int, int, int]:
    """Return ``(scanned, migrated, skipped)``.

    ``skipped`` counts rows whose payload couldn't be decoded (malformed
    base64, missing MIME, etc) — they stay as-is and are logged so an
    operator can audit them manually.
    """
    scanned = migrated = skipped = 0
    with SessionLocal() as session:
        for user in _iter_data_url_users(session):
            scanned += 1
            raw = (user.avatar_url or "").strip()
            m = _DATA_URL_RE.match(raw)
            if not m:
                logger.warning(
                    "user=%s avatar_url is data: but doesn't match expected shape; skipping",
                    user.username,
                )
                skipped += 1
                continue

            mime = m.group("mime")
            try:
                body = base64.b64decode(m.group("b64"), validate=True)
            except (ValueError, base64.binascii.Error) as exc:
                logger.warning("user=%s base64 decode failed: %s; skipping", user.username, exc)
                skipped += 1
                continue

            if not body:
                logger.warning("user=%s decoded body is empty; skipping", user.username)
                skipped += 1
                continue

            object_key = _avatar_object_key(user.username, mime)
            if dry_run:
                logger.info(
                    "[dry-run] would migrate user=%s (%d bytes, %s) → %s",
                    user.username, len(body), mime, object_key,
                )
                migrated += 1
                continue

            new_uri = _store_blob(body, object_key, mime, user.username)
            user.avatar_url = new_uri
            session.add(user)
            session.commit()
            migrated += 1
            logger.info("user=%s migrated → %s", user.username, new_uri)

    return scanned, migrated, skipped


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Migrate legacy data: URL avatars to S3 / local.")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="List rows that would be migrated without writing anything.",
    )
    parser.add_argument(
        "--log-level", default="INFO",
        help="Python logging level (DEBUG / INFO / WARNING / ERROR). Default: INFO.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    scanned, migrated, skipped = migrate(dry_run=args.dry_run)
    print(
        f"\n=== avatar migration {'(dry-run)' if args.dry_run else ''}: "
        f"scanned={scanned}, migrated={migrated}, skipped={skipped} ==="
    )
    return 0 if skipped == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
