"""No provider calls in default plan, exact owner/category scopes and bounded cursors."""

from unittest.mock import MagicMock
from datetime import datetime
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
import app.models  # noqa: F401
from app.db.database import Base
from app.models.knowledge import KnowledgeDocument
import scripts.reingest_hybrid as script


@pytest.fixture
def data(monkeypatch):
    engine = create_engine("sqlite://", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    monkeypatch.setattr(script, "SessionLocal", factory)
    with factory() as db:
        for name, owner, category, kind, status in [
            ("a", 1, "题库", "manual_text", "ready"),
            ("b", 1, "笔记", "manual_text", "ready"),
            ("c", 2, "题库", "manual_text", "ready"),
            ("d", 1, "题库", "chat_attachment", "ready"),
            ("e", 1, "题库", "manual_text", "deleted"),
        ]:
            db.add(
                KnowledgeDocument(
                    id=name,
                    user_id=owner,
                    title=name,
                    category=category,
                    source_kind=kind,
                    status=status,
                    deleted_at=datetime.now() if status == "deleted" else None,
                )
            )
        db.commit()
    calls = []
    monkeypatch.setattr(
        "app.rag.index.knowledge.reindex_document", lambda doc: calls.append(doc) or 2
    )
    monkeypatch.setattr("app.rag.hybrid_index.validate_index_storage", lambda *a: None)
    monkeypatch.setattr(
        "app.rag.embedding_registry.build_embedding", lambda: MagicMock()
    )
    monkeypatch.setattr("llama_index.core.Settings", MagicMock())
    yield calls
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_default_only_plans_and_does_not_load_model(data, monkeypatch):
    monkeypatch.setattr(
        "app.rag.embedding_registry.build_embedding",
        lambda: pytest.fail("plan must not load model"),
    )
    report = script.reingest_knowledge()
    assert report["mode"] == "plan" and data == []
    assert [d["id"] for d in report["documents"]] == ["a", "b", "c"]


def test_execute_is_explicit_and_skips_private_deleted_sources(data):
    report = script.reingest_knowledge(execute=True)
    assert data == ["a", "b", "c"] and report["indexed_chunks"] == 6


def test_owner_and_category_filters_apply_even_to_explicit_ids(data):
    report = script.reingest_knowledge(
        user_id=1,
        category="题库",
        document_ids=["a", "b", "c", "missing"],
        execute=True,
    )
    assert data == ["a"] and report["completed_documents"] == ["a"]


def test_cursor_has_no_duplicate_or_lost_documents(data):
    first = script.reingest_knowledge(limit=2)
    second = script.reingest_knowledge(limit=2, after=first["next_cursor"])
    assert [d["id"] for d in first["documents"] + second["documents"]] == [
        "a",
        "b",
        "c",
    ]
    assert first["has_more"] and not second["has_more"]


def test_empty_owner_has_no_model_side_effect(data, monkeypatch):
    monkeypatch.setattr(
        "app.rag.embedding_registry.build_embedding", lambda: pytest.fail("empty batch")
    )
    assert script.reingest_knowledge(user_id=999, execute=True)["indexed_chunks"] == 0
    assert data == []


@pytest.mark.parametrize(
    "kwargs",
    [
        {"category": "题库"},
        {"limit": 0},
        {"limit": 1001},
        {"user_id": True},
        {"document_ids": []},
    ],
)
def test_invalid_batch_is_rejected(kwargs):
    with pytest.raises(ValueError):
        script.reingest_knowledge(**kwargs)


def test_drop_is_not_an_accepted_accidental_data_deletion_command():
    with pytest.raises(SystemExit):
        script.main(["--drop"])
