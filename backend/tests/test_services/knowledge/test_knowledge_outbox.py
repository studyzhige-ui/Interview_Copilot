"""§4.6.3: reliable Milvus knowledge-index ops via the shared outbox.

C1 — delete: a document delete removes the Postgres facts first (read path
correct at once); a failed Milvus row delete queues a ``milvus_delete_document``
job instead of raising or leaking vectors. C2 — upsert: an ingest-time Milvus
write failure queues ``milvus_upsert_document`` (facts already pending, doc left
``processing``); the handler rebuilds from facts and flips the doc ``ready``, or
``failed`` once retries exhaust. Both handlers are idempotent.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from app.models.document_chunk import DocumentChunk
from app.models.knowledge import KnowledgeDocument
from app.models.outbox_job import OutboxJob
from app.services.knowledge import knowledge_outbox as ko


def _job(document_id, *, attempts=0, max_attempts=5):
    return SimpleNamespace(id="j", aggregate_id=document_id, attempts=attempts,
                           max_attempts=max_attempts)


def _upsert_job_row(db, document_id):
    return db.query(OutboxJob).filter(
        OutboxJob.aggregate_id == document_id,
        OutboxJob.job_type == "milvus_upsert_document",
    ).first()


def _doc_row(db, document_id):
    return db.query(KnowledgeDocument).filter(KnowledgeDocument.id == document_id).first()


def _make_due(db, document_id):
    """Clear an upsert job's backoff so the next drain re-claims it."""
    job = _upsert_job_row(db, document_id)
    job.next_run_at = datetime.utcnow() - timedelta(seconds=1)
    job.locked_at = None
    db.add(job)
    db.commit()


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


def test_enqueue_then_drain_runs_registered_handler(db_session, monkeypatch):
    """End-to-end through the real outbox loop: enqueue → run_due_outbox_jobs
    runs the REGISTERED handler → job reaches 'succeeded' and delete_by_field is
    called. The direct-handler tests above can't exercise the claim/run/status
    lifecycle this does."""
    import app.services.knowledge.knowledge_outbox  # noqa: F401 — registers handler
    from app.services.uploads.outbox_service import run_due_outbox_jobs

    calls = []
    import app.rag.milvus_hybrid as mh
    monkeypatch.setattr(mh, "delete_by_field", lambda coll, field, value: calls.append((field, value)))

    ko.enqueue_milvus_delete(db_session, user_pk=1, document_id="kdoc_drain")
    db_session.commit()

    processed = run_due_outbox_jobs(db_session)

    assert processed >= 1
    assert calls == [("document_id", "kdoc_drain")]
    job = db_session.query(OutboxJob).filter(OutboxJob.aggregate_id == "kdoc_drain").first()
    assert job.status == "succeeded"


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


# ── C2: milvus_upsert_document — ingest write-failure recovery ───────────────


def _seed_doc(db, doc_id, status="processing"):
    db.add(KnowledgeDocument(
        id=doc_id, user_id=1, title="t", source_kind="user_upload", status=status,
    ))
    db.commit()


def test_upsert_handler_rebuilds_and_marks_ready(db_session, monkeypatch):
    _seed_doc(db_session, "kdoc_u")
    import app.rag.ingestion as ing
    monkeypatch.setattr(ing, "reindex_document", lambda db, doc_id: 3)  # rebuild OK

    ko._handle_milvus_upsert(db_session, _job("kdoc_u"))

    doc = db_session.query(KnowledgeDocument).filter(KnowledgeDocument.id == "kdoc_u").first()
    assert doc.status == "ready" and doc.error_message is None


def test_upsert_handler_nonfinal_failure_stays_processing(db_session, monkeypatch):
    _seed_doc(db_session, "kdoc_u2")
    import app.rag.ingestion as ing
    def _boom(db, doc_id):
        raise RuntimeError("milvus down")
    monkeypatch.setattr(ing, "reindex_document", _boom)

    with pytest.raises(RuntimeError):
        ko._handle_milvus_upsert(db_session, _job("kdoc_u2", attempts=0))  # 4 retries left

    doc = db_session.query(KnowledgeDocument).filter(KnowledgeDocument.id == "kdoc_u2").first()
    assert doc.status == "processing"  # not terminal yet — outbox will retry


def test_upsert_handler_final_failure_marks_failed(db_session, monkeypatch):
    _seed_doc(db_session, "kdoc_u3")
    import app.rag.ingestion as ing
    def _boom(db, doc_id):
        raise RuntimeError("milvus down")
    monkeypatch.setattr(ing, "reindex_document", _boom)

    with pytest.raises(RuntimeError):
        # attempts=4, max=5 → this attempt exhausts the job (4 + 1 >= 5).
        ko._handle_milvus_upsert(db_session, _job("kdoc_u3", attempts=4))

    doc = db_session.query(KnowledgeDocument).filter(KnowledgeDocument.id == "kdoc_u3").first()
    assert doc.status == "failed" and "重试" in (doc.error_message or "")


def test_upsert_handler_does_not_resurrect_deleting_doc(db_session, monkeypatch):
    """A delete that happened while the upsert was queued must not be undone:
    reindex clears Milvus (0 live chunks) but the 'deleting' status is kept."""
    _seed_doc(db_session, "kdoc_del", status="deleting")
    import app.rag.ingestion as ing
    monkeypatch.setattr(ing, "reindex_document", lambda db, doc_id: 0)  # no live chunks

    ko._handle_milvus_upsert(db_session, _job("kdoc_del"))

    doc = db_session.query(KnowledgeDocument).filter(KnowledgeDocument.id == "kdoc_del").first()
    assert doc.status == "deleting"  # NOT resurrected to ready


def test_enqueue_milvus_upsert_is_repeatable(db_session):
    ko.enqueue_milvus_upsert(db_session, user_pk=1, document_id="kdoc_up")
    db_session.commit()
    ko.enqueue_milvus_upsert(db_session, user_pk=1, document_id="kdoc_up")
    db_session.commit()

    jobs = db_session.query(OutboxJob).filter(
        OutboxJob.aggregate_id == "kdoc_up",
        OutboxJob.job_type == "milvus_upsert_document",
    ).all()
    assert len(jobs) == 2  # no idempotency_key — re-ingest can re-queue


# ── C2 end-to-end through the REAL outbox runner (claim / attempts++ / status) ─


def test_upsert_drain_persistent_failure_ends_dead_and_doc_failed(db_session, monkeypatch):
    """Drive the real run_due_outbox_jobs lifecycle: a persistently-failing
    upsert increments attempts 1→5; the job goes 'dead' and the document goes
    'failed' on the SAME (5th) drain — the off-by-one boundary — with the doc
    kept 'processing' on runs 1–4."""
    import app.services.knowledge.knowledge_outbox  # noqa: F401 — registers handler
    from app.services.uploads.outbox_service import run_due_outbox_jobs
    import app.rag.ingestion as ing

    _seed_doc(db_session, "kdoc_e2e")  # status=processing
    def _boom(db, doc_id):
        raise RuntimeError("milvus down")
    monkeypatch.setattr(ing, "reindex_document", _boom)
    ko.enqueue_milvus_upsert(db_session, user_pk=1, document_id="kdoc_e2e")
    db_session.commit()

    for run in range(1, 6):
        _make_due(db_session, "kdoc_e2e")
        run_due_outbox_jobs(db_session)
        if run < 5:
            assert _upsert_job_row(db_session, "kdoc_e2e").status == "failed", f"run {run}"
            assert _doc_row(db_session, "kdoc_e2e").status == "processing", f"run {run}"
        else:
            assert _upsert_job_row(db_session, "kdoc_e2e").status == "dead"
            assert _doc_row(db_session, "kdoc_e2e").status == "failed"


def test_upsert_drain_recovers_to_ready(db_session, monkeypatch):
    """Fail once, then succeed: the document graduates 'processing' → 'ready'
    through the real runner (the primary recovery path C2 exists for)."""
    import app.services.knowledge.knowledge_outbox  # noqa: F401
    from app.services.uploads.outbox_service import run_due_outbox_jobs
    import app.rag.ingestion as ing

    _seed_doc(db_session, "kdoc_rec")
    calls = {"n": 0}
    def _flaky(db, doc_id):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("milvus blip")
        return 2
    monkeypatch.setattr(ing, "reindex_document", _flaky)
    ko.enqueue_milvus_upsert(db_session, user_pk=1, document_id="kdoc_rec")
    db_session.commit()

    run_due_outbox_jobs(db_session)  # attempt 1: fails
    assert _doc_row(db_session, "kdoc_rec").status == "processing"

    _make_due(db_session, "kdoc_rec")
    run_due_outbox_jobs(db_session)  # attempt 2: succeeds
    assert _upsert_job_row(db_session, "kdoc_rec").status == "succeeded"
    assert _doc_row(db_session, "kdoc_rec").status == "ready"


def test_upsert_drain_does_not_resurrect_hard_deleted_doc(db_session, monkeypatch):
    """Delete-race end-to-end with the REAL reindex_document: a doc deleted while
    its upsert was queued reads 0 live chunks → Milvus is cleared and the doc
    stays 'deleting' (never resurrected to ready)."""
    import app.services.knowledge.knowledge_outbox  # noqa: F401
    from app.rag.document_chunk_service import delete_document_chunks
    from app.services.uploads.outbox_service import run_due_outbox_jobs

    _seed_doc(db_session, "kdoc_race")  # processing
    db_session.add(DocumentChunk(
        document_id="kdoc_race", node_id="n1", user_id=1, source_kind="user_upload",
        chunk_index=0, text="x", index_status="pending",
    ))
    db_session.commit()
    ko.enqueue_milvus_upsert(db_session, user_pk=1, document_id="kdoc_race")
    db_session.commit()

    # The delete happens while the upsert is queued: mark deleting + hard-delete
    # the chunks (mirrors hard_delete_knowledge_document's order).
    doc = _doc_row(db_session, "kdoc_race")
    doc.status = "deleting"
    db_session.add(doc)
    db_session.commit()
    delete_document_chunks(db_session, "kdoc_race")

    deletes: list = []
    import app.rag.milvus_hybrid as mh
    monkeypatch.setattr(mh, "delete_by_field", lambda coll, field, value: deletes.append(value))

    run_due_outbox_jobs(db_session)

    assert _doc_row(db_session, "kdoc_race").status == "deleting"  # NOT resurrected
    assert deletes == ["kdoc_race"]  # 0 live chunks → Milvus cleared
