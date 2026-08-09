"""Semantic index identity and generation reconciliation."""

from app.models.knowledge import KnowledgeDocument
from app.models.outbox_job import OutboxJob
from app.models.user import User
from app.rag.index.identity import current_index_identity
from app.rag.index.reconciliation import enqueue_stale_documents


def test_same_dimension_model_change_creates_new_index_generation(monkeypatch):
    from app.rag.index import identity

    monkeypatch.setattr(identity.settings, "EMBEDDING_MODEL", "model-a")
    first = current_index_identity()
    monkeypatch.setattr(identity.settings, "EMBEDDING_MODEL", "model-b")
    second = current_index_identity()

    assert first.embedding_dim == second.embedding_dim
    assert first.fingerprint != second.fingerprint
    assert first.physical_collection("knowledge") != second.physical_collection(
        "knowledge"
    )


def test_chunk_contract_change_creates_new_index_generation(monkeypatch):
    from app.rag.index import identity

    first = current_index_identity()
    monkeypatch.setattr(
        identity.settings,
        "RAG_CHUNK_TOKENS",
        identity.settings.RAG_CHUNK_TOKENS - 1,
    )
    second = current_index_identity()

    assert first.fingerprint != second.fingerprint


def test_generation_reconciliation_is_idempotent(db_session):
    active = current_index_identity().fingerprint
    user = User(
        id=9917,
        username="rag-generation-user",
        hashed_password="x",
    )
    document = KnowledgeDocument(
        id="rag-generation-document",
        user_id=user.id,
        title="Generation test",
        source_kind="manual_text",
        status="ready",
        index_fingerprint="stale" if active != "stale" else None,
    )
    db_session.add_all([user, document])
    db_session.commit()

    assert enqueue_stale_documents(db_session) == 1
    assert enqueue_stale_documents(db_session) == 0
    jobs = (
        db_session.query(OutboxJob).filter(OutboxJob.aggregate_id == document.id).all()
    )

    assert len(jobs) == 1
    assert jobs[0].idempotency_key == f"rag-generation:{document.id}:{active}"
