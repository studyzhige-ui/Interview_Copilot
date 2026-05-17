"""API tests for ``app.api.rag`` — knowledge document CRUD + query.

We patch storage (presigned URL) and Celery dispatch so tests don't touch
S3 or Redis.
"""
from __future__ import annotations

from typing import Iterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import rag as rag_mod
from app.core.security import get_current_user
from app.db.database import Base, get_db
import app.models  # noqa: F401  — register mappers
from app.models.knowledge import KnowledgeDocument
from app.models.upload import UserUpload


@pytest.fixture
def db() -> Iterator[Session]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session_ = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = Session_()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture
def client(db: Session) -> Iterator[TestClient]:
    class FakeUser:
        username = "alice"

    def fake_user() -> FakeUser:
        return FakeUser()

    def fake_db() -> Iterator[Session]:
        yield db

    app = FastAPI()
    app.include_router(rag_mod.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = fake_user
    app.dependency_overrides[get_db] = fake_db
    return TestClient(app)


# ── /rag/query ────────────────────────────────────────────────────────────


def test_rag_query_delegates_to_retriever(client):
    async def fake_query(q, source_type=None, user_id=None):
        assert user_id == "alice"
        return {"response": "answer", "source_nodes": []}

    with patch("app.api.rag.query_knowledge_base", side_effect=fake_query):
        resp = client.post(
            "/api/v1/rag/query",
            json={"query": "what is redis", "source_type": "official_docs"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    assert body["data"]["response"] == "answer"


def test_rag_query_500_on_retriever_error(client):
    async def boom(*_args, **_kwargs):
        raise RuntimeError("milvus down")

    with patch("app.api.rag.query_knowledge_base", side_effect=boom):
        resp = client.post("/api/v1/rag/query", json={"query": "x"})
    assert resp.status_code == 500


# ── /knowledge/upload/url ─────────────────────────────────────────────────


def test_create_upload_url_creates_user_upload(client, db: Session):
    fake_url_info = {"upload_url": "https://upload", "storage_uri": "s3://b/k"}
    with patch(
        "app.services.upload_service.generate_presigned_upload_url_for_key",
        return_value=fake_url_info,
    ):
        resp = client.post(
            "/api/v1/knowledge/upload/url",
            json={"filename": "redis.pdf", "content_type": "application/pdf"},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    upload_id = body["upload_id"]
    assert upload_id.startswith("upl_")
    row = db.query(UserUpload).filter(UserUpload.id == upload_id).first()
    assert row is not None
    assert row.user_id == "alice"
    assert row.purpose == "knowledge_document"


# ── /knowledge/documents (POST) ───────────────────────────────────────────


def test_create_document_404_when_upload_not_owned(client, db: Session):
    db.add(UserUpload(
        id="upl_b",
        user_id="bob",
        purpose="knowledge_document",
        original_filename="r.pdf",
        storage_uri="s3://b/uploads/bob/upl_b/r.pdf",
        object_key="uploads/bob/upl_b/r.pdf",
        status="uploaded",
    ))
    db.commit()
    resp = client.post(
        "/api/v1/knowledge/documents",
        json={"upload_id": "upl_b", "source_type": "interview_qa"},
    )
    assert resp.status_code == 404


def test_create_document_dispatches_celery_with_document_id(client, db: Session):
    db.add(UserUpload(
        id="upl_a",
        user_id="alice",
        purpose="knowledge_document",
        original_filename="redis.pdf",
        storage_uri="s3://b/uploads/alice/upl_a/redis.pdf",
        object_key="uploads/alice/upl_a/redis.pdf",
        status="uploaded",
    ))
    db.commit()

    fake_task = MagicMock()
    fake_task.id = "task-1"
    with patch("app.api.rag.process_document_ingestion") as mock_proc:
        mock_proc.delay.return_value = fake_task
        resp = client.post(
            "/api/v1/knowledge/documents",
            json={
                "upload_id": "upl_a",
                "title": "Redis Notes",
                "category": "Backend",
                "source_type": "interview_qa",
            },
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    document_id = body["document"]["id"]
    mock_proc.delay.assert_called_once_with(document_id)
    assert body["document"]["category"] == "Backend"
    assert body["document"]["title"] == "Redis Notes"
    assert body["document"]["task_id"] == "task-1"


def test_create_document_marks_failed_when_dispatch_explodes(client, db: Session):
    db.add(UserUpload(
        id="upl_a",
        user_id="alice",
        purpose="knowledge_document",
        original_filename="r.pdf",
        storage_uri="s3://b/uploads/alice/upl_a/r.pdf",
        object_key="uploads/alice/upl_a/r.pdf",
        status="uploaded",
    ))
    db.commit()

    with patch("app.api.rag.process_document_ingestion") as mock_proc:
        mock_proc.delay.side_effect = RuntimeError("redis broker offline")
        resp = client.post(
            "/api/v1/knowledge/documents",
            json={"upload_id": "upl_a", "source_type": "interview_qa"},
        )
    assert resp.status_code == 503

    # The document row should now exist with status='failed' so the UI
    # surfaces a real error rather than a forever-processing row.
    rows = db.query(KnowledgeDocument).filter(KnowledgeDocument.user_id == "alice").all()
    assert len(rows) == 1
    assert rows[0].status == "failed"
    assert "redis broker offline" in (rows[0].error_message or "")


# ── /knowledge/documents (GET list) ───────────────────────────────────────


def test_list_documents_is_user_scoped(client, db: Session):
    for user in ("alice", "bob"):
        db.add(UserUpload(
            id=f"upl_{user}",
            user_id=user,
            purpose="knowledge_document",
            original_filename=f"{user}.pdf",
            storage_uri=f"s3://b/uploads/{user}/upl_{user}/{user}.pdf",
            object_key=f"uploads/{user}/upl_{user}/{user}.pdf",
            status="consumed",
        ))
        db.add(KnowledgeDocument(
            id=f"doc_{user}",
            user_id=user,
            upload_id=f"upl_{user}",
            title=f"{user} doc",
            category="默认",
            source_type="interview_qa",
            storage_uri=f"s3://b/uploads/{user}/upl_{user}/{user}.pdf",
            object_key=f"uploads/{user}/upl_{user}/{user}.pdf",
            status="ready",
        ))
    db.commit()
    resp = client.get("/api/v1/knowledge/documents")
    assert resp.status_code == 200
    body = resp.json()
    titles = [d["title"] for d in body["documents"]]
    assert titles == ["alice doc"]


def test_list_documents_filters_by_category(client, db: Session):
    db.add(UserUpload(
        id="upl_a",
        user_id="alice",
        purpose="knowledge_document",
        original_filename="r.pdf",
        storage_uri="s3://b/x",
        object_key="x",
        status="consumed",
    ))
    db.add(KnowledgeDocument(
        id="doc_a", user_id="alice", upload_id="upl_a", title="A",
        category="Redis", source_type="interview_qa",
        storage_uri="s3://b/x", object_key="x", status="ready",
    ))
    db.add(UserUpload(
        id="upl_b",
        user_id="alice",
        purpose="knowledge_document",
        original_filename="r.pdf",
        storage_uri="s3://b/y",
        object_key="y",
        status="consumed",
    ))
    db.add(KnowledgeDocument(
        id="doc_b", user_id="alice", upload_id="upl_b", title="B",
        category="Java", source_type="interview_qa",
        storage_uri="s3://b/y", object_key="y", status="ready",
    ))
    db.commit()
    resp = client.get("/api/v1/knowledge/documents", params={"category": "Redis"})
    assert resp.status_code == 200
    ids = [d["id"] for d in resp.json()["documents"]]
    assert ids == ["doc_a"]


# ── /knowledge/documents/{id} (GET / PATCH / DELETE) ──────────────────────


def test_get_document_404_for_other_user(client, db: Session):
    db.add(UserUpload(
        id="upl_b", user_id="bob", purpose="knowledge_document",
        original_filename="r.pdf", storage_uri="s3://b/x",
        object_key="x", status="consumed",
    ))
    db.add(KnowledgeDocument(
        id="doc_b", user_id="bob", upload_id="upl_b", title="B",
        category="默认", source_type="interview_qa",
        storage_uri="s3://b/x", object_key="x", status="ready",
    ))
    db.commit()
    resp = client.get("/api/v1/knowledge/documents/doc_b")
    assert resp.status_code == 404


def test_patch_document_updates_title_and_category(client, db: Session):
    db.add(UserUpload(
        id="upl_a", user_id="alice", purpose="knowledge_document",
        original_filename="r.pdf", storage_uri="s3://b/x",
        object_key="x", status="consumed",
    ))
    db.add(KnowledgeDocument(
        id="doc_a", user_id="alice", upload_id="upl_a", title="old",
        category="默认", source_type="interview_qa",
        storage_uri="s3://b/x", object_key="x", status="ready",
    ))
    db.commit()
    resp = client.patch(
        "/api/v1/knowledge/documents/doc_a",
        json={"title": "new title", "category": "Redis"},
    )
    assert resp.status_code == 200
    db.expire_all()
    saved = db.query(KnowledgeDocument).filter(KnowledgeDocument.id == "doc_a").first()
    assert saved.title == "new title"
    assert saved.category == "Redis"


def test_delete_document_calls_hard_delete(client, db: Session):
    db.add(UserUpload(
        id="upl_a", user_id="alice", purpose="knowledge_document",
        original_filename="r.pdf", storage_uri="s3://b/x",
        object_key="x", status="consumed",
    ))
    db.add(KnowledgeDocument(
        id="doc_a", user_id="alice", upload_id="upl_a", title="t",
        category="默认", source_type="interview_qa",
        storage_uri="s3://b/x", object_key="x", status="ready",
    ))
    db.commit()
    with patch("app.api.rag.hard_delete_knowledge_document") as mock_del:
        resp = client.delete("/api/v1/knowledge/documents/doc_a")
    assert resp.status_code == 200
    mock_del.assert_called_once()


# ── /knowledge/categories ─────────────────────────────────────────────────


def test_list_categories_returns_counts(client, db: Session):
    for i, cat in enumerate(["Redis", "Redis", "Java"]):
        db.add(UserUpload(
            id=f"upl_{i}", user_id="alice", purpose="knowledge_document",
            original_filename=f"r{i}.pdf", storage_uri=f"s3://b/{i}",
            object_key=f"{i}", status="consumed",
        ))
        db.add(KnowledgeDocument(
            id=f"doc_{i}", user_id="alice", upload_id=f"upl_{i}", title=f"t{i}",
            category=cat, source_type="interview_qa",
            storage_uri=f"s3://b/{i}", object_key=f"{i}", status="ready",
        ))
    db.commit()
    resp = client.get("/api/v1/knowledge/categories")
    assert resp.status_code == 200
    counts = {row["category"]: row["count"] for row in resp.json()["categories"]}
    assert counts == {"Redis": 2, "Java": 1}
