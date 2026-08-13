"""General-purpose file-asset upload API: presigned PUT + confirm.

Every persistent business file (resume / knowledge document / interview audio /
JD / mock voice clip / avatar / agent output) is uploaded the same way:

    POST /file-assets/upload-url      -> reserve a file_assets row + presigned URL
    PUT  <presigned_url> (client)     -> bytes go straight to object storage
    POST /file-assets/{id}/confirm    -> HEAD-verify + size-reconcile the upload

Business endpoints then consume the confirmed ``file_asset_id``. Domain
commands that must inspect an upload before keeping it (such as a recorded
mock answer) use ``store_validated_file_asset`` instead of sending the same
bytes through this generic browser flow a second time.
"""

from __future__ import annotations

import logging
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.core.rate_limit import RATE_UPLOAD, limiter
from app.core.security import get_current_user
from app.db.database import get_db
from app.models.file_asset import FileAsset
from app.models.user import User
from app.schemas.file_assets import (
    ConfirmResponse,
    FileAssetDeletionImpact,
    FileAssetPermanentDeleteRequest,
    FileAssetPermanentDeleteResult,
    UploadUrlRequest,
    UploadUrlResponse,
)
from app.services.uploads.file_asset_service import (
    UPLOAD_STATUS_UPLOADED,
    UnknownUploadPurpose,
    UploadTooLarge,
    confirm_file_asset,
    create_file_asset,
    ensure_uploaded,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Shared HTTP mappings for upload errors ───────────────────────────────
# Every router that mints upload URLs or consumes assets uses these, so the
# user-facing wording lives exactly once.


def upload_too_large_http(exc: UploadTooLarge) -> HTTPException:
    return HTTPException(
        status_code=413,
        detail=f"文件过大（上限 {exc.limit_mb}MB）",
    )


def require_uploaded(db: Session, upload: FileAsset, noun: str) -> FileAsset:
    """Confirm-on-consume gate for business endpoints: verify a possibly
    still-pending asset and 400 with its validation error if it isn't
    readable. ``noun`` names the file in the user-facing message (文档 /
    音频文件 / ...)."""
    upload = ensure_uploaded(db, upload)
    if upload.upload_status != UPLOAD_STATUS_UPLOADED:
        raise HTTPException(
            status_code=400,
            detail=f"{noun}校验未通过：{upload.validation_error or '上传未完成'}",
        )
    return upload


@router.post("/file-assets/upload-url", response_model=UploadUrlResponse)
@limiter.limit(RATE_UPLOAD)
def create_upload_url(
    request: Request,
    response: Response,
    body: UploadUrlRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Reserve a file asset and return a short-lived presigned PUT URL.

    Purpose whitelist + size cap are enforced inside ``create_file_asset``
    from PURPOSE_REGISTRY — every upload entry point shares the same rules.
    """
    try:
        asset, url_info = create_file_asset(
            db,
            user_id=current_user.username,
            filename=body.filename,
            purpose=body.purpose,
            content_type=body.content_type,
            size_bytes=body.size_bytes,
        )
    except UnknownUploadPurpose:
        raise HTTPException(status_code=400, detail=f"不支持的上传用途：{body.purpose}")
    except UploadTooLarge as exc:
        raise upload_too_large_http(exc)
    return UploadUrlResponse(
        file_asset_id=asset.id,
        upload_url=url_info["upload_url"],
        filename=asset.original_filename,
    )


@router.post("/file-assets/{file_asset_id}/confirm", response_model=ConfirmResponse)
@limiter.limit(RATE_UPLOAD)
def confirm_upload(
    request: Request,
    response: Response,
    file_asset_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Confirm a client-completed upload: HEAD-verify + size-reconcile.

    ``validation_status=passed`` attests existence + size only; deep content
    validation is the consuming domain's parse/ingest step.
    """
    asset = confirm_file_asset(
        db,
        file_asset_id=file_asset_id,
        user_id=current_user.username,
    )
    if asset is None:
        raise HTTPException(status_code=404, detail="文件资产不存在或无权访问")
    return ConfirmResponse(
        file_asset_id=asset.id,
        upload_status=asset.upload_status,
        validation_status=asset.validation_status,
        validation_error=asset.validation_error,
    )


def _file_deletion_http(exc: Exception) -> HTTPException:
    from app.services.uploads.file_asset_deletion_service import (
        FileAssetDeletionConflictError,
        FileAssetDeletionNotFoundError,
    )

    if isinstance(exc, FileAssetDeletionNotFoundError):
        return HTTPException(status_code=404, detail="文件资产不存在或无权访问")
    if isinstance(exc, FileAssetDeletionConflictError):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=422, detail=str(exc))


@router.get(
    "/file-assets/{file_asset_id}/deletion-impact",
    response_model=FileAssetDeletionImpact,
)
def get_file_asset_deletion_impact(
    file_asset_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.services.uploads.file_asset_deletion_service import (
        FileAssetDeletionError,
        preview_file_asset_deletion,
    )

    try:
        return preview_file_asset_deletion(
            db,
            user_pk=current_user.id,
            file_asset_id=file_asset_id,
        )
    except FileAssetDeletionError as exc:
        raise _file_deletion_http(exc) from exc


@router.delete(
    "/file-assets/{file_asset_id}/permanent",
    response_model=FileAssetPermanentDeleteResult,
)
def permanently_delete_file_asset(
    file_asset_id: str,
    body: FileAssetPermanentDeleteRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.services.uploads.file_asset_deletion_service import (
        FileAssetDeletionError,
        permanently_delete_file_asset as delete_asset,
    )

    try:
        execution = delete_asset(
            db,
            user_pk=current_user.id,
            file_asset_id=file_asset_id,
            confirmation_token=body.confirmation_token,
            confirm_file_asset_id=body.confirm_file_asset_id,
            confirm_filename=body.confirm_filename,
        )
        db.commit()
    except FileAssetDeletionError as exc:
        db.rollback()
        raise _file_deletion_http(exc) from exc
    except Exception:
        db.rollback()
        raise

    from app.task_queue.dispatch import revoke_task

    for task_id in execution.ingestion_task_ids:
        try:
            revoke_task(task_id)
        except Exception:  # noqa: BLE001 - durable deletion fence is authoritative
            logger.warning(
                "Could not revoke permanently deleted FileAsset ingestion %s",
                task_id,
                exc_info=True,
            )
    return execution.result


@router.get("/file-assets/{file_asset_id}/download")
def download_file_asset(
    file_asset_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Owner-scoped download without disclosing storage URI or object key."""

    asset = (
        db.query(FileAsset)
        .filter(
            FileAsset.id == file_asset_id,
            FileAsset.user_id == current_user.id,
            FileAsset.deleted_at.is_(None),
            FileAsset.upload_status.in_(("uploaded", "consumed")),
            FileAsset.validation_status == "passed",
        )
        .one_or_none()
    )
    if asset is None:
        raise HTTPException(status_code=404, detail="文件资产不存在或不可下载")

    if asset.storage_uri.startswith("s3://"):
        from app.core.config import settings
        from app.core.storage import parse_s3_uri, s3_client

        try:
            bucket, key = parse_s3_uri(asset.storage_uri)
            if bucket != settings.S3_BUCKET_NAME:
                raise ValueError("FileAsset points outside the controlled bucket")
            object_response = s3_client.get_object(Bucket=bucket, Key=key)
        except Exception as exc:  # noqa: BLE001 - no raw storage fallback
            logger.warning("download read failed for %s", asset.id, exc_info=True)
            raise HTTPException(status_code=503, detail="文件暂时无法下载") from exc

        body = object_response["Body"]

        def iter_object():
            try:
                yield from body.iter_chunks(chunk_size=64 * 1024)
            finally:
                body.close()

        headers = {
            "Cache-Control": "private, no-store",
            "Content-Disposition": (
                f"attachment; filename*=UTF-8''{quote(asset.original_filename, safe='')}"
            ),
            "X-Content-Type-Options": "nosniff",
        }
        response_size = object_response.get("ContentLength", asset.size_bytes)
        if response_size is not None:
            headers["Content-Length"] = str(response_size)
        return StreamingResponse(
            iter_object(),
            media_type=asset.content_type or "application/octet-stream",
            headers=headers,
        )

    from app.core.storage import is_local_uri, parse_local_uri

    if is_local_uri(asset.storage_uri):
        try:
            local_path = parse_local_uri(asset.storage_uri)
        except ValueError as exc:
            logger.warning("unsafe local FileAsset URI for %s", asset.id)
            raise HTTPException(status_code=404, detail="文件资产不可下载") from exc
        if not local_path.is_file():
            raise HTTPException(status_code=404, detail="文件资产不可下载")
        return FileResponse(
            path=local_path,
            media_type=asset.content_type or "application/octet-stream",
            filename=asset.original_filename,
            headers={
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )

    raise HTTPException(status_code=409, detail="该存储类型不支持安全下载")
