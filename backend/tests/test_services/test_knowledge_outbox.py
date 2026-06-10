"""C1 / §4.6.3: reliable Milvus knowledge-index delete via the shared outbox.

A document delete removes the Postgres facts first (read path correct at once);
if the Milvus row delete then fails, a ``milvus_delete_document`` outbox job is
queued for retry instead of raising or leaking un-cleaned vectors. The handler
is idempotent (delete-by-document_id).
"""
from __future__ import annotations

from types import SimpleNamespace

from app.models.document_chunk import DocumentChunk
from app.models.knowledge import KnowledgeDocument
from app.models.outbox_job import OutboxJob
from app.services.knowledge import knowledge_outbox as ko


def test_handle_milvus_delete_deletes_by_document_id(monkeypatch):
    calls = []
    import app.rag.milvus_hybrid as mh
    monkeypatch.setattr(mh, "delete_by_field", lambda coll, field, value: calls.append((field, value)))

    ko._handle_milvus_delete(None, SimpleNamespace(id="job1", aggregate_id="kdoc_x"))
    assert calls == [("document_id", "kdoc_x")]


def test_handle_milvus_delete_noop_without_document_id(monkeypatch):
    calls = []
    import app.rag.milvus_hybrid as mh
    monkeypatch.setattr(mh, "delete_by_field", lambda *a, **k: calls.append(a))

    ko._handle_milvus_delete(None, SimpleNamespace(id="job2", aggregate_id=None))
    assert calls == []  # no document_id → nothing to delete


def test_enqueue_milvus_delete_creates_keyed_job(db_session):
    ko.enqueue_milvus_delete(db_session, user_pk=1, document_id="kdoc_y")
    db_session.commit()

    jobs = db_session.query(OutboxJob).filter(
        OutboxJob.job_type == "milvus_delete_document").all()
    assert len(jobs) == 1
    assert jobs[0].aggregate_id == "kdoc_y"
    assert jobs[0].aggregate_type == "knowledge_document"
    assert jobs[0].idempotency_key == "milvus_delete_document:kdoc_y"


def test_enqueue_milvus_delete_coalesces_duplicates(db_session):
    ko.enqueue_milvus_delete(db_session, user_pk=1, document_id="kdoc_z")
    db_session.commit()
    ko.enqueue_milvus_delete(db_session, user_pk=1, document_id="kdoc_z")
    db_session.commit()

    jobs = db_session.query(OutboxJob).filter(OutboxJob.aggregate_id == "kdoc_z").all()
    assert len(jobs) == 1  # idempotency_key coalesces — a doc is deleted once


def test_delete_queues_outbox_when_milvus_fails(db_session, monkeypatch):
    from app.services.knowledge import knowledge_service as ks

    db_session.add(KnowledgeDocument(
        id="kdoc_f", user_id=1, title="t", source_kind="user_upload", status="deleting",
    ))
    db_session.add(DocumentChunk(
        document_id="kdoc_f", node_id="n1", user_id=1, source_kind="user_upload",
        chunk_index=0, text="x",
    ))
    db_session.commit()

    import app.rag.milvus_hybrid as mh
    def _boom(*a, **k):
        raise RuntimeError("milvus down")
    monkeypatch.setattr(mh, "delete_by_field", _boom)

    doc = db_session.query(KnowledgeDocument).filter(KnowledgeDocument.id == "kdoc_f").first()
    ks.delete_document_vectors_and_chunks(db_session, doc)

    # Facts are gone (read path correct), and the Milvus delete is queued.
    assert db_session.query(DocumentChunk).filter(
        DocumentChunk.document_id == "kdoc_f").count() == 0
    jobs = db_session.query(OutboxJob).filter(OutboxJob.aggregate_id == "kdoc_f").all()
    assert len(jobs) == 1 and jobs[0].job_type == "milvus_delete_document"


def test_delete_no_outbox_when_milvus_succeeds(db_session, monkeypatch):
    from app.services.knowledge import knowledge_service as ks

    db_session.add(KnowledgeDocument(
        id="kdoc_ok", user_id=1, title="t", source_kind="user_upload", status="deleting",
    ))
    db_session.add(DocumentChunk(
        document_id="kdoc_ok", node_id="n1", user_id=1, source_kind="user_upload",
        chunk_index=0, text="x",
    ))
    db_session.commit()

    import app.rag.milvus_hybrid as mh
    monkeypatch.setattr(mh, "delete_by_field", lambda *a, **k: None)

    doc = db_session.query(KnowledgeDocument).filter(KnowledgeDocument.id == "kdoc_ok").first()
    ks.delete_document_vectors_and_chunks(db_session, doc)

    assert db_session.query(OutboxJob).filter(OutboxJob.aggregate_id == "kdoc_ok").count() == 0
