"""Original-file asset: the single home for every persistent uploaded blob.

``file_assets`` is the raw-file layer — it records WHERE a file lives (object
storage key + URI), WHAT it is (content type / size / checksum), and the
lifecycle of the upload (``upload_status``) and its content validation
(``validation_status``). It deliberately carries NO business meaning: whether
an asset becomes a resume, a knowledge document, interview audio, a JD, a mock
voice clip, or an avatar is decided by the business table that references it
(by ``file_assets.id``). Replaces the old ``user_uploads`` table.

Keyed by the stable ``users.id`` (FK, ON DELETE CASCADE). Persistent business
files only ever arrive via the presigned upload-url + confirm flow; there is
no server-receives-bytes "direct upload" business path.
"""
import uuid
from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
)

from app.db.database import Base


def generate_file_asset_id() -> str:
    return f"fa_{uuid.uuid4().hex}"


class FileAsset(Base):
    __tablename__ = "file_assets"
    __table_args__ = (
        # Hot path: list a user's assets of a given purpose, newest first.
        Index("ix_file_assets_user_purpose", "user_id", "purpose"),
    )

    id = Column(String, primary_key=True, default=generate_file_asset_id, index=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    # Upload intent: resume / knowledge_document / interview_audio / jd /
    # mock_audio_clip / avatar / agent_output. Validated at the API layer.
    purpose = Column(String, index=True, nullable=False)
    original_filename = Column(String, nullable=False)
    # Object-storage location. ``object_key`` is the controlled key
    # (uploads/{user}/{asset}/{file}); ``storage_uri`` is the s3:// / local://
    # form the worker/serializer dereference.
    object_key = Column(String, nullable=False, unique=True, index=True)
    storage_uri = Column(String, nullable=False)
    content_type = Column(String, nullable=True)
    size_bytes = Column(Integer, nullable=True)
    checksum_sha256 = Column(String, nullable=True)
    # Raw-file lifecycle: pending_upload -> uploaded -> consumed, with
    # delete_pending / deleted / failed as terminal/cleanup states.
    upload_status = Column(
        String, index=True, default="pending_upload", nullable=False,
    )
    # Confirm-time check: pending -> passed/failed (or skipped). ``passed``
    # means the object EXISTS and its size reconciles with what the client
    # declared — NOT a deep content check. Magic-byte / parseability
    # validation is the consuming domain's job (its parse/ingest step), since
    # the presigned bytes never traverse this process.
    validation_status = Column(String, default="pending", nullable=False)
    validation_error = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False,
    )
    deleted_at = Column(DateTime, nullable=True)
