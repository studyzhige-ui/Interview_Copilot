import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String

from app.db.database import Base


def generate_upload_id() -> str:
    return f"upl_{uuid.uuid4().hex}"


class UserUpload(Base):
    __tablename__ = "user_uploads"

    id = Column(String, primary_key=True, default=generate_upload_id, index=True)
    user_id = Column(String, index=True, nullable=False)
    purpose = Column(String, index=True, nullable=False)
    original_filename = Column(String, nullable=False)
    storage_uri = Column(String, nullable=False)
    object_key = Column(String, nullable=False, unique=True, index=True)
    content_type = Column(String, nullable=True)
    size_bytes = Column(Integer, nullable=True)
    status = Column(String, index=True, default="pending_upload", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
