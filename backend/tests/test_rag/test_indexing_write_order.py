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

    def __init__(self, dim=4):
        self._dim = dim

    def get_text_embedding_batch(self, texts, show_progress=False):
        # One vector per text so the count always matches (works for any number
        # of chunks the real splitter produces in the end-to-end test).
        return [[0.1] * self._dim for _ in texts]


@pytest.fixture
def index_db(monkeypatch):
    """In-memory DB whose sessionmaker replaces ``app.db.database.SessionLocal``
    — ``_index_nodes`` imports SessionLocal from there, so patching the module
    attribute reroutes its sessions onto this engine."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
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


def _use_embed(monkeypatch, dim=4):
    monkeypatch.setattr(
        er,
        "resolve_embedding",
        lambda: er.ResolvedEmbedding(
            "local", er.PROVIDERS["local"], "BAAI/bge-m3", dim
        ),
    )
    monkeypatch.setattr(
        ingestion, "Settings", SimpleNamespace(embed_model=_FakeEmbed(dim))
    )


def test_index_nodes_writes_pending_before_milvus_then_indexed(index_db, monkeypatch):
    _use_embed(monkeypatch)

    import app.rag.milvus_hybrid as mh

    monkeypatch.setattr(mh, "delete_by_field", lambda *a, **k: None)

    def fake_insert(coll, rows):
        # At Milvus-insert time the facts must already be committed as pending
        # (phase 1 before phase 2) — read them back on a fresh session.
        db = index_db()
        try:
            statuses = {
                r.index_status
                for r in db.query(DocumentChunk)
                .filter(DocumentChunk.document_id == "d1")
                .all()
            }
        finally:
            db.close()
        assert statuses == {"pending"}, statuses

    monkeypatch.setattr(mh, "insert", fake_insert)

    nodes = [TextNode(text="a", id_="n1"), TextNode(text="b", id_="n2")]
    info = ingestion._index_nodes(
        nodes,
        user_id=1,
        source_kind="user_upload",
        document_id="d1",
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


def test_index_nodes_milvus_failure_queues_upsert_keeps_pending(index_db, monkeypatch):
    """C2: a Milvus write failure does NOT fail the import — it keeps the pending
    facts, queues a milvus_upsert_document retry, and reports indexed=False so the
    caller leaves the document 'processing'."""
    from app.models.outbox_job import OutboxJob

    _use_embed(monkeypatch)

    import app.rag.milvus_hybrid as mh

    monkeypatch.setattr(mh, "delete_by_field", lambda *a, **k: None)

    def boom(coll, rows):
        raise RuntimeError("milvus unavailable")

    monkeypatch.setattr(mh, "insert", boom)

    nodes = [TextNode(text="a", id_="n1")]
    info = ingestion._index_nodes(
        nodes, user_id=1, source_kind="user_upload", document_id="d2"
    )

    assert info["indexed"] is False
    db = index_db()
    try:
        rows = db.query(DocumentChunk).filter(DocumentChunk.document_id == "d2").all()
        assert (
            len(rows) == 1 and rows[0].index_status == "pending"
        )  # facts kept, not indexed
        jobs = db.query(OutboxJob).filter(OutboxJob.aggregate_id == "d2").all()
        assert len(jobs) == 1 and jobs[0].job_type == "milvus_upsert_document"
    finally:
        db.close()


def test_reingest_replacement_is_idempotent(index_db, monkeypatch):
    """Re-ingesting the same document_id replaces (not accumulates) its chunks
    and Milvus rows — the worker's stated re-ingest idempotency contract."""
    _use_embed(monkeypatch)
    import app.rag.milvus_hybrid as mh

    deletes: list = []
    monkeypatch.setattr(
        mh, "delete_by_field", lambda coll, field, value: deletes.append((field, value))
    )
    monkeypatch.setattr(mh, "insert", lambda coll, rows: None)

    first = [TextNode(text="v1 a", id_="a1"), TextNode(text="v1 b", id_="a2")]
    ingestion._index_nodes(
        first, user_id=1, source_kind="user_upload", document_id="dup"
    )
    second = [TextNode(text="v2 only", id_="b1")]
    ingestion._index_nodes(
        second, user_id=1, source_kind="user_upload", document_id="dup"
    )

    db = index_db()
    try:
        rows = db.query(DocumentChunk).filter(DocumentChunk.document_id == "dup").all()
        assert len(rows) == 1  # replaced, not 2+1 accumulated
        assert rows[0].text == "v2 only"
        assert rows[0].index_status == "indexed"
    finally:
        db.close()
    # Each ingest deleted this document's prior Milvus rows before inserting.
    assert deletes == [("document_id", "dup"), ("document_id", "dup")]


def test_reindex_document_rebuilds_from_live_facts(index_db, monkeypatch):
    """reindex_document reads LIVE chunks (skips deleted), re-embeds, replaces the
    document's Milvus rows, and flips its pending chunks to indexed."""
    _use_embed(monkeypatch)
    import app.rag.milvus_hybrid as mh

    captured: dict = {}
    monkeypatch.setattr(mh, "delete_by_field", lambda coll, field, value: None)
    monkeypatch.setattr(
        mh, "insert", lambda coll, rows: captured.__setitem__("rows", rows)
    )

    db = index_db()
    try:
        db.add_all(
            [
                DocumentChunk(
                    document_id="rd",
                    node_id="n1",
                    user_id=1,
                    source_kind="user_upload",
                    chunk_index=0,
                    text="alpha",
                    index_status="pending",
                ),
                DocumentChunk(
                    document_id="rd",
                    node_id="n2",
                    user_id=1,
                    source_kind="user_upload",
                    chunk_index=1,
                    text="beta",
                    index_status="pending",
                ),
                DocumentChunk(
                    document_id="rd",
                    node_id="n3",
                    user_id=1,
                    source_kind="user_upload",
                    chunk_index=2,
                    text="gone",
                    index_status="deleted",
                ),
            ]
        )
        db.commit()
    finally:
        db.close()

    db2 = index_db()
    try:
        n = ingestion.reindex_document(db2, "rd")
    finally:
        db2.close()

    assert n == 2  # only the 2 live chunks
    assert {r["id"] for r in captured["rows"]} == {"n1", "n2"}  # deleted excluded
    db3 = index_db()
    try:
        indexed = (
            db3.query(DocumentChunk)
            .filter(
                DocumentChunk.document_id == "rd",
                DocumentChunk.index_status == "indexed",
            )
            .count()
        )
        assert indexed == 2  # pending → indexed
    finally:
        db3.close()


def test_reindex_document_no_live_chunks_clears_milvus(index_db, monkeypatch):
    _use_embed(monkeypatch)
    import app.rag.milvus_hybrid as mh

    deletes: list = []
    monkeypatch.setattr(
        mh, "delete_by_field", lambda coll, field, value: deletes.append(value)
    )
    monkeypatch.setattr(
        mh,
        "insert",
        lambda coll, rows: pytest.fail("must not insert with no live chunks"),
    )

    db = index_db()
    try:
        n = ingestion.reindex_document(db, "empty_doc")
    finally:
        db.close()

    assert n == 0
    assert deletes == ["empty_doc"]  # rows cleared, nothing inserted


async def test_ingest_text_end_to_end_marks_indexed(index_db, monkeypatch):
    """A real ingest_text entry (improved_qa) runs the full pipeline and leaves
    indexed facts — validates _index_nodes wiring through a live entry point."""
    _use_embed(monkeypatch)
    import app.rag.milvus_hybrid as mh

    monkeypatch.setattr(mh, "delete_by_field", lambda *a, **k: None)
    monkeypatch.setattr(mh, "insert", lambda coll, rows: None)

    result = await ingestion.ingest_text(
        "## 问题\n什么是缓存击穿？\n## 答案\n热点 key 失效。",
        "improved_qa",
        user_id=1,
        document_id="qa1",
    )

    assert result["success"] and result["node_ids"]
    db = index_db()
    try:
        rows = db.query(DocumentChunk).filter(DocumentChunk.document_id == "qa1").all()
        assert rows and all(r.index_status == "indexed" for r in rows)
    finally:
        db.close()
