"""Owned expiration policy for unconsumed uploads, with durable blob deletion."""

from datetime import timedelta
from app.models.file_asset import FileAsset
from .file_asset_service import (
    UPLOAD_STATUS_DELETED,
    UPLOAD_STATUS_FAILED,
    UPLOAD_STATUS_PENDING,
    enqueue_asset_blob_delete,
)


def expire_orphan_uploads(db, *, now, limit=500) -> int:
    rows = (
        db.query(FileAsset)
        .filter(
            FileAsset.upload_status.in_((UPLOAD_STATUS_PENDING, UPLOAD_STATUS_FAILED)),
            FileAsset.updated_at < now - timedelta(hours=24),
            FileAsset.deleted_at.is_(None),
        )
        .order_by(FileAsset.updated_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
        .populate_existing()
        .all()
    )
    for asset in rows:
        if asset.upload_status == UPLOAD_STATUS_PENDING:
            enqueue_asset_blob_delete(db, asset)
        asset.upload_status = UPLOAD_STATUS_DELETED
        asset.deleted_at = now
        asset.updated_at = now
        db.add(asset)
    return len(rows)
