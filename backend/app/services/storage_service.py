import logging
import os
import uuid

import boto3
from botocore.exceptions import ClientError

from app.core.config import settings

logger = logging.getLogger(__name__)

s3_client = boto3.client(
    "s3",
    aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
    aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
    region_name=settings.AWS_REGION,
    endpoint_url=settings.AWS_ENDPOINT_URL,
)


def generate_presigned_upload_url(filename: str, expiration=3600) -> dict:
    """Generate a presigned URL for direct client uploads."""
    _, ext = os.path.splitext(filename)
    if not ext:
        ext = ".bin"

    unique_filename = f"uploads/{uuid.uuid4().hex}{ext}"

    try:
        response = s3_client.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": settings.S3_BUCKET_NAME,
                "Key": unique_filename,
                "ContentType": "application/octet-stream",
            },
            ExpiresIn=expiration,
        )

        file_url = f"s3://{settings.S3_BUCKET_NAME}/{unique_filename}"
        logger.info("Generated presigned upload URL for %s", file_url)

        return {
            "upload_url": response,
            "file_path": file_url,
        }
    except ClientError as exc:
        logger.error("Failed to generate S3 presigned upload URL: %s", exc)
        raise


def download_file_from_s3(s3_uri: str, local_path: str):
    """Download an S3 URI to a local worker path."""
    if not s3_uri.startswith("s3://"):
        raise ValueError(f"Invalid s3 URI: {s3_uri}")

    parts = s3_uri.replace("s3://", "").split("/", 1)
    if len(parts) != 2:
        raise ValueError(f"Unable to parse S3 URI: {s3_uri}")

    bucket, key = parts
    try:
        logger.info("[Worker] Downloading %s to %s", s3_uri, local_path)
        s3_client.download_file(bucket, key, local_path)
        logger.info("[Worker] S3 download completed.")
    except ClientError as exc:
        logger.error("[Worker] S3 download failed: %s", exc)
        raise


def upload_file_to_s3(file_obj, filename: str) -> str:
    """Upload a file object to S3-compatible storage and return its s3:// URI."""
    _, ext = os.path.splitext(filename)
    if not ext:
        ext = ".bin"

    unique_filename = f"uploads/{uuid.uuid4().hex}{ext}"

    try:
        s3_client.upload_fileobj(
            file_obj,
            settings.S3_BUCKET_NAME,
            unique_filename,
            ExtraArgs={"ContentType": "application/octet-stream"},
        )
        url = f"s3://{settings.S3_BUCKET_NAME}/{unique_filename}"
        logger.info("Uploaded object to %s", url)
        return url
    except ClientError as exc:
        logger.error("S3 upload failed, falling back to local storage: %s", exc)
        return _fallback_local_save(file_obj, unique_filename)
    except Exception as exc:  # noqa: BLE001
        logger.warning("S3 client unavailable, falling back to local storage: %s", exc)
        return _fallback_local_save(file_obj, unique_filename)


def _fallback_local_save(file_obj, relative_path: str):
    import shutil
    from pathlib import Path

    base_dir = Path(settings.STORAGE_DIR)
    full_path = base_dir / relative_path
    full_path.parent.mkdir(parents=True, exist_ok=True)
    file_obj.seek(0)
    with open(full_path, "wb") as f:
        shutil.copyfileobj(file_obj, f)
    return str(full_path)
