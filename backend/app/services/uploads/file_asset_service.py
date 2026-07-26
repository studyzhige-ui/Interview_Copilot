"""Service layer for ``file_assets`` — the unified presigned upload flow.

Lifecycle:

    create_file_asset()   -> row (pending_upload / pending) + presigned PUT URL
                             (purpose whitelist + declared-size cap from
                             PURPOSE_REGISTRY; TTL per purpose)
    <client PUTs bytes to object storage>
    confirm_file_asset()  -> verify: object exists, size reconciles AND is
                             within the purpose cap, first bytes match the
                             purpose's content kind -> uploaded / passed
                             (or failed + enqueue object cleanup)
    <business consumes>    -> ensure_uploaded() (confirm-on-consume — runs the
                             same verification if the client skipped /confirm)
                             then mark_file_asset_consumed()

The explicit /confirm endpoint remains for the happy path (fail fast, client
sees the validation error immediately), but consumers no longer trust it to
have happened: ``ensure_uploaded`` makes verification unskippable (UP-1).

The table keys on the stable ``users.id``; callers still pass the runtime
principal (username), which this layer resolves once via
``app.core.user_identity.resolve_user_pk`` (same pattern as the model-config
services). Reads that already hold a trusted business object look an asset up
by id alone (``get_file_asset``); ownership-sensitive reads use
``get_owned_file_asset``.
"""

from __future__ import annotations

import logging

import os
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.user_identity import resolve_user_pk
from app.models.file_asset import FileAsset, generate_file_asset_id
from app.core.storage import (
    build_owned_object_key,
    generate_presigned_upload_url_for_key,
    head_object,
    read_object_head,
    storage_uri_for_key,
)
from app.services.uploads.purpose_registry import get_purpose_spec

logger = logging.getLogger(__name__)

# ── Upload-status vocabulary ─────────────────────────────────────────────
# Raw-file lifecycle on file_assets.upload_status. Import these instead of
# hardcoding the strings — same drift hazard the record STATUS_* constants
# exist to prevent.
UPLOAD_STATUS_PENDING = "pending_upload"
UPLOAD_STATUS_UPLOADED = "uploaded"
UPLOAD_STATUS_CONSUMED = "consumed"
UPLOAD_STATUS_FAILED = "failed"
UPLOAD_STATUS_DELETED = "deleted"
# Statuses whose bytes are verified and safe to read/consume.
READABLE_UPLOAD_STATUSES = (UPLOAD_STATUS_UPLOADED, UPLOAD_STATUS_CONSUMED)


class UnknownUploadPurpose(ValueError):
    """Purpose not in PURPOSE_REGISTRY."""


class UploadTooLarge(ValueError):
    """Declared size exceeds the purpose's cap."""

    def __init__(self, purpose: str, limit_bytes: int):
        self.purpose = purpose
        self.limit_bytes = limit_bytes
        super().__init__(f"upload for purpose={purpose} exceeds {limit_bytes} bytes")

    @property
    def limit_mb(self) -> int:
        return self.limit_bytes // (1024 * 1024)


def create_file_asset(
    db: Session,
    *,
    user_id: str,
    filename: str,
    purpose: str,
    content_type: str | None = None,
    size_bytes: int | None = None,
) -> tuple[FileAsset, dict]:
    """Reserve a file-asset row and return it plus a presigned PUT URL.

    Enforces the PURPOSE_REGISTRY whitelist and declared-size cap here — the
    single choke point every entry (file-assets API, rag.py knowledge URL,
    agent write_file) goes through. Raises ``UnknownUploadPurpose`` /
    ``UploadTooLarge`` accordingly.

    ``user_id`` is the caller's username; it's resolved to the stable
    ``users.id`` for the FK. Raises ``ValueError`` for an unknown user.
    """
    spec = get_purpose_spec(purpose)
    if spec is None:
        raise UnknownUploadPurpose(f"Unknown upload purpose: {purpose}")
    if size_bytes is not None and size_bytes > spec.max_bytes:
        raise UploadTooLarge(purpose, spec.max_bytes)

    user_pk = resolve_user_pk(db, user_id)
    if user_pk is None:
        raise ValueError(f"Unknown user: {user_id}")

    asset_id = generate_file_asset_id()
    # Object key namespaced by the stable id (opaque, stable across renames).
    object_key = build_owned_object_key(str(user_pk), asset_id, filename)
    storage_uri = storage_uri_for_key(object_key)
    asset = FileAsset(
        id=asset_id,
        user_id=user_pk,
        purpose=purpose,
        original_filename=filename,
        object_key=object_key,
        storage_uri=storage_uri,
        content_type=content_type or "application/octet-stream",
        size_bytes=size_bytes,
        upload_status=UPLOAD_STATUS_PENDING,
        validation_status="pending",
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    url_info = generate_presigned_upload_url_for_key(
        object_key,
        content_type=asset.content_type or "application/octet-stream",
        expiration=spec.presign_ttl_seconds,
    )
    return asset, url_info


def get_owned_file_asset(
    db: Session,
    *,
    file_asset_id: str,
    user_id: str,
    purpose: str | None = None,
) -> FileAsset | None:
    """Fetch an asset, enforcing ownership by the caller's username."""
    user_pk = resolve_user_pk(db, user_id)
    if user_pk is None:
        return None
    query = db.query(FileAsset).filter(
        FileAsset.id == file_asset_id,
        FileAsset.user_id == user_pk,
        FileAsset.deleted_at.is_(None),
    )
    if purpose:
        query = query.filter(FileAsset.purpose == purpose)
    return query.first()


def get_file_asset(db: Session, file_asset_id: str) -> FileAsset | None:
    """Fetch by id alone — for callers that already hold a trusted business
    object whose ownership was checked upstream (worker / orchestrator)."""
    return (
        db.query(FileAsset)
        .filter(FileAsset.id == file_asset_id, FileAsset.deleted_at.is_(None))
        .first()
    )


def list_user_file_assets(
    db: Session,
    *,
    user_id: str,
    purpose: str | None = None,
) -> list[FileAsset]:
    user_pk = resolve_user_pk(db, user_id)
    if user_pk is None:
        return []
    query = db.query(FileAsset).filter(
        FileAsset.user_id == user_pk,
        FileAsset.deleted_at.is_(None),
    )
    if purpose:
        query = query.filter(FileAsset.purpose == purpose)
    return query.order_by(FileAsset.created_at.desc()).all()


def confirm_file_asset(
    db: Session,
    *,
    file_asset_id: str,
    user_id: str,
) -> FileAsset | None:
    """Confirm a client-completed upload — delegates to
    ``_verify_pending_asset``. Returns the asset, or ``None`` if it isn't
    owned by the caller."""
    asset = get_owned_file_asset(db, file_asset_id=file_asset_id, user_id=user_id)
    if asset is None:
        return None
    return _verify_pending_asset(db, asset)


def ensure_uploaded(db: Session, asset: FileAsset) -> FileAsset:
    """Confirm-on-consume (UP-1): run the confirm verification if the client
    never called /confirm. Consumers call this and then require
    ``upload_status == "uploaded"`` — verification can no longer be skipped
    by consuming a ``pending_upload`` asset directly.
    """
    return _verify_pending_asset(db, asset)


def _verify_pending_asset(db: Session, asset: FileAsset) -> FileAsset:
    """Verify a pending upload and flip it uploaded/passed or failed/failed.

    Checks, in order:
      1. the object exists in storage (HEAD),
      2. its actual size reconciles with what the client declared,
      3. its actual size is within the purpose's registry cap — the declared
         size is client-controlled, so the cap must bind on actual bytes
         (UP-4),
      4. its first 32 bytes match the purpose's content kind (UP-6) — the
         presigned bytes never traverse this process, so this head read is
         the only server-side look at the content.

    On any failure the asset goes failed/failed and a cleanup job is enqueued
    in the SAME transaction so a half-uploaded object can't linger.
    Idempotent: an already-uploaded/consumed asset is returned untouched
    (never regresses), and a failed asset stays failed.
    """
    if asset.upload_status != UPLOAD_STATUS_PENDING:
        return asset

    meta = head_object(asset.storage_uri)
    if meta is None:
        _fail_asset(db, asset, "object not found in storage after upload")
        return asset

    actual_size = meta.get("size_bytes")
    if (
        asset.size_bytes is not None
        and actual_size is not None
        and actual_size != asset.size_bytes
    ):
        _fail_asset(
            db,
            asset,
            f"size mismatch: declared {asset.size_bytes}, stored {actual_size}",
        )
        return asset

    spec = get_purpose_spec(asset.purpose)
    if spec is not None and actual_size is not None and actual_size > spec.max_bytes:
        _fail_asset(
            db,
            asset,
            f"file exceeds the {spec.max_bytes // (1024 * 1024)}MB limit "
            f"for purpose={asset.purpose}",
        )
        return asset

    if spec is not None:
        from app.services.uploads.file_validation import detect_head_format

        head = read_object_head(asset.storage_uri)
        if head is None:
            # HEAD just proved the object exists, so a failed ranged read is
            # a storage blip (conn reset / restart / throttle), not bad
            # content. Failing here would enqueue blob cleanup and destroy a
            # possibly-500MB upload over a transient error — leave the asset
            # pending so a retried confirm/consume can re-verify. (A 0-byte
            # object also lands here via InvalidRange and stays pending; the
            # orphan sweeper reaps it after 24h.)
            asset.validation_error = "存储暂时不可读，请稍后重试"
            asset.updated_at = datetime.utcnow()
            db.add(asset)
            db.commit()
            db.refresh(asset)
            return asset
        ext = os.path.splitext(asset.original_filename or "")[1]
        if detect_head_format(head, spec.content_kind, ext) is None:
            _fail_asset(
                db,
                asset,
                f"file content does not look like {spec.content_kind} "
                "(magic-byte check failed)",
            )
            return asset

    if actual_size is not None:
        asset.size_bytes = actual_size
    if meta.get("content_type"):
        asset.content_type = meta["content_type"]
    asset.upload_status = UPLOAD_STATUS_UPLOADED
    asset.validation_status = "passed"
    asset.validation_error = None
    asset.updated_at = datetime.utcnow()
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return asset


def mark_file_asset_consumed(db: Session, asset: FileAsset) -> None:
    """Mark an asset consumed by a business object. Caller commits."""
    asset.upload_status = UPLOAD_STATUS_CONSUMED
    asset.updated_at = datetime.utcnow()
    db.add(asset)


def presigned_get_urls(
    db: Session,
    asset_ids: list[str],
    *,
    expiration: int = 1800,
) -> dict[str, str]:
    """Batch-mint presigned GET URLs for owned assets (one IN query).

    Only ``s3://`` URIs get a URL — ``local://`` storage has no presign
    equivalent, so those (and unknown ids) are simply absent from the
    result; callers degrade to no link. Best-effort: a presign failure
    skips that asset instead of raising.
    """
    ids = [i for i in asset_ids if i]
    if not ids:
        return {}
    from app.core.storage import generate_presigned_get_url

    rows = (
        db.query(FileAsset.id, FileAsset.storage_uri)
        .filter(FileAsset.id.in_(ids), FileAsset.deleted_at.is_(None))
        .all()
    )
    out: dict[str, str] = {}
    for asset_id, uri in rows:
        if not uri or not uri.startswith("s3://"):
            continue
        try:
            out[asset_id] = generate_presigned_get_url(uri, expiration=expiration)
        except Exception:  # noqa: BLE001 — degrade to no playback link
            logger.warning("presign failed for asset %s", asset_id, exc_info=True)
    return out


def enqueue_asset_blob_delete(db: Session, asset: FileAsset) -> None:
    """Queue deletion of an asset's storage blob via the outbox (UP-2).

    Caller commits (same transaction as the business delete). Idempotent per
    asset. The row itself is the caller's business — this only handles the
    bytes in object storage.
    """
    from app.services.uploads.outbox_service import enqueue_job

    enqueue_job(
        db,
        user_pk=asset.user_id,
        job_type="delete_object",
        aggregate_type="file_asset",
        aggregate_id=asset.id,
        payload={"storage_uri": asset.storage_uri},
        idempotency_key=f"delete_object:{asset.id}",
    )


def _fail_asset(db: Session, asset: FileAsset, reason: str) -> None:
    """Flag a failed upload and enqueue object-storage cleanup, atomically."""
    from app.services.uploads.outbox_service import enqueue_job

    asset.upload_status = UPLOAD_STATUS_FAILED
    asset.validation_status = "failed"
    asset.validation_error = reason
    asset.updated_at = datetime.utcnow()
    db.add(asset)
    enqueue_job(
        db,
        user_pk=asset.user_id,
        job_type="cleanup_failed_upload",
        aggregate_type="file_asset",
        aggregate_id=asset.id,
        payload={"storage_uri": asset.storage_uri},
        idempotency_key=f"cleanup_failed_upload:{asset.id}",
    )
    db.commit()
    db.refresh(asset)
