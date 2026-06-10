"""B7 / §4.6.3: two-phase document-atomic write order.

``_index_nodes`` must write facts as ``pending`` BEFORE the Milvus rows, then
flip them to ``indexed`` only after Milvus succeeds. If the Milvus write fails,
the committed pending facts must remain (recoverable by reingest/reindex), never
a half-written index.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from llama_index.core.schema import TextNode
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401 — register mappers
import app.rag.embedding_registry as er
from app.db.database import Base
from app.models.document_chunk import DocumentChunk
from app.rag import ingestion


class _FakeEmbed:
    embed_batch_size = 8

    def __init__(self, vectors):
        self._vectors = vectors

    def get_text_embedding_batch(self, texts, show_progress=False):
        return self._vectors


@pytest.fixture
def index_db(monkeypatch):
    """In-memory DB whose sessionmaker replaces ``app.db.database.SessionLocal``
    — ``_index_nodes`` imports SessionLocal from there, so patching the module
    attribute reroutes its sessions onto this engine."""
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Maker = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    import app.db.database as dbmod
    monkeypatch.setattr(dbmod, "SessionLocal", Maker)
    try:
        yield Maker
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _use_embed(monkeypatch, vectors, dim=4):
    monkeypatch.setattr(
        er, "resolve_embedding",
        lambda: er.ResolvedEmbedding("local", er.PROVIDERS["local"], "BAAI/bge-m3", dim),
    )
    monkeypatch.setattr(ingestion, "Settings", SimpleNamespace(embed_model=_FakeEmbed(vectors)))


def test_index_nodes_writes_pending_before_milvus_then_indexed(index_db, monkeypatch):
    _use_embed(monkeypatch, [[0.1, 0.2, 0.3, 0.4], [0.5, 0.6, 0.7, 0.8]])

    import app.rag.milvus_hybrid as mh
    monkeypatch.setattr(mh, "delete_by_field", lambda *a, **k: None)

    def fake_insert(coll, rows):
        # At Milvus-insert time the facts must already be committed as pending
        # (phase 1 before phase 2) — read them back on a fresh session.
        db = index_db()
        try:
            statuses = {
                r.index_status for r in db.query(DocumentChunk)
                .filter(DocumentChunk.document_id == "d1").all()
            }
        finally:
            db.close()
        assert statuses == {"pending"}, statuses

    monkeypatch.setattr(mh, "insert", fake_insert)

    nodes = [TextNode(text="a", id_="n1"), TextNode(text="b", id_="n2")]
    info = ingestion._index_nodes(
        nodes, user_id=1, source_kind="user_upload", document_id="d1",
    )

    assert info["chunk_count"] == 2
    assert all("embedding_profile" in n.metadata for n in nodes)
    db = index_db()
    try:
        rows = db.query(DocumentChunk).filter(DocumentChunk.document_id == "d1").all()
        assert len(rows) == 2
        assert all(r.index_status == "indexed" for r in rows)  # phase 3 flipped them
    finally:
        db.close()


def test_index_nodes_milvus_failure_leaves_pending_facts(index_db, monkeypatch):
    _use_embed(monkeypatch, [[0.1, 0.2, 0.3, 0.4]])

    import app.rag.milvus_hybrid as mh
    monkeypatch.setattr(mh, "delete_by_field", lambda *a, **k: None)

    def boom(coll, rows):
        raise RuntimeError("milvus unavailable")

    monkeypatch.setattr(mh, "insert", boom)

    nodes = [TextNode(text="a", id_="n1")]
    with pytest.raises(RuntimeError):
        ingestion._index_nodes(nodes, user_id=1, source_kind="user_upload", document_id="d2")

    # Pending facts survive the Milvus failure — recoverable, not half-indexed.
    db = index_db()
    try:
        rows = db.query(DocumentChunk).filter(DocumentChunk.document_id == "d2").all()
        assert len(rows) == 1
        assert rows[0].index_status == "pending"
    finally:
        db.close()
