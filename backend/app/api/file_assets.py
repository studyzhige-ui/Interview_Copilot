"""Unified file-asset upload API: presigned PUT + confirm.

Every persistent business file (resume / knowledge document / interview audio /
JD / mock voice clip / avatar / agent output) is uploaded the same way:

    POST /file-assets/upload-url      -> reserve a file_assets row + presigned URL
    PUT  <presigned_url> (client)     -> bytes go straight to object storage
    POST /file-assets/{id}/confirm    -> HEAD-verify + size-reconcile the upload

Business endpoints then consume the confirmed ``file_asset_id``. There is no
server-receives-bytes "direct upload" path for persistent business files.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.core.rate_limit import RATE_UPLOAD, limiter
from app.core.security import get_current_user
from app.db.database import get_db
from app.models.user import User
from app.schemas.file_assets import (
    ConfirmResponse,
    UploadUrlRequest,
    UploadUrlResponse,
)
from app.services.uploads.file_asset_service import (
    UnknownUploadPurpose,
    UploadTooLarge,
    confirm_file_asset,
    create_file_asset,
)

logger = logging.getLogger(__name__)

router = APIRouter()


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
        raise HTTPException(
            status_code=413,
            detail=f"文件过大（上限 {exc.limit_bytes // (1024 * 1024)}MB）",
        )
    return UploadUrlResponse(
        file_asset_id=asset.id,
        upload_url=url_info["upload_url"],
        storage_uri=asset.storage_uri,
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
        db, file_asset_id=file_asset_id, user_id=current_user.username,
    )
    if asset is None:
        raise HTTPException(status_code=404, detail="文件资产不存在或无权访问")
    return ConfirmResponse(
        file_asset_id=asset.id,
        upload_status=asset.upload_status,
        validation_status=asset.validation_status,
        validation_error=asset.validation_error,
    )
