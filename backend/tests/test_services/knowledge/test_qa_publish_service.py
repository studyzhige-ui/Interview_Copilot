"""Tests for qa_publish_service — improved_qa knowledge publishing (RFC §6.9).

Saving a QA's improved answer creates ONE knowledge_documents(improved_qa) with
content_text = question + improved_answer, back-fills interview_qa.saved_document_id,
is idempotent (re-save refreshes the same doc), and unsave removes it + clears the
ref. The Milvus/embedding index step is stubbed (out of scope for unit tests).
"""

from __future__ import annotations

import asyncio

import pytest


def test_save_refresh_and_unsave_qa(db_session, monkeypatch):
    from app.models.interview_qa import InterviewQA
    from app.models.interview_record import InterviewRecord
    from app.models.knowledge import KnowledgeDocument
    from app.models.user import User
    from app.services.knowledge import qa_publish_service

    user = User(username="alice", hashed_password="x")
    db_session.add(user)
    db_session.flush()
    rec = InterviewRecord(
        id="ir_1", user_id=user.id, source="mock", status="review_ready"
    )
    db_session.add(rec)
    qa = InterviewQA(
        id="qa_1",
        record_id="ir_1",
        order_idx=0,
        phase="technical",
        question="什么是缓存雪崩?",
        answer="原始回答",
        improved_answer="缓存雪崩是指大量缓存同时失效……",
    )
    db_session.add(qa)
    db_session.commit()

    # Stub the index step — no Milvus / embedding model in unit tests.
    async def _fake_ingest(**kwargs):
        assert kwargs["source_kind"] == "improved_qa"
        assert kwargs["document_id"]  # tied to the doc
        return {"chunk_count": 2, "node_ids": [], "ref_doc_ids": []}

    monkeypatch.setattr("app.rag.ingestion.ingest_text", _fake_ingest)

    doc = asyncio.run(
        qa_publish_service.save_qa_to_knowledge(
            db_session,
            user_pk=user.id,
            qa=qa,
            record=rec,
        )
    )
    assert doc.source_kind == "improved_qa"
    assert doc.source_ref_type == "interview_qa"
    assert doc.source_ref_id == "qa_1"
    assert doc.source_interview_record_id == "ir_1"
    assert doc.file_asset_id is None  # fileless
    assert "缓存雪崩" in (doc.content_text or "")
    assert doc.status == "ready"
    assert doc.chunk_count == 2

    qa2 = db_session.query(InterviewQA).filter(InterviewQA.id == "qa_1").first()
    assert qa2.saved_document_id == doc.id

    # Idempotent re-save: refresh the SAME doc, not a second one.
    doc2 = asyncio.run(
        qa_publish_service.save_qa_to_knowledge(
            db_session,
            user_pk=user.id,
            qa=qa2,
            record=rec,
        )
    )
    assert doc2.id == doc.id
    assert (
        db_session.query(KnowledgeDocument)
        .filter(KnowledgeDocument.source_ref_id == "qa_1")
        .count()
        == 1
    )

    # Unsave: drop the doc (stub the Milvus-touching hard delete) + clear the ref.
    deleted: dict = {}

    def _fake_delete(db, document):
        deleted["id"] = document.id
        db.delete(document)
        db.commit()

    monkeypatch.setattr(
        "app.services.knowledge.knowledge_service.hard_delete_knowledge_document",
        _fake_delete,
    )
    assert (
        qa_publish_service.unsave_qa_from_knowledge(db_session, user_pk=user.id, qa=qa2)
        is True
    )
    assert deleted["id"] == doc.id
    qa3 = db_session.query(InterviewQA).filter(InterviewQA.id == "qa_1").first()
    assert qa3.saved_document_id is None


def test_unsave_noop_when_not_saved(db_session):
    from app.models.interview_qa import InterviewQA
    from app.models.interview_record import InterviewRecord
    from app.models.user import User
    from app.services.knowledge import qa_publish_service

    user = User(username="bob", hashed_password="x")
    db_session.add(user)
    db_session.flush()
    db_session.add(
        InterviewRecord(
            id="ir_2", user_id=user.id, source="mock", status="review_ready"
        )
    )
    qa = InterviewQA(
        id="qa_2",
        record_id="ir_2",
        order_idx=0,
        phase="technical",
        question="q",
        answer="a",
    )
    db_session.add(qa)
    db_session.commit()

    assert (
        qa_publish_service.unsave_qa_from_knowledge(db_session, user_pk=user.id, qa=qa)
        is False
    )


def test_save_stays_processing_while_index_retry_is_queued(db_session, monkeypatch):
    from app.models.interview_qa import InterviewQA
    from app.models.interview_record import InterviewRecord
    from app.models.user import User
    from app.services.knowledge import qa_publish_service

    user = User(username="queued", hashed_password="x")
    db_session.add(user)
    db_session.flush()
    rec = InterviewRecord(
        id="ir_queued", user_id=user.id, source="mock", status="review_ready"
    )
    qa = InterviewQA(
        id="qa_queued",
        record_id=rec.id,
        order_idx=0,
        phase="technical",
        question="q",
        answer="a",
        improved_answer="better",
    )
    db_session.add_all([rec, qa])
    db_session.commit()

    async def queued_ingest(**_kwargs):
        return {"chunk_count": 1, "indexed": False}

    monkeypatch.setattr("app.rag.ingestion.ingest_text", queued_ingest)

    doc = asyncio.run(
        qa_publish_service.save_qa_to_knowledge(
            db_session,
            user_pk=user.id,
            qa=qa,
            record=rec,
        )
    )
    assert doc.status == "processing"
    assert "重试" in (doc.error_message or "")


def test_save_marks_document_failed_when_indexing_fails(db_session, monkeypatch):
    from app.models.interview_qa import InterviewQA
    from app.models.interview_record import InterviewRecord
    from app.models.knowledge import KnowledgeDocument
    from app.models.user import User
    from app.services.knowledge import qa_publish_service

    user = User(username="failed", hashed_password="x")
    db_session.add(user)
    db_session.flush()
    rec = InterviewRecord(
        id="ir_failed", user_id=user.id, source="mock", status="review_ready"
    )
    qa = InterviewQA(
        id="qa_failed",
        record_id=rec.id,
        order_idx=0,
        phase="technical",
        question="q",
        answer="a",
        improved_answer="better",
    )
    db_session.add_all([rec, qa])
    db_session.commit()

    async def failed_ingest(**_kwargs):
        raise RuntimeError("embedding unavailable")

    monkeypatch.setattr("app.rag.ingestion.ingest_text", failed_ingest)

    with pytest.raises(RuntimeError, match="embedding unavailable"):
        asyncio.run(
            qa_publish_service.save_qa_to_knowledge(
                db_session,
                user_pk=user.id,
                qa=qa,
                record=rec,
            )
        )

    doc = (
        db_session.query(KnowledgeDocument)
        .filter(KnowledgeDocument.source_ref_id == qa.id)
        .one()
    )
    assert doc.status == "failed"
    assert doc.error_message
