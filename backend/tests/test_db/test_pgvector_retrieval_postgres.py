"""Real extension, operators, locks and legacy migration; mandatory in CI.

Synthetic embeddings deliberately test retrieval semantics, not model quality.
No downloaded weights, external service, production account or private data.
"""

from concurrent.futures import ThreadPoolExecutor
import hashlib
from threading import Event

from alembic import command
import pytest
from sqlalchemy import select, text, update, event
from app.core.config import settings
from app.models.user import User
from app.models.knowledge import KnowledgeDocument
from app.models.document_chunk import DocumentChunk
from app.models.file_asset import FileAsset
from app.models.retrieval_index import RetrievalEntry, RetrievalGeneration
from app.rag import hybrid_index as index
from app.rag.index.identity import current_index_identity
from app.rag.index.source import capture_source, IndexSourceChanged
from app.rag.index.lexical import term_counts, bm25_reference
from tests.test_db.test_alembic_migrations import fresh_pg_db  # noqa: F401
from tests.test_db.test_budget_and_invitation_recovery_postgres import (
    database as database_fixture,
)

database = database_fixture


@pytest.fixture
def corpus(database, monkeypatch):
    _, cfg, factory = database
    monkeypatch.setattr("app.db.database.SessionLocal", factory)
    monkeypatch.setattr(settings, "EMBEDDING_DIM", 4)
    monkeypatch.setattr(settings, "RAG_SIMILARITY_METRIC", "IP")
    with factory() as db:
        users = [
            User(username=name, hashed_password="synthetic")
            for name in ["alice", "bob"]
        ]
        db.add_all(users)
        db.commit()
        ids = [u.id for u in users]
    return cfg, factory, ids


def seed(corpus, name, owner, texts, *, kind="manual_text", asset=False, publish=True):
    _, factory, _ = corpus
    asset_id = None
    with factory() as db:
        if asset:
            f = FileAsset(
                user_id=owner,
                purpose="knowledge_document",
                original_filename=name + ".txt",
                object_key="fixture/" + name,
                storage_uri="local://fixture/" + name,
                upload_status="consumed",
                validation_status="passed",
            )
            db.add(f)
            db.flush()
            asset_id = f.id
        d = KnowledgeDocument(
            id=name,
            user_id=owner,
            title=name,
            source_kind=kind,
            status="ready",
            file_asset_id=asset_id,
        )
        db.add(d)
        db.flush()
        rows = []
        for i, (body, vector) in enumerate(texts):
            node = name + ":" + str(i)
            db.add(
                DocumentChunk(
                    document_id=name,
                    node_id=node,
                    user_id=owner,
                    source_kind=kind,
                    chunk_index=i,
                    text=body,
                    text_hash=hashlib.sha256(body.encode()).hexdigest(),
                    index_status="pending",
                )
            )
            rows.append(
                {"id": node, "source_text": body, "text": body, "dense": vector}
            )
        db.commit()
    if publish:
        index.replace_document(
            user_pk=owner, document_id=name, source_kind=kind, rows=rows
        )
    return rows, asset_id


def dense(owner, **kwargs):
    return index.dense_search(
        query_dense=[1, 0, 0, 0], user_pk=owner, top_k=20, **kwargs
    )


def sparse(owner, query="缓存 Redis", **kwargs):
    return index.sparse_search(query_text=query, user_pk=owner, top_k=20, **kwargs)


def test_real_dense_operators_and_bm25_agree_with_reference(corpus, monkeypatch):
    _, _, (a, b) = corpus
    bodies = ["缓存击穿 Redis SETNX", "Redis Redis cache", "完全不同的内容"]
    vectors = [[0.1, 0.8, 0, 0], [0.9, 0.1, 0, 0], [0.3, 0.5, 0, 0]]
    seed(corpus, "own", a, list(zip(bodies, vectors)))
    seed(corpus, "other", b, [("Redis " * 100, [999, 0, 0, 0])])
    assert [x["id"] for x in dense(a)] == ["own:1", "own:2", "own:0"]
    scores = bm25_reference([term_counts(t) for t in bodies], "缓存 Redis")
    hits = sparse(a)
    assert {h["id"] for h in hits} == {
        f"own:{i}" for i, v in enumerate(scores) if v > 0
    }
    for hit in hits:
        assert hit["score"] == pytest.approx(
            scores[int(hit["id"].split(":")[-1])], rel=1e-6
        )
    # Foreign tenant frequency changes cannot change Alice's lexical scores.
    seed(corpus, "other_more", b, [(f"Redis {i}", [1, 1, 0, 0]) for i in range(15)])
    assert sparse(a) == hits
    # Each metric is a separate semantic generation; reindex explicitly.
    for metric in ["COSINE", "L2"]:
        monkeypatch.setattr(settings, "RAG_SIMILARITY_METRIC", metric)
        assert dense(a) == []
        rows = [
            dict(id=f"own:{i}", source_text=t, text=t, dense=v)
            for i, (t, v) in enumerate(zip(bodies, vectors))
        ]
        index.replace_document(
            user_pk=a, document_id="own", source_kind="manual_text", rows=rows
        )
        assert dense(a)[0]["id"] == "own:1"


def test_owner_type_document_and_private_scope_are_applied_before_top_k(corpus):
    _, factory, (a, b) = corpus
    seed(corpus, "a", a, [("secret Redis", [1, 0, 0, 0])], asset=True)
    seed(corpus, "b", b, [("secret Redis", [9, 0, 0, 0])])
    seed(
        corpus,
        "private",
        a,
        [("secret Redis", [99, 0, 0, 0])],
        kind="chat_attachment",
        publish=False,
    )
    assert len(dense(a)) == len(sparse(a)) == 1
    assert dense(a, filters={"document_id": ["b", "private"]}) == []
    assert sparse(a, filters={"document_id": []}) == []
    assert dense(a, filters={"document_id": ["x' OR 1=1 --"]}) == []
    with factory() as db:
        # Even malicious/corrupt projection owner metadata cannot authorize B.
        db.execute(
            update(RetrievalEntry)
            .where(RetrievalEntry.document_id == "b")
            .values(user_id=a)
        )
        db.commit()
    assert [x["id"] for x in dense(a)] == ["a:0"]
    assert [x["id"] for x in sparse(a)] == ["a:0"]


def test_canonical_chunk_file_and_document_revocation_exclude_immediately(corpus):
    _, factory, (a, b) = corpus
    rows, asset_id = seed(corpus, "protected", a, [("Redis", [1, 0, 0, 0])], asset=True)
    mutations = [
        (DocumentChunk, {"user_id": b}),
        (KnowledgeDocument, {"user_id": b}),
        (FileAsset, {"user_id": b}),
        (FileAsset, {"upload_status": "delete_pending"}),
        (KnowledgeDocument, {"status": "stale"}),
        (DocumentChunk, {"index_status": "deleted"}),
    ]
    for model, values in mutations:
        with factory() as db:
            row = (
                db.get(FileAsset, asset_id)
                if model is FileAsset
                else db.get(KnowledgeDocument, "protected")
                if model is KnowledgeDocument
                else db.query(DocumentChunk).filter_by(document_id="protected").one()
            )
            old = {k: getattr(row, k) for k in values}
            for k, v in values.items():
                setattr(row, k, v)
            db.commit()
        assert dense(a) == [] and sparse(a) == []
        with factory() as db:
            row = (
                db.get(FileAsset, asset_id)
                if model is FileAsset
                else db.get(KnowledgeDocument, "protected")
                if model is KnowledgeDocument
                else db.query(DocumentChunk).filter_by(document_id="protected").one()
            )
            for k, v in old.items():
                setattr(row, k, v)
            db.commit()
        assert dense(a)


def test_partial_replace_rollback_retains_previous_published_generation(corpus):
    _, factory, (a, _) = corpus
    rows, _ = seed(corpus, "atomic", a, [("Redis", [1, 0, 0, 0])])
    engine = factory.kw["bind"]

    def fail_insert(_conn, _cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO retrieval_entries"):
            raise RuntimeError("injected insert failure after delete")

    event.listen(engine, "before_cursor_execute", fail_insert)
    try:
        with pytest.raises(RuntimeError, match="injected"):
            index.replace_document(
                user_pk=a, document_id="atomic", source_kind="manual_text", rows=rows
            )
    finally:
        event.remove(engine, "before_cursor_execute", fail_insert)
    assert [h["id"] for h in dense(a)] == ["atomic:0"]
    with factory() as db:
        assert db.query(RetrievalEntry).count() == 1
        assert db.query(DocumentChunk).one().index_status == "indexed"


def test_late_embedding_cannot_publish_replaced_facts_or_changed_title(corpus):
    _, factory, (a, _) = corpus
    rows, _ = seed(corpus, "race", a, [("old Redis", [1, 0, 0, 0])])
    snapshot = capture_source("race", a, "manual_text")
    with factory() as db:
        d = db.get(KnowledgeDocument, "race")
        d.title = "new title"
        db.commit()
    with pytest.raises(IndexSourceChanged):
        index.replace_document(
            user_pk=a,
            document_id="race",
            source_kind="manual_text",
            rows=rows,
            expected_source=snapshot,
        )
    with factory() as db:
        c = db.query(DocumentChunk).one()
        c.text = "corrected Redis"
        c.text_hash = hashlib.sha256(c.text.encode()).hexdigest()
        c.index_status = "pending"
        db.commit()
    with pytest.raises(IndexSourceChanged):
        index.replace_document(
            user_pk=a, document_id="race", source_kind="manual_text", rows=rows
        )
    assert dense(a) == []


def test_generation_is_not_just_embedding_width(corpus, monkeypatch):
    _, factory, (a, _) = corpus
    seed(corpus, "g", a, [("Redis", [1, 0, 0, 0])])
    first = current_index_identity().fingerprint
    monkeypatch.setattr(settings, "EMBEDDING_MODEL", "different-same-dimension-model")
    assert current_index_identity().fingerprint != first and dense(a) == []
    monkeypatch.setattr(settings, "EMBEDDING_DIM", 2)
    index.replace_document(
        user_pk=a,
        document_id="g",
        source_kind="manual_text",
        rows=[{"id": "g:0", "source_text": "Redis", "text": "Redis", "dense": [1, 0]}],
    )
    hits = index.dense_search(query_dense=[1, 0], user_pk=a, top_k=10)
    assert [h["id"] for h in hits] == ["g:0"]
    with factory() as db:
        assert db.query(RetrievalGeneration).count() == 2


def test_statement_timeout_is_real_and_does_not_poison_pool(corpus, monkeypatch):
    _, factory, (a, _) = corpus
    seed(corpus, "timeouts", a, [("Redis", [1, 0, 0, 0])])
    monkeypatch.setattr(settings, "RAG_INDEX_STATEMENT_TIMEOUT_MS", 100)
    with factory() as db:
        index._limits(db)
        with pytest.raises(Exception) as error:
            db.execute(text("SELECT pg_sleep(1)"))
        assert "statement timeout" in str(error.value)
        db.rollback()
    assert dense(a)


def test_replace_waiting_on_document_lock_rechecks_deleted_source(corpus):
    _, factory, (a, _) = corpus
    rows, _ = seed(corpus, "lock", a, [("Redis", [1, 0, 0, 0])])
    started = Event()
    with factory() as editor, ThreadPoolExecutor(1) as pool:
        row = editor.execute(
            select(KnowledgeDocument)
            .where(KnowledgeDocument.id == "lock")
            .with_for_update()
        ).scalar_one()

        def publish():
            started.set()
            return index.replace_document(
                user_pk=a, document_id="lock", source_kind="manual_text", rows=rows
            )

        future = pool.submit(publish)
        assert started.wait(3)
        row.status = "deleted"
        editor.commit()
        with pytest.raises(IndexSourceChanged):
            future.result(8)
    assert dense(a) == []


def test_migration_preserves_source_and_pending_legacy_job_identities(corpus):
    cfg, factory, (a, _) = corpus
    rows, _ = seed(corpus, "historical", a, [("原始资料", [1, 0, 0, 0])], publish=False)
    command.downgrade(cfg, "0055")
    with factory() as db:
        # Historical row inserted directly; new dispatcher intentionally refuses
        # the old vocabulary. Upgrade maps it without recreating its identity.
        db.execute(
            text(
                "INSERT INTO outbox_jobs(id,user_id,job_type,aggregate_type,aggregate_id,payload_json,status,attempts,max_attempts,next_run_at,created_at,updated_at,idempotency_key) VALUES ('legacy-job',:u,'milvus_upsert_document','knowledge_document','historical','{}','pending',0,5,NOW(),NOW(),NOW(),'legacy-idempotency')"
            ),
            {"u": a},
        )
        before = db.execute(
            text("SELECT id,node_id,text,text_hash FROM document_chunks")
        ).all()
        db.commit()
    command.upgrade(cfg, "head")
    command.check(cfg)
    with factory() as db:
        assert (
            db.execute(
                text("SELECT id,node_id,text,text_hash FROM document_chunks")
            ).all()
            == before
        )
        result = db.execute(
            text(
                "SELECT id,job_type,idempotency_key,status FROM outbox_jobs WHERE id='legacy-job'"
            )
        ).one()
        assert tuple(result) == (
            "legacy-job",
            "retrieval_upsert_document",
            "legacy-idempotency",
            "pending",
        )
        assert db.query(RetrievalEntry).count() == 0
    index.replace_document(
        user_pk=a, document_id="historical", source_kind="manual_text", rows=rows
    )
    with pytest.raises(RuntimeError, match="backup"):
        command.downgrade(cfg, "0055")
    assert dense(a)
