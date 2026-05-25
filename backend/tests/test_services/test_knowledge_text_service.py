"""Tests for the docstore fast-path in knowledge_text_service.

These pin the perf win: when a document has been ingested into the
library, its parsed chunks already live in PostgresDocumentStore — so
mock-start / analyze / read_resume can read them back without a fresh
S3 download + LlamaParse round-trip.

Pre-fix mock-start timing on a fresh resume showed ``resume=8610ms``,
99% of which was the LlamaParse remote call. With the docstore fast
path that drops to ~5-50 ms.
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


def _make_doc(*, node_ids: list[str], id: str = "kdoc_1") -> SimpleNamespace:
    """A minimal stand-in for a KnowledgeDocument row — only the fields
    ``read_full_text_from_docstore`` actually touches."""
    return SimpleNamespace(
        id=id,
        node_ids=json.dumps(node_ids),
    )


def test_read_full_text_returns_concatenated_chunks_in_stored_order(monkeypatch):
    """Stored-order matters: SentenceSplitter emits chunks in document
    flow (top → bottom for PDFs), so concatenating in node_ids order
    preserves heading-above-body structure. Without this the LLM sees
    the resume scrambled."""
    from app.services import knowledge_text_service as svc

    fake_nodes = {
        "n1": SimpleNamespace(text="孙根武\n北京邮电大学"),
        "n2": SimpleNamespace(text="工作经历: Acme Corp 2024-至今"),
        "n3": SimpleNamespace(text="技能: Python, Rust, Go"),
    }

    class _FakeDocstore:
        def get_document(self, nid):
            return fake_nodes.get(nid)

    monkeypatch.setattr(
        "llama_index.storage.docstore.postgres.PostgresDocumentStore.from_uri",
        classmethod(lambda cls, uri: _FakeDocstore()),
    )

    doc = _make_doc(node_ids=["n1", "n2", "n3"])
    text, count = svc.read_full_text_from_docstore(doc)

    assert count == 3
    assert "孙根武" in text
    assert "工作经历" in text
    assert "技能" in text
    # Order matters — n1 before n2 before n3.
    assert text.index("孙根武") < text.index("工作经历") < text.index("技能")


def test_read_full_text_returns_empty_on_no_node_ids():
    """Documents whose ingestion hasn't populated ``node_ids`` yet
    (status=processing / pending / failed) must return ``("", 0)``
    rather than try to talk to the docstore — the caller will fall
    back to re-parsing the raw upload."""
    from app.services import knowledge_text_service as svc

    doc = _make_doc(node_ids=[])
    text, count = svc.read_full_text_from_docstore(doc)
    assert text == ""
    assert count == 0


def test_read_full_text_swallows_docstore_connection_failure(monkeypatch):
    """If the docstore can't even be reached (DB down, llama_index extras
    not installed in this env), return ``("", 0)`` and let the caller
    fall back. Crashing the whole endpoint over an observability path
    would be much worse than re-parsing."""
    from app.services import knowledge_text_service as svc

    def _boom(cls, uri):
        raise RuntimeError("simulated_db_down")

    monkeypatch.setattr(
        "llama_index.storage.docstore.postgres.PostgresDocumentStore.from_uri",
        classmethod(_boom),
    )

    doc = _make_doc(node_ids=["n1"])
    text, count = svc.read_full_text_from_docstore(doc)
    assert text == ""
    assert count == 0


def test_read_full_text_skips_missing_nodes(monkeypatch):
    """Individual ``get_document`` lookups can return None (chunk was
    deleted out from under us) or raise (transient DB hiccup). Both
    are absorbed and we keep going with whatever nodes we got.

    All-missing collapses to ``("", 0)`` so the caller knows to fall
    back to re-parsing."""
    from app.services import knowledge_text_service as svc

    class _PartiallyEmpty:
        def __init__(self): self.calls = 0
        def get_document(self, nid):
            self.calls += 1
            if nid == "n_ok":
                return SimpleNamespace(text="readable content")
            if nid == "n_raises":
                raise RuntimeError("transient")
            return None  # n_missing

    monkeypatch.setattr(
        "llama_index.storage.docstore.postgres.PostgresDocumentStore.from_uri",
        classmethod(lambda cls, uri: _PartiallyEmpty()),
    )

    doc = _make_doc(node_ids=["n_missing", "n_ok", "n_raises"])
    text, count = svc.read_full_text_from_docstore(doc)
    # Only 1 of 3 succeeded — we don't lose that one.
    assert count == 1
    assert "readable content" in text


def test_read_full_text_uses_get_content_when_text_attr_missing(monkeypatch):
    """Older llama_index versions / Document-subtype nodes may not
    expose ``.text`` directly. Cover both shapes so a library upgrade
    doesn't silently drop the content."""
    from app.services import knowledge_text_service as svc

    class _DocLikeNode:
        # No .text; only get_content()
        def get_content(self): return "from get_content"

    class _Store:
        def get_document(self, nid):
            return _DocLikeNode()

    monkeypatch.setattr(
        "llama_index.storage.docstore.postgres.PostgresDocumentStore.from_uri",
        classmethod(lambda cls, uri: _Store()),
    )

    doc = _make_doc(node_ids=["n1"])
    text, count = svc.read_full_text_from_docstore(doc)
    assert count == 1
    assert text == "from get_content"


def test_read_full_text_truncates_at_max_chars(monkeypatch):
    from app.services import knowledge_text_service as svc

    class _Big:
        def get_document(self, nid):
            return SimpleNamespace(text="A" * 30000)

    monkeypatch.setattr(
        "llama_index.storage.docstore.postgres.PostgresDocumentStore.from_uri",
        classmethod(lambda cls, uri: _Big()),
    )

    doc = _make_doc(node_ids=["n1"])
    text, count = svc.read_full_text_from_docstore(doc, max_chars=100)
    assert len(text) == 100
    assert count == 1


def test_find_knowledge_doc_by_upload_filters_user_and_upload(monkeypatch):
    """``find_knowledge_doc_by_upload`` must filter on BOTH user_id and
    upload_id so a user can't access another user's library row by
    guessing an upload id."""
    from app.services import knowledge_text_service as svc

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
    assert out is not None
    assert out.id == "kdoc_ok"
    # Two filter expressions: one on upload_id, one on user_id.
    assert len(captured_filters) == 2


def test_load_knowledge_text_prefers_docstore_over_reparse(monkeypatch):
    """The fast path must short-circuit the slow path — that's the
    whole point of this refactor. Verify ``load_knowledge_text``
    returns the docstore text and never touches ``download_file_from_s3``."""
    from app.services import knowledge_text_service as svc

    class _Q:
        def filter(self, *a, **k): return self
        def first(self):
            return SimpleNamespace(
                id="kdoc_ok",
                node_ids=json.dumps(["n1"]),
                storage_uri="s3://b/k",
                title="x.pdf",
                object_key="x.pdf",
            )

    class _Db:
        def query(self, *a, **k): return _Q()

    class _Store:
        def get_document(self, nid):
            return SimpleNamespace(text="from docstore")

    monkeypatch.setattr(
        "llama_index.storage.docstore.postgres.PostgresDocumentStore.from_uri",
        classmethod(lambda cls, uri: _Store()),
    )

    # Sentinel: if anything tries to hit S3, the test fails loudly.
    def _no_s3(*a, **k):
        raise AssertionError("download_file_from_s3 should NOT be called when docstore returns text")

    monkeypatch.setattr(
        "app.services.knowledge_text_service.download_file_from_s3",
        _no_s3,
    )
    monkeypatch.setattr(
        "app.services.knowledge_text_service.extract_resume_text",
        _no_s3,
    )

    text = svc.load_knowledge_text(_Db(), "kdoc_ok", "alice")
    assert text == "from docstore"


def test_load_knowledge_text_falls_back_to_reparse_when_docstore_empty(monkeypatch):
    """When docstore returns empty (ingestion still pending), the
    download+parse fallback runs and its result is returned."""
    from app.services import knowledge_text_service as svc

    class _Q:
        def filter(self, *a, **k): return self
        def first(self):
            return SimpleNamespace(
                id="kdoc_pending",
                node_ids=json.dumps([]),  # not yet ingested
                storage_uri="s3://b/k",
                title="x.pdf",
                object_key="x.pdf",
            )

    class _Db:
        def query(self, *a, **k): return _Q()

    monkeypatch.setattr(
        "app.services.knowledge_text_service.download_file_from_s3",
        lambda src, dst: None,  # no-op
    )
    monkeypatch.setattr(
        "app.services.knowledge_text_service.extract_resume_text",
        lambda path: "from reparse",
    )

    text = svc.load_knowledge_text(_Db(), "kdoc_pending", "alice")
    assert text == "from reparse"
