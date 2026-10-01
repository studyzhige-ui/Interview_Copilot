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
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.rate_limit import RATE_UPLOAD, limiter
from app.core.security import get_current_user
from app.core.storage import StorageConfigurationError
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
from app.files.application.file_asset_service import UPLOAD_STATUS_UPLOADED
from app.files.application.file_asset_service import UnknownUploadPurpose
from app.files.application.file_asset_service import UploadTooLarge
from app.files.application.file_asset_service import confirm_file_asset
from app.files.application.file_asset_service import create_file_asset
from app.files.application.file_asset_service import ensure_uploaded

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
    db: Session = Depends(get_db, scope="function"),
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
    except StorageConfigurationError as exc:
        raise HTTPException(503, str(exc)) from exc
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
    db: Session = Depends(get_db, scope="function"),
):
    """Confirm a client-completed upload: HEAD-verify + size-reconcile.

    ``validation_status=passed`` attests existence + size only; deep content
    validation is the consuming domain's parse/ingest step.
    """
    from botocore.exceptions import BotoCoreError, ClientError

    try:
        asset = confirm_file_asset(
            db,
            file_asset_id=file_asset_id,
            user_id=current_user.username,
        )
    except StorageConfigurationError as exc:
        db.rollback()
        raise HTTPException(503, str(exc)) from exc
    except (BotoCoreError, ClientError, OSError) as exc:
        db.rollback()
        raise HTTPException(503, "文件存储暂时不可用，请稍后重试") from exc
    if asset is None:
        raise HTTPException(status_code=404, detail="文件资产不存在或无权访问")
    return ConfirmResponse(
        file_asset_id=asset.id,
        upload_status=asset.upload_status,
        validation_status=asset.validation_status,
        validation_error=asset.validation_error,
    )


def _file_deletion_http(exc: Exception) -> HTTPException:
    from app.files.application.file_asset_deletion_service import (
        FileAssetDeletionConflictError,
    )
    from app.files.application.file_asset_deletion_service import (
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
    db: Session = Depends(get_db, scope="function"),
):
    from app.files.application.file_asset_deletion_service import FileAssetDeletionError
    from app.files.application.file_asset_deletion_service import (
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
    db: Session = Depends(get_db, scope="function"),
):
    from app.files.application.file_asset_deletion_service import FileAssetDeletionError
    from app.files.application.file_asset_deletion_service import (
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


@router.api_route("/file-assets/{file_asset_id}/download", methods=["GET", "HEAD"])
def download_file_asset(
    request: Request,
    file_asset_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db, scope="function"),
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

    return _stream_asset(request, asset, attachment=True)


@router.get("/file-assets/storage-usage")
def storage_usage(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db, scope="function"),
):
    """Owner logical usage; optional device capacity, never filesystem paths."""
    import shutil
    from sqlalchemy import func
    from app.core.config import settings
    from app.core.storage import check_free_space

    used, count = (
        db.query(
            func.coalesce(func.sum(FileAsset.size_bytes), 0), func.count(FileAsset.id)
        )
        .filter(
            FileAsset.user_id == current_user.id,
            FileAsset.deleted_at.is_(None),
            FileAsset.upload_status.in_(("uploaded", "consumed")),
            FileAsset.validation_status == "passed",
        )
        .one()
    )
    free = total = None
    if settings.STORAGE_BACKEND == "filesystem":
        try:
            check_free_space()
            capacity = shutil.disk_usage(settings.STORAGE_DIR)
            free, total = capacity.free, capacity.total
        except OSError:
            # Capacity still useful on a full disk; an absent/unreadable mount is unknown.
            try:
                capacity = shutil.disk_usage(settings.STORAGE_DIR)
                free, total = capacity.free, capacity.total
            except OSError:
                pass
    return {
        "backend": settings.STORAGE_BACKEND,
        "used_bytes": int(used),
        "asset_count": count,
        "free_bytes": free,
        "total_bytes": total,
    }


def _capability_asset(db, file_asset_id, token, operation, *, lock=False):
    from app.files.application.storage_access import decode_capability, matches_asset

    try:
        claims = decode_capability(token, operation=operation)
    except Exception as exc:
        raise HTTPException(403, "文件访问凭据无效或已过期") from exc
    query = db.query(FileAsset).filter(
        FileAsset.id == file_asset_id, FileAsset.deleted_at.is_(None)
    )
    if lock:
        query = query.populate_existing().with_for_update()
    asset = query.one_or_none()
    owner = db.get(User, claims["owner"])
    if owner is None or not owner.is_active or owner.token_version != claims["tv"]:
        raise HTTPException(403, "文件访问凭据已撤销")
    if (
        asset is None
        and operation == "read"
        and file_asset_id == f"legacy-avatar-{owner.id}"
        and (owner.avatar_url or "").startswith("local://avatars/")
    ):
        from app.files.application.storage_access import legacy_avatar_asset

        asset = legacy_avatar_asset(owner)
    if asset is None or not matches_asset(claims, asset):
        raise HTTPException(404, "文件资产不存在或无权访问")
    return asset


@router.put("/file-assets/{file_asset_id}/content", status_code=204)
@limiter.limit(RATE_UPLOAD)
async def upload_file_content(
    request: Request,
    response: Response,
    file_asset_id: str,
    token: str,
    db: Session = Depends(get_db, scope="function"),
):
    """Stream to bounded scratch, then create-only commit while holding asset lock."""
    import errno
    import hashlib
    from botocore.exceptions import BotoCoreError, ClientError
    import tempfile
    from app.core import storage
    from app.files.application.purpose_registry import get_purpose_spec

    from starlette.concurrency import run_in_threadpool

    # A waiting PostgreSQL row lock must not block the event loop that is
    # still receiving the upload holding that lock.
    asset = await run_in_threadpool(
        _capability_asset, db, file_asset_id, token, "write", lock=True
    )
    if asset.upload_status != "pending_upload":
        raise HTTPException(409, "上传已结束，请重新创建文件资产")
    spec = get_purpose_spec(asset.purpose)
    if spec is None:
        raise HTTPException(409, "不支持的上传用途")
    incoming_type = (
        request.headers.get("content-type", "application/octet-stream")
        .split(";", 1)[0]
        .strip()
        .lower()
    )
    if (
        incoming_type
        != (asset.content_type or "application/octet-stream")
        .split(";", 1)[0]
        .strip()
        .lower()
    ):
        raise HTTPException(415, "文件类型与上传声明不一致")
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            length = int(declared)
        except ValueError as exc:
            raise HTTPException(400, "文件长度无效") from exc
        if length < 0 or length > spec.max_bytes:
            raise HTTPException(413, "文件超过上传上限")
        if asset.size_bytes is not None and length != asset.size_bytes:
            raise HTTPException(400, "文件长度与上传声明不一致")
    try:
        if storage.head_object(asset.storage_uri) is not None:
            raise HTTPException(409, "文件已上传，请确认上传结果")
        storage.check_free_space(asset.size_bytes or 0)
        # Scratch lives on the managed volume; never accumulate a 500MB request in RAM.
        with tempfile.TemporaryFile(dir=storage.settings.STORAGE_DIR) as staged:
            size = 0
            digest = hashlib.sha256()
            async for block in request.stream():
                size += len(block)
                if size > spec.max_bytes:
                    raise HTTPException(413, "文件超过上传上限")
                if asset.size_bytes is not None and size > asset.size_bytes:
                    raise HTTPException(400, "文件长度与上传声明不一致")
                storage.check_free_space(len(block))
                staged.write(block)
                digest.update(block)
            if asset.size_bytes is not None and size != asset.size_bytes:
                raise HTTPException(400, "文件上传不完整")
            if declared is not None and size != int(declared):
                raise HTTPException(400, "文件上传不完整")
            # Recheck expiration immediately before committing a slow upload.
            from app.files.application.storage_access import decode_capability

            try:
                decode_capability(token, operation="write")
            except Exception as exc:
                raise HTTPException(403, "文件访问凭据已过期") from exc
            await run_in_threadpool(
                storage.store_object,
                staged,
                asset.storage_uri,
                content_type=asset.content_type,
                max_bytes=spec.max_bytes,
            )
            from app.files.application.file_asset_service import (
                record_file_asset_upload,
            )

            record_file_asset_upload(db, asset, digest.hexdigest())
    except StorageConfigurationError as exc:
        db.rollback()
        raise HTTPException(503, str(exc)) from exc
    except FileExistsError as exc:
        db.rollback()
        raise HTTPException(409, "文件已上传") from exc
    except ClientError as exc:
        db.rollback()
        code = str(exc.response.get("Error", {}).get("Code"))
        if code in {"412", "PreconditionFailed", "ConditionalRequestConflict"}:
            raise HTTPException(409, "文件已上传") from exc
        raise HTTPException(503, "文件存储暂时不可用") from exc
    except BotoCoreError as exc:
        db.rollback()
        raise HTTPException(503, "文件存储暂时不可用") from exc
    except OSError as exc:
        db.rollback()
        if exc.errno == errno.ENOSPC:
            raise HTTPException(507, "存储空间不足，请释放空间后重试") from exc
        raise HTTPException(503, "文件存储暂时不可用") from exc
    except BaseException:
        db.rollback()
        raise
    return Response(status_code=204)


def _stream_asset(request: Request, asset, *, attachment=False):
    from app.core.storage import head_object, open_object

    try:
        meta = head_object(asset.storage_uri)
    except StorageConfigurationError as exc:
        raise HTTPException(503, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(404, "文件资产不可下载") from exc
    except Exception as exc:
        raise HTTPException(503, "文件暂时不可读") from exc
    if meta is None:
        raise HTTPException(404, "文件不存在")
    size = meta["size_bytes"]
    base_content_type = (
        (asset.content_type or "application/octet-stream")
        .split(";", 1)[0]
        .strip()
        .lower()
    )
    safe_inline = asset.purpose in {
        "avatar",
        "interview_audio",
        "mock_audio_clip",
    } and base_content_type in {
        "image/png",
        "image/jpeg",
        "image/gif",
        "image/webp",
        "audio/mpeg",
        "audio/wav",
        "audio/x-wav",
        "audio/ogg",
        "audio/webm",
        "audio/mp4",
        "video/mp4",
        "video/webm",
    }
    attachment = attachment or not safe_inline
    headers = {
        "Referrer-Policy": "no-referrer",
        "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff",
        "Accept-Ranges": "bytes",
        "Content-Disposition": f"{'attachment' if attachment else 'inline'}; filename*=UTF-8''{quote(asset.original_filename, safe='')}",
    }
    start, end, status = 0, size - 1, 200
    byte_range = request.headers.get("range")
    if byte_range:
        import re

        match = re.fullmatch(r"bytes=(\d*)-(\d*)", byte_range.strip())
        if not match or not any(match.groups()) or size == 0:
            raise HTTPException(
                416, "无效的文件范围", headers={"Content-Range": f"bytes */{size}"}
            )
        first, last = match.groups()
        if first:
            start, end = int(first), min(int(last) if last else size - 1, size - 1)
        else:
            start, end = max(0, size - int(last)), size - 1
        if start >= size or start > end or (not first and int(last) == 0):
            raise HTTPException(
                416, "无效的文件范围", headers={"Content-Range": f"bytes */{size}"}
            )
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
        status = 206
    length = max(0, end - start + 1)
    headers["Content-Length"] = str(length)
    if request.method == "HEAD":
        return Response(
            status_code=status,
            headers=headers,
            media_type=asset.content_type or "application/octet-stream",
        )

    storage_uri = asset.storage_uri

    def chunks():
        with open_object(storage_uri, start=start, end=end if size else None) as stream:
            remaining = length
            while remaining:
                block = stream.read(min(64 * 1024, remaining))
                if not block:
                    raise OSError("Incomplete object stream")
                remaining -= len(block)
                yield block

    return StreamingResponse(
        chunks(),
        status_code=status,
        headers=headers,
        media_type=asset.content_type or "application/octet-stream",
    )


@router.api_route("/file-assets/{file_asset_id}/content", methods=["GET", "HEAD"])
def read_file_content(
    request: Request,
    file_asset_id: str,
    token: str,
    db: Session = Depends(get_db, scope="function"),
):
    asset = _capability_asset(db, file_asset_id, token, "read")
    if (
        asset.upload_status not in ("uploaded", "consumed")
        or asset.validation_status != "passed"
    ):
        raise HTTPException(404, "文件资产不可读")
    return _stream_asset(request, asset)
