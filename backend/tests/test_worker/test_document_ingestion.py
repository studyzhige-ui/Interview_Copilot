"""Worker-level test for the format defense-in-depth in
``process_document_ingestion`` (ingestion §4.1.2).

A document that bypassed the API gate (stale dispatch / direct DB insert)
with an unsupported format must be marked ``failed`` and NOT retried, and
must never reach the parser. The validator itself is unit-tested in
test_document_formats; this pins the worker's no-retry handling.
"""
from __future__ import annotations

from typing import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base
import app.models  # noqa: F401 — register mappers
from app.models.file_asset import FileAsset
from app.models.knowledge import KnowledgeDocument


@pytest.fixture
def worker_db(monkeypatch) -> Iterator[sessionmaker]:
    """Isolated in-memory DB whose sessionmaker replaces the worker's
    ``SessionLocal`` — the task opens/closes its OWN session on this engine,
    so it can't disturb a seed session."""
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Maker = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    import app.worker.tasks as tasks_mod
    monkeypatch.setattr(tasks_mod, "SessionLocal", Maker)
    try:
        yield Maker
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _seed_doc(maker: sessionmaker, *, filename: str, status: str = "processing") -> str:
    db: Session = maker()
    try:
        asset = FileAsset(
            id="fa_w1", user_id=1, purpose="knowledge_document",
            original_filename=filename,
            object_key="uploads/1/fa_w1/" + filename,
            storage_uri="s3://b/uploads/1/fa_w1/" + filename,
            upload_status="uploaded",
        )
        doc = KnowledgeDocument(
            id="kdoc_w1", user_id=1, file_asset_id="fa_w1",
            title="t", source_kind="user_upload", status=status,
            storage_uri=asset.storage_uri, object_key=asset.object_key,
        )
        db.add_all([asset, doc])
        db.commit()
        return doc.id
    finally:
        db.close()


def test_worker_rejects_unsupported_format_without_retry(worker_db, monkeypatch):
    from app.worker.tasks import process_document_ingestion

    # If the parser is ever reached, fail loudly — the format gate must
    # short-circuit before download/ingest.
    import app.rag.ingestion as ingestion_mod
    monkeypatch.setattr(
        ingestion_mod, "ingest_document",
        lambda *a, **k: pytest.fail("ingest_document must not run for a rejected format"),
    )

    doc_id = _seed_doc(worker_db, filename="malware.exe")
    result = process_document_ingestion.apply(args=[doc_id]).get()

    assert result["status"] == "failed"
    # Permanent failure persisted with the friendly Chinese message.
    db = worker_db()
    try:
        doc = db.query(KnowledgeDocument).filter(KnowledgeDocument.id == doc_id).first()
        assert doc.status == "failed"
        assert doc.error_message and "不支持" in doc.error_message
    finally:
        db.close()


def test_worker_rejects_deferred_format(worker_db, monkeypatch):
    from app.worker.tasks import process_document_ingestion

    import app.rag.ingestion as ingestion_mod
    monkeypatch.setattr(
        ingestion_mod, "ingest_document",
        lambda *a, **k: pytest.fail("ingest_document must not run for a deferred format"),
    )

    # Legacy Office is still deferred (images now OCR-ingest, so .png is allowed).
    doc_id = _seed_doc(worker_db, filename="old.doc")
    result = process_document_ingestion.apply(args=[doc_id]).get()

    assert result["status"] == "failed"
    db = worker_db()
    try:
        doc = db.query(KnowledgeDocument).filter(KnowledgeDocument.id == doc_id).first()
        assert "即将支持" in (doc.error_message or "")
    finally:
        db.close()


def test_worker_marks_failed_on_empty_after_cleaning_without_retry(worker_db, monkeypatch):
    """EmptyContentError from ingest (S0 cleaning left no usable text) is a
    permanent failure: friendly message, no retry."""
    from app.rag.cleaning import EmptyContentError
    from app.worker.tasks import process_document_ingestion

    # Get past the download (no real S3) so ingest is reached.
    import app.services.storage_service as storage_mod
    monkeypatch.setattr(
        storage_mod, "download_file_from_s3",
        lambda uri, path: open(path, "w", encoding="utf-8").close(),
    )

    async def _empty(*a, **k):
        raise EmptyContentError("文档清洗后没有可用文本，请确认文件内容非空且为可读文本。")

    import app.rag.ingestion as ingestion_mod
    monkeypatch.setattr(ingestion_mod, "ingest_document", _empty)

    doc_id = _seed_doc(worker_db, filename="notes.txt")
    result = process_document_ingestion.apply(args=[doc_id]).get()

    assert result["status"] == "failed"
    db = worker_db()
    try:
        doc = db.query(KnowledgeDocument).filter(KnowledgeDocument.id == doc_id).first()
        assert doc.status == "failed"
        assert "可用文本" in (doc.error_message or "")
    finally:
        db.close()


def test_worker_keeps_processing_when_index_queued(worker_db, monkeypatch):
    """C2: when ingest reports indexed=False (the Milvus write was queued for
    outbox retry because Milvus was down), the worker saves the facts but keeps
    the document 'processing' — NOT 'ready' — until the index lands."""
    from app.worker.tasks import process_document_ingestion

    import app.services.storage_service as storage_mod
    monkeypatch.setattr(
        storage_mod, "download_file_from_s3",
        lambda uri, path: open(path, "w", encoding="utf-8").close(),
    )

    async def _queued(*a, **k):
        return {
            "success": True, "indexed": False, "chunk_count": 2,
            "node_ids": ["n1", "n2"], "ref_doc_ids": [], "content_text": "body",
        }

    import app.rag.ingestion as ingestion_mod
    monkeypatch.setattr(ingestion_mod, "ingest_document", _queued)

    doc_id = _seed_doc(worker_db, filename="notes.txt")
    result = process_document_ingestion.apply(args=[doc_id]).get()

    assert result["status"] == "indexing_queued"
    db = worker_db()
    try:
        doc = db.query(KnowledgeDocument).filter(KnowledgeDocument.id == doc_id).first()
        assert doc.status == "processing"   # not 'ready' until the index lands
        assert doc.chunk_count == 2          # facts are saved
        assert "重试" in (doc.error_message or "")
    finally:
        db.close()


def test_worker_marks_failed_on_embedding_validation_without_retry(worker_db, monkeypatch):
    """A dimension/count mismatch (EmbeddingValidationError) is a permanent
    config error: friendly message surfaced via str(exc), no retry (B6 §4.5.3)."""
    from app.rag.embedding_registry import EmbeddingValidationError
    from app.worker.tasks import process_document_ingestion

    import app.services.storage_service as storage_mod
    monkeypatch.setattr(
        storage_mod, "download_file_from_s3",
        lambda uri, path: open(path, "w", encoding="utf-8").close(),
    )

    async def _dim_mismatch(*a, **k):
        raise EmbeddingValidationError(
            "向量维度(3)与配置 EMBEDDING_DIM(1024)不一致；请确认 embedding 模型与配置匹配，或重建索引。"
        )

    import app.rag.ingestion as ingestion_mod
    monkeypatch.setattr(ingestion_mod, "ingest_document", _dim_mismatch)

    doc_id = _seed_doc(worker_db, filename="notes.txt")
    result = process_document_ingestion.apply(args=[doc_id]).get()

    assert result["status"] == "failed"
    db = worker_db()
    try:
        doc = db.query(KnowledgeDocument).filter(KnowledgeDocument.id == doc_id).first()
        assert doc.status == "failed"
        assert "维度" in (doc.error_message or "")
    finally:
        db.close()
