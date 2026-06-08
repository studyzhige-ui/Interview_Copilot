"""Tests for the knowledge-text fast path.

Parsed chunks now live in the Postgres ``document_chunks`` fact table (not a
LlamaIndex docstore). ``read_document_text`` concatenates them in order;
``read_full_text_from_docstore`` is the thin KnowledgeDocument wrapper, and
``load_knowledge_text`` short-circuits the S3 re-parse when chunks exist.
"""
from __future__ import annotations

from types import SimpleNamespace

from app.models.document_chunk import DocumentChunk


def _seed(db, document_id: str, texts: list[str], user_id: str = "u1") -> None:
    for i, t in enumerate(texts):
        db.add(DocumentChunk(
            document_id=document_id, user_id=user_id,
            source_type="official_docs", chunk_index=i, text=t,
        ))
    db.commit()


# ── read_document_text (the fact-source reader) ─────────────────────────────


def test_read_document_text_concatenates_in_order(db_session):
    from app.services.knowledge.document_chunk_service import read_document_text

    _seed(db_session, "kdoc_1", ["孙根武\n北京邮电大学", "工作经历: Acme", "技能: Python"])
    text, count = read_document_text(db_session, "kdoc_1")
    assert count == 3
    assert text.index("孙根武") < text.index("工作经历") < text.index("技能")


def test_read_document_text_empty_when_no_chunks(db_session):
    from app.services.knowledge.document_chunk_service import read_document_text

    text, count = read_document_text(db_session, "kdoc_missing")
    assert text == ""
    assert count == 0


def test_read_document_text_truncates_at_max_chars(db_session):
    from app.services.knowledge.document_chunk_service import read_document_text

    _seed(db_session, "kdoc_big", ["A" * 30000])
    text, count = read_document_text(db_session, "kdoc_big", max_chars=100)
    assert len(text) == 100
    assert count == 1


# ── read_full_text_from_docstore (thin wrapper) ─────────────────────────────


def test_read_full_text_delegates_to_chunks(monkeypatch):
    from app.services.knowledge import knowledge_text_service as svc

    monkeypatch.setattr(
        "app.services.knowledge.document_chunk_service.read_document_text",
        lambda db, doc_id, *, max_chars=20000: ("full resume text", 2),
    )
    text, count = svc.read_full_text_from_docstore(SimpleNamespace(id="kdoc_1"))
    assert (text, count) == ("full resume text", 2)


def test_read_full_text_swallows_read_failure(monkeypatch):
    from app.services.knowledge import knowledge_text_service as svc

    def _boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr(
        "app.services.knowledge.document_chunk_service.read_document_text", _boom,
    )
    text, count = svc.read_full_text_from_docstore(SimpleNamespace(id="kdoc_1"))
    assert (text, count) == ("", 0)


# ── find_knowledge_doc_by_upload (unchanged) ────────────────────────────────


def test_find_knowledge_doc_by_upload_filters_user_and_upload():
    from app.services.knowledge import knowledge_text_service as svc

    captured_filters: list = []

    class _Q:
        def filter(self, *exprs):
            captured_filters.extend(exprs)
            return self
        def first(self):
            return SimpleNamespace(id="kdoc_ok")

    class _Db:
        def query(self, model):
            return _Q()

    out = svc.find_knowledge_doc_by_upload(_Db(), "upl_x", "alice")
    assert out is not None and out.id == "kdoc_ok"
    assert len(captured_filters) == 2  # upload_id + user_id


# ── load_knowledge_text (fast path vs S3 re-parse) ──────────────────────────


def test_load_knowledge_text_prefers_chunks_over_reparse(monkeypatch):
    from app.services.knowledge import knowledge_text_service as svc

    class _Q:
        def filter(self, *a, **k): return self
        def first(self):
            return SimpleNamespace(
                id="kdoc_ok", storage_uri="s3://b/k", title="x.pdf", object_key="x.pdf",
            )

    class _Db:
        def query(self, *a, **k): return _Q()

    monkeypatch.setattr(svc, "read_full_text_from_docstore", lambda doc, **k: ("from chunks", 1))

    def _no_s3(*a, **k):
        raise AssertionError("download_file_from_s3 must NOT run when chunks exist")

    monkeypatch.setattr(svc, "download_file_from_s3", _no_s3)
    monkeypatch.setattr(svc, "extract_resume_text", _no_s3)

    assert svc.load_knowledge_text(_Db(), "kdoc_ok", "alice") == "from chunks"


def test_load_knowledge_text_falls_back_to_reparse_when_no_chunks(monkeypatch):
    from app.services.knowledge import knowledge_text_service as svc

    class _Q:
        def filter(self, *a, **k): return self
        def first(self):
            return SimpleNamespace(
                id="kdoc_pending", storage_uri="s3://b/k", title="x.pdf", object_key="x.pdf",
            )

    class _Db:
        def query(self, *a, **k): return _Q()

    monkeypatch.setattr(svc, "read_full_text_from_docstore", lambda doc, **k: ("", 0))
    monkeypatch.setattr(svc, "download_file_from_s3", lambda src, dst: None)
    monkeypatch.setattr(svc, "extract_resume_text", lambda path: "from reparse")

    assert svc.load_knowledge_text(_Db(), "kdoc_pending", "alice") == "from reparse"
