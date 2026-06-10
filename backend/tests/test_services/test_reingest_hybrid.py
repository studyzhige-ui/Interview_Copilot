"""C3 / §4.6.3: subset knowledge reingest (document / user / category) resolved
from Postgres facts, funnelled through ingestion.reindex_document.

A soft-deleted document is never re-indexed; category is read from
knowledge_documents (not Milvus). reindex_document is stubbed here (its own
rebuild-from-facts behaviour is covered in test_indexing_write_order).
"""
from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401 — register mappers
from app.db.database import Base
from app.models.knowledge import KnowledgeDocument


@pytest.fixture
def reingest_db(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Maker = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    import scripts.reingest_hybrid as rh
    monkeypatch.setattr(rh, "SessionLocal", Maker)
    try:
        yield Maker
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _seed(maker, docs):
    db = maker()
    try:
        for d in docs:
            db.add(KnowledgeDocument(**d))
        db.commit()
    finally:
        db.close()


def _patch_reindex(monkeypatch):
    """Record reindex_document calls; return 1 'chunk' per document."""
    calls: list[str] = []
    import app.rag.ingestion as ing
    monkeypatch.setattr(ing, "reindex_document", lambda db, doc_id: calls.append(doc_id) or 1)
    return calls


def test_reingest_full_skips_soft_deleted(reingest_db, monkeypatch):
    _seed(reingest_db, [
        dict(id="d1", user_id=1, title="t", source_kind="user_upload", status="ready"),
        dict(id="d2", user_id=1, title="t", source_kind="user_upload", status="ready"),
        dict(id="d3", user_id=2, title="t", source_kind="user_upload", status="ready",
             deleted_at=datetime.utcnow()),
    ])
    calls = _patch_reindex(monkeypatch)
    import scripts.reingest_hybrid as rh

    total = rh.reingest_knowledge()

    assert set(calls) == {"d1", "d2"}  # the soft-deleted d3 is excluded
    assert total == 2


def test_reingest_by_user(reingest_db, monkeypatch):
    _seed(reingest_db, [
        dict(id="d1", user_id=1, title="t", source_kind="user_upload", status="ready"),
        dict(id="d2", user_id=2, title="t", source_kind="user_upload", status="ready"),
    ])
    calls = _patch_reindex(monkeypatch)
    import scripts.reingest_hybrid as rh

    rh.reingest_knowledge(user_id=1)
    assert calls == ["d1"]


def test_reingest_by_user_and_category(reingest_db, monkeypatch):
    _seed(reingest_db, [
        dict(id="d1", user_id=1, title="t", source_kind="user_upload", status="ready",
             category="面试题库"),
        dict(id="d2", user_id=1, title="t", source_kind="user_upload", status="ready",
             category="笔记"),
    ])
    calls = _patch_reindex(monkeypatch)
    import scripts.reingest_hybrid as rh

    rh.reingest_knowledge(user_id=1, category="面试题库")
    assert calls == ["d1"]


def test_reingest_explicit_document_ids(reingest_db, monkeypatch):
    _seed(reingest_db, [
        dict(id="d1", user_id=1, title="t", source_kind="user_upload", status="ready"),
    ])
    calls = _patch_reindex(monkeypatch)
    import scripts.reingest_hybrid as rh

    n = rh.reingest_knowledge(document_ids=["d1", "dX"])
    assert calls == ["d1", "dX"]  # explicit ids used as-is (no DB resolution)
    assert n == 2
