"""Actual HNSW plans, filtered recall and canonical authorization fences."""

from sqlalchemy import text, update
import pytest

from app.core.config import settings
from app.models.knowledge import KnowledgeDocument
from app.models.document_chunk import DocumentChunk
from app.models.retrieval_index import RetrievalEntry
from app.rag import hybrid_index as index
from app.rag.index import hnsw
from app.rag.index.identity import current_index_identity
from tests.test_db.test_pgvector_retrieval_postgres import corpus as corpus_fixture
from tests.test_db.test_pgvector_retrieval_postgres import database, fresh_pg_db, seed  # noqa: F401

corpus = corpus_fixture


@pytest.mark.parametrize("metric", ["IP", "COSINE", "L2"])
def test_owner_graph_plan_recall_filters_and_publication(
    corpus, monkeypatch, metric, record_property
):
    _, factory, (owner, foreign) = corpus
    monkeypatch.setattr(settings, "RAG_SIMILARITY_METRIC", metric)
    # A large foreign corpus of nearer vectors must never starve this graph.
    seed(
        corpus,
        "own",
        owner,
        [(f"Redis {i}", [1 - i / 10000, i / 10000 + 0.001, 0, 0]) for i in range(1500)],
    )
    seed(
        corpus, "foreign", foreign, [(f"secret {i}", [1, 0, 0, 0]) for i in range(3000)]
    )
    seed(corpus, "filtered", owner, [("private nearer", [1, 0, 0, 0])])
    with factory() as db:
        for model in (KnowledgeDocument, DocumentChunk, RetrievalEntry):
            key = model.id if model is KnowledgeDocument else model.document_id
            db.execute(
                update(model)
                .where(key == "filtered")
                .values(source_kind="chat_attachment")
            )
        db.commit()
    identity = current_index_identity()
    args = dict(
        query_dense=[1, 0, 0, 0],
        user_pk=owner,
        top_k=10,
        filters={"document_id": "own"},
    )
    exact = index.dense_search(**args)
    with factory() as db:
        name = hnsw.prepare(db, identity, owner)
        assert hnsw.prepare(db, identity, owner) == name
        db.execute(text("ANALYZE retrieval_entries"))
        db.commit()
    plans = []
    from sqlalchemy import event

    def explain(conn, cursor, statement, parameters, context, executemany):
        if (
            "SELECT retrieval_entries.node_id AS id" in statement
            and "ORDER BY" in statement
        ):
            with conn.connection.cursor() as probe:
                probe.execute("EXPLAIN (FORMAT JSON) " + statement, parameters)
                plans.append(str(probe.fetchone()[0]))

    monkeypatch.setattr(settings, "PGVECTOR_DENSE_INDEX_TYPE", "hnsw")
    assert current_index_identity().fingerprint == identity.fingerprint
    engine = factory.kw["bind"]
    event.listen(engine, "before_cursor_execute", explain)
    try:
        hits = index.dense_search(**args)
    finally:
        event.remove(engine, "before_cursor_execute", explain)
    assert len(hits) == 10 and all(hit["user_id"] == owner for hit in hits)
    assert len(set(h["id"] for h in hits) & set(h["id"] for h in exact)) >= 9
    assert any(name in plan for plan in plans), plans
    record_property("used_hnsw_index", name)
    record_property(
        "synthetic_recall_at_10",
        len(set(h["id"] for h in hits) & set(h["id"] for h in exact)) / 10,
    )
    assert index.dense_search(**{**args, "filters": None}) == hits
    with factory() as db:
        db.execute(
            update(KnowledgeDocument)
            .where(KnowledgeDocument.id == "own")
            .values(status="processing")
        )
        db.commit()
    assert index.dense_search(**args) == []


def test_explicit_unprepared_graph_and_empty_corpus(corpus, monkeypatch):
    _, _, (owner, foreign) = corpus
    seed(corpus, "own", owner, [("data", [1, 0, 0, 0])])
    monkeypatch.setattr(settings, "PGVECTOR_DENSE_INDEX_TYPE", "hnsw")
    args = dict(query_dense=[1, 0, 0, 0], top_k=10)
    assert index.dense_search(user_pk=foreign, **args) == []
    with pytest.raises(index.RetrievalIndexUnavailable, match="HNSW index missing"):
        index.dense_search(user_pk=owner, **args)
