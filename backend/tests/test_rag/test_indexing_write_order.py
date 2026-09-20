"""Orchestration contracts; PostgreSQL atomicity is exercised by test_db tests.

The fake publication port below deliberately is NOT a SQLite implementation of
pgvector. It lets the ingest tests observe persisted pending facts at the port.
"""

from types import SimpleNamespace
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from llama_index.core.schema import TextNode
import app.models  # noqa: F401
from app.db.database import Base
from app.models.knowledge import KnowledgeDocument
from app.models.document_chunk import DocumentChunk
from app.models.outbox_job import OutboxJob
from app.rag import embedding_registry as er, hybrid_index as index
from app.rag.ingest.pipeline import _persist_nodes, ingest_text
from app.rag.index.knowledge import reindex_document
from app.rag.index.identity import current_index_identity
from app.rag.index.source import IndexSourceChanged


@pytest.fixture
def index_db(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr("app.db.database.SessionLocal", factory)
    monkeypatch.setattr(er.settings, "EMBEDDING_DIM", 4)
    monkeypatch.setattr(
        er,
        "resolve_embedding",
        lambda: er.ResolvedEmbedding("local", er.PROVIDERS["local"], "BAAI/bge-m3", 4),
    )
    monkeypatch.setattr(
        "app.rag.ingest.embedding.Settings",
        SimpleNamespace(
            embed_model=SimpleNamespace(
                get_text_embedding_batch=lambda texts, **k: [[0.1] * 4 for _ in texts]
            )
        ),
    )
    try:
        yield factory
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def doc(factory, name, kind="user_upload"):
    with factory() as db:
        db.add(
            KnowledgeDocument(
                id=name,
                user_id=1,
                title="Fixture",
                source_kind=kind,
                status="processing",
            )
        )
        db.commit()


def publication(factory, captured, *, fail=False):
    def publish(**kwargs):
        captured.append(kwargs)
        with factory() as db:
            chunks = (
                db.query(DocumentChunk)
                .filter_by(document_id=kwargs["document_id"])
                .all()
            )
            assert all(
                c.index_status in ("pending", "deleted", "indexed") for c in chunks
            )
            if fail:
                raise ConnectionError("projection temporarily unavailable")
            for c in chunks:
                if c.index_status != "deleted":
                    c.index_status = "indexed"
            db.get(
                KnowledgeDocument, kwargs["document_id"]
            ).index_fingerprint = current_index_identity().fingerprint
            db.commit()

    return publish


def persist(nodes, **kwargs):
    return _persist_nodes(
        nodes,
        assign_stable_ids=False,
        document_title_loader=lambda _: None,
        user_id=1,
        source_kind="user_upload",
        **kwargs,
    )


def test_pending_facts_precede_atomic_publication_port(index_db, monkeypatch):
    doc(index_db, "first")
    calls = []
    monkeypatch.setattr(index, "replace_document", publication(index_db, calls))
    result = persist(
        [TextNode(text="alpha", id_="n1"), TextNode(text="beta", id_="n2")],
        document_id="first",
    )
    assert result["indexed"] and result["chunk_count"] == 2 and len(calls) == 1
    with index_db() as db:
        assert {c.index_status for c in db.query(DocumentChunk)} == {"indexed"}


def test_failure_retains_pending_facts_and_outbox(index_db, monkeypatch):
    doc(index_db, "failure")
    monkeypatch.setattr(index, "replace_document", publication(index_db, [], fail=True))
    result = persist([TextNode(text="alpha", id_="n1")], document_id="failure")
    assert result["indexed"] is False
    with index_db() as db:
        assert db.query(DocumentChunk).one().index_status == "pending"
        assert db.query(OutboxJob).one().job_type == "retrieval_upsert_document"


def test_reingest_replaces_complete_chunk_set_once(index_db, monkeypatch):
    doc(index_db, "duplicate")
    calls = []
    monkeypatch.setattr(index, "replace_document", publication(index_db, calls))
    persist(
        [TextNode(text="v1 a", id_="a"), TextNode(text="v1 b", id_="b")],
        document_id="duplicate",
    )
    persist([TextNode(text="v2", id_="c")], document_id="duplicate")
    assert len(calls) == 2
    with index_db() as db:
        assert db.query(DocumentChunk).one().text == "v2"
        assert db.query(DocumentChunk).one().index_status == "indexed"


def test_passage_prefix_does_not_replace_raw_source(index_db, monkeypatch):
    doc(index_db, "structured")
    calls = []
    monkeypatch.setattr(index, "replace_document", publication(index_db, calls))
    node = TextNode(
        text="Acknowledged after execution.",
        id_="n",
        metadata={"heading_path": ["Tasks", "Acknowledgements"]},
    )
    _persist_nodes(
        [node],
        user_id=1,
        source_kind="user_upload",
        document_id="structured",
        assign_stable_ids=False,
        document_title_loader=lambda _: "Celery",
    )
    assert (
        calls[0]["rows"][0]["text"]
        == "Document: Celery\nSection: Tasks > Acknowledgements\nAcknowledged after execution."
    )
    assert calls[0]["rows"][0]["source_text"] == node.text
    with index_db() as db:
        assert db.query(DocumentChunk).one().text == node.text


def test_reindex_uses_live_canonical_facts_and_detached_snapshot(index_db, monkeypatch):
    doc(index_db, "rd")
    calls = []
    with index_db() as db:
        for n, t, status in [
            ("n1", "alpha", "pending"),
            ("n2", "beta", "pending"),
            ("n3", "gone", "deleted"),
        ]:
            db.add(
                DocumentChunk(
                    document_id="rd",
                    node_id=n,
                    user_id=1,
                    source_kind="user_upload",
                    text=t,
                    index_status=status,
                    chunk_index=0,
                )
            )
        db.commit()
    monkeypatch.setattr(index, "replace_document", publication(index_db, calls))
    assert reindex_document("rd") == 2
    assert {r["id"] for r in calls[0]["rows"]} == {"n1", "n2"}
    assert calls[0]["expected_source"].document_id == "rd"
    assert calls[0]["embedding_profile"]["embedding_dim"] == 4


def test_missing_document_rebuild_has_no_write_side_effect(index_db, monkeypatch):
    monkeypatch.setattr(
        index,
        "replace_document",
        lambda **_: pytest.fail("missing owner must not publish"),
    )
    assert reindex_document("missing") == 0


def test_missing_canonical_chunks_require_reparse(index_db, monkeypatch):
    doc(index_db, "empty")
    calls = []
    monkeypatch.setattr(index, "replace_document", publication(index_db, calls))
    with pytest.raises(ValueError, match="canonical_chunks_missing"):
        reindex_document("empty")
    assert calls == []


async def test_text_entry_reaches_publication_and_preserves_provenance(
    index_db, monkeypatch
):
    doc(index_db, "qa", "improved_qa")
    calls = []
    monkeypatch.setattr(index, "replace_document", publication(index_db, calls))
    result = await ingest_text(
        "## 问题\n什么是缓存击穿？\n## 答案\n热点 key 失效。",
        "improved_qa",
        1,
        document_id="qa",
    )
    assert result["success"] and result["indexed"] and calls
    with index_db() as db:
        assert all(c.index_status == "indexed" for c in db.query(DocumentChunk))


def test_owner_mismatch_stops_before_model(index_db, monkeypatch):
    doc(index_db, "owned")
    with index_db() as db:
        db.get(KnowledgeDocument, "owned").user_id = 2
        db.commit()
    monkeypatch.setattr(
        "app.rag.ingest.pipeline.embed_passages",
        lambda *a, **k: pytest.fail("must authorize first"),
    )
    with pytest.raises(PermissionError):
        persist([TextNode(text="x", id_="n")], document_id="owned")


def test_source_edit_during_embedding_cannot_replace_chunks(index_db, monkeypatch):
    doc(index_db, "racing")

    def changed(passages, **kwargs):
        with index_db() as db:
            db.get(KnowledgeDocument, "racing").title = "Changed"
            db.commit()
        return SimpleNamespace(vectors=[[0.1] * 4 for _ in passages], profile={})

    monkeypatch.setattr("app.rag.ingest.pipeline.embed_passages", changed)
    with pytest.raises(IndexSourceChanged):
        persist([TextNode(text="stale", id_="n")], document_id="racing")
    with index_db() as db:
        assert db.query(DocumentChunk).count() == 0 and db.query(OutboxJob).count() == 0
