"""Resolve a KnowledgeDocument id into plain text.

Used by both /chat/mock-interview/start and /analyze to enrich an interview
plan / analysis context with a candidate's job description.
"""

import logging
import os
import tempfile

from sqlalchemy.orm import Session

from app.models.knowledge import KnowledgeDocument
from app.services.storage_service import download_file_from_s3
from app.services.voice.file_parser import extract_resume_text

logger = logging.getLogger(__name__)


def load_knowledge_text(db: Session, document_id: str, user_id: str) -> str:
    """Download the document's file from object storage and parse it.

    Returns an empty string on any failure — callers should treat the JD as
    optional and not block the broader flow.
    """
    doc = (
        db.query(KnowledgeDocument)
        .filter(
            KnowledgeDocument.id == document_id,
            KnowledgeDocument.user_id == user_id,
        )
        .first()
    )
    if doc is None or not doc.storage_uri:
        return ""

    suffix = os.path.splitext(doc.title or doc.object_key or "")[1] or ".txt"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tf:
        local_path = tf.name
    try:
        download_file_from_s3(doc.storage_uri, local_path)
        return extract_resume_text(local_path) or ""
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to load knowledge doc %s as text: %s", document_id, exc)
        return ""
    finally:
        try:
            os.unlink(local_path)
        except OSError:
            pass
