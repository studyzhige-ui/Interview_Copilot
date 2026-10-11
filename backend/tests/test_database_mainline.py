"""Disposable PostgreSQL migration and real pgvector retrieval acceptance."""

import os
import subprocess
import sys
import uuid
from pathlib import Path
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def postgres():
    admin_url = os.environ.get("TEST_PG_ADMIN_URL")
    if not admin_url:
        if os.environ.get("REQUIRE_TEST_POSTGRES") == "1":
            pytest.fail("TEST_PG_ADMIN_URL is required")
        pytest.skip("explicit disposable PostgreSQL admin URL required")
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    name = "contract_" + uuid.uuid4().hex
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    url = make_url(admin_url).set(database=name).render_as_string(hide_password=False)
    engine = create_engine(url)
    try:
        environment = {**os.environ, "DATABASE_URL": url}
        for args in (["upgrade", "head"], ["check"]):
            result = subprocess.run(
                [sys.executable, "-m", "alembic", *args],
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
                timeout=120,
            )
            assert result.returncode == 0, result.stdout + result.stderr
        yield engine
    finally:
        engine.dispose()
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        admin.dispose()


def test_schema_has_version_bound_resume_spans_and_one_vector_repository(postgres):
    with postgres.connect() as connection:
        assert (
            connection.execute(text("select version_num from alembic_version")).scalar()
            == "0074"
        )
        assert (
            connection.execute(
                text(
                    "select count(*) from information_schema.columns where table_name='artifact_resume_states' and column_name='section_spans_json'"
                )
            ).scalar()
            == 1
        )
        assert (
            connection.execute(
                text("select '[1,0]'::vector <=> '[1,0]'::vector")
            ).scalar()
            == 0
        )


def test_exact_and_hnsw_share_generation_owner_and_source_deletion_fences(
    postgres, monkeypatch
):
    from app.core.config import settings
    from app.db import database
    from app.models.user import User
    from app.models.knowledge import KnowledgeDocument
    from app.models.document_chunk import DocumentChunk
    from app.rag import hybrid_index as index
    from app.rag.index.identity import current_index_identity
    from app.rag.index.hnsw import prepare
    from app.db.types import utc_now

    sessions = sessionmaker(postgres, expire_on_commit=False)
    monkeypatch.setattr(database, "SessionLocal", sessions)
    monkeypatch.setattr(settings, "PGVECTOR_DENSE_INDEX_TYPE", "exact")
    identity = current_index_identity()
    vector = [1.0] + [0.0] * (identity.embedding_dim - 1)
    with sessions() as db:
        users = [
            User(username="pg_owner", hashed_password="none"),
            User(username="pg_other", hashed_password="none"),
        ]
        db.add_all(users)
        db.flush()
        ids = [u.id for u in users]
        for i, owner in enumerate(ids):
            db.add(
                KnowledgeDocument(
                    id=f"doc-{i}",
                    user_id=owner,
                    title="RAG",
                    source_kind="manual_text",
                    content_text="alpha evidence",
                    status="ready",
                )
            )
            db.flush()
            db.add(
                DocumentChunk(
                    id=f"chunk-{i}",
                    document_id=f"doc-{i}",
                    user_id=owner,
                    node_id=f"node-{i}",
                    source_kind="manual_text",
                    text="alpha evidence",
                    chunk_index=0,
                )
            )
        db.commit()
    for i, owner in enumerate(ids):
        index.replace_document(
            user_pk=owner,
            document_id=f"doc-{i}",
            source_kind="manual_text",
            rows=[
                {
                    "id": f"node-{i}",
                    "source_text": "alpha evidence",
                    "text": "alpha evidence",
                    "dense": vector,
                }
            ],
        )
    exact = index.dense_search(query_dense=vector, user_pk=ids[0], top_k=5)
    assert len(exact) == 1 and exact[0]["document_id"] == "doc-0"
    with sessions() as db:
        prepare(db, identity, ids[0])
        db.commit()
    monkeypatch.setattr(settings, "PGVECTOR_DENSE_INDEX_TYPE", "hnsw")
    assert [
        r["id"] for r in index.dense_search(query_dense=vector, user_pk=ids[0], top_k=5)
    ] == [r["id"] for r in exact]
    with sessions() as db:
        db.get(KnowledgeDocument, "doc-0").deleted_at = utc_now()
        db.commit()
    assert index.dense_search(query_dense=vector, user_pk=ids[0], top_k=5) == []
