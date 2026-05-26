from datetime import datetime

from sqlalchemy.orm import Session

from app.models.upload import UserUpload, generate_upload_id
from app.services.storage_service import (
    build_owned_object_key,
    generate_presigned_upload_url_for_key,
    storage_uri_for_key,
)


def create_owned_upload(
    db: Session,
    *,
    user_id: str,
    filename: str,
    purpose: str,
    content_type: str | None = None,
    size_bytes: int | None = None,
) -> tuple[UserUpload, dict]:
    upload_id = generate_upload_id()
    object_key = build_owned_object_key(user_id, upload_id, filename)
    storage_uri = storage_uri_for_key(object_key)
    upload = UserUpload(
        id=upload_id,
        user_id=user_id,
        purpose=purpose,
        original_filename=filename,
        storage_uri=storage_uri,
        object_key=object_key,
        content_type=content_type or "application/octet-stream",
        size_bytes=size_bytes,
        status="pending_upload",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(upload)
    db.commit()
    db.refresh(upload)
    url_info = generate_presigned_upload_url_for_key(
        object_key,
        content_type=upload.content_type or "application/octet-stream",
    )
    return upload, url_info


def get_owned_upload(
    db: Session,
    *,
    upload_id: str,
    user_id: str,
    purpose: str | None = None,
) -> UserUpload | None:
    query = db.query(UserUpload).filter(UserUpload.id == upload_id, UserUpload.user_id == user_id)
    if purpose:
        query = query.filter(UserUpload.purpose == purpose)
    return query.first()


def mark_upload_consumed(db: Session, upload: UserUpload) -> None:
    upload.status = "consumed"
    upload.updated_at = datetime.utcnow()
    db.add(upload)
