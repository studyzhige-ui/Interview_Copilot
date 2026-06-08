"""Resolve a KnowledgeDocument into plain text.

The fast path reads the **already-parsed chunks** from the Postgres
``document_chunks`` fact table — the work done ONCE at ingestion time —
concatenated in chunk order. The slow path (download from S3 → re-parse) is a
fallback for documents that have no chunks yet (ingestion still running /
failed). The fast path resolves in ~5-50 ms vs. an 8-10 s re-parse.

Used by:
  - ``/chat/mock-interview/start``  for both resume and JD text
  - ``/analyze``                    via load_knowledge_text for JD
"""
from __future__ import annotations

import logging
import os
import tempfile

from sqlalchemy.orm import Session

from app.models.knowledge import KnowledgeDocument
from app.services.storage_service import download_file_from_s3
from app.services.voice.file_parser import extract_resume_text

logger = logging.getLogger(__name__)


def read_full_text_from_chunks(
    doc: KnowledgeDocument,
    *,
    max_chars: int = 20000,
) -> tuple[str, int]:
    """Concatenate the document's chunks from Postgres ``document_chunks`` in
    order. Returns ``(text, chunk_count)``; ``("", 0)`` when the document has
    no chunks yet (ingestion still running / failed) so the caller falls back
    to re-parsing the raw upload.
    """
    from app.db.database import SessionLocal
    from app.services.knowledge.document_chunk_service import read_document_text

    try:
        with SessionLocal() as db:
            return read_document_text(db, doc.id, max_chars=max_chars)
    except Exception as exc:  # noqa: BLE001 — never break the caller on a read
        logger.warning("chunk read failed for doc=%s: %s", doc.id, exc)
        return "", 0


def find_knowledge_doc_by_upload(
    db: Session, upload_id: str, user_id: str,
) -> KnowledgeDocument | None:
    """Find the ``KnowledgeDocument`` row that wraps a given
    ``file_assets.id``, if any.

    Returns ``None`` when no library row exists for the upload — e.g. a
    direct ``/upload/resume`` that the user never categorized into the
    library, or a stale upload from before the library schema landed.
    Callers fall back to re-parsing the raw upload in that case.

    The ``upload_id`` column is indexed (see ``models/knowledge.py``)
    so this is a single point-lookup.
    """
    return (
        db.query(KnowledgeDocument)
        .filter(
            KnowledgeDocument.upload_id == upload_id,
            KnowledgeDocument.user_id == user_id,
        )
        .first()
    )


def load_knowledge_text(db: Session, document_id: str, user_id: str) -> str:
    """Resolve a ``KnowledgeDocument.id`` into plain text.

    Fast path: read the already-parsed chunks from ``document_chunks``. This
    is the common case — anything in the user's library has been
    ingested. Resolves in ~5-50 ms with no remote calls.

    Cold path: download the original file and re-parse it. Only happens
    for documents that have no chunks yet (ingestion still pending /
    failed). Used to be the only path, which is why /mock-interview/start
    took ~9s on cold resumes.

    Returns ``""`` on any failure — callers should treat the result as
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
    if doc is None:
        return ""

    # Fast path
    text, count = read_full_text_from_chunks(doc)
    if count > 0:
        return text

    # Cold fallback — only when no chunks exist yet.
    if not doc.storage_uri:
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
