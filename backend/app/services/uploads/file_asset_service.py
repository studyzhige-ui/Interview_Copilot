"""Service layer for ``file_assets`` — the unified presigned upload flow.

Lifecycle:

    create_file_asset()   -> row (pending_upload / pending) + presigned PUT URL
    <client PUTs bytes to object storage>
    confirm_file_asset()  -> HEAD-verify + size-reconcile -> uploaded / passed
                             (or failed + enqueue object cleanup)
    <business consumes>    -> mark_file_asset_consumed()

``passed`` attests only that the object exists and its size matches what the
client declared. Deep content validation (magic bytes / parseability) is left
to the consuming domain's parse/ingest job — the presigned bytes never reach
this process.

The table keys on the stable ``users.id``; callers still pass the runtime
principal (username), which this layer resolves once via
``app.core.user_identity.resolve_user_pk`` (same pattern as the model-config
services). Reads that already hold a trusted business object look an asset up
by id alone (``get_file_asset``); ownership-sensitive reads use
``get_owned_file_asset``.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.core.user_identity import resolve_user_pk
from app.models.file_asset import FileAsset, generate_file_asset_id
from app.services.storage_service import (
    build_owned_object_key,
    generate_presigned_upload_url_for_key,
    head_object,
    storage_uri_for_key,
)


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

    ``user_id`` is the caller's username; it's resolved to the stable
    ``users.id`` for the FK. Raises ``ValueError`` for an unknown user.
    """
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
        upload_status="pending_upload",
        validation_status="pending",
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    url_info = generate_presigned_upload_url_for_key(
        object_key, content_type=asset.content_type or "application/octet-stream",
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
    db: Session, *, user_id: str, purpose: str | None = None,
) -> list[FileAsset]:
    user_pk = resolve_user_pk(db, user_id)
    if user_pk is None:
        return []
    query = db.query(FileAsset).filter(
        FileAsset.user_id == user_pk, FileAsset.deleted_at.is_(None),
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
    """Confirm a client-completed upload.

    HEAD the object to prove it exists, reconcile its size against what the
    client declared, then flip the asset to uploaded/passed. On any failure the
    asset goes failed/failed and a cleanup job is enqueued in the SAME
    transaction so a half-uploaded object can't linger. Returns the asset, or
    ``None`` if it isn't owned by the caller.
    """
    asset = get_owned_file_asset(db, file_asset_id=file_asset_id, user_id=user_id)
    if asset is None:
        return None
    # Idempotent: a re-fired confirm on an already-uploaded/consumed asset is a
    # no-op — never regress a consumed asset back to uploaded.
    if asset.upload_status in ("uploaded", "consumed"):
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
            db, asset,
            f"size mismatch: declared {asset.size_bytes}, stored {actual_size}",
        )
        return asset

    if actual_size is not None:
        asset.size_bytes = actual_size
    if meta.get("content_type"):
        asset.content_type = meta["content_type"]
    asset.upload_status = "uploaded"
    asset.validation_status = "passed"
    asset.validation_error = None
    asset.updated_at = datetime.utcnow()
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return asset


def mark_file_asset_consumed(db: Session, asset: FileAsset) -> None:
    """Mark an asset consumed by a business object. Caller commits."""
    asset.upload_status = "consumed"
    asset.updated_at = datetime.utcnow()
    db.add(asset)


def _fail_asset(db: Session, asset: FileAsset, reason: str) -> None:
    """Flag a failed upload and enqueue object-storage cleanup, atomically."""
    from app.services.uploads.outbox_service import enqueue_job

    asset.upload_status = "failed"
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
