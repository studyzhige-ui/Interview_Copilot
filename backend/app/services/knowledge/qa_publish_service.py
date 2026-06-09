"""Publish an interview QA's improved answer to the knowledge base (RFC §6.9).

One ``interview_qa`` -> one ``knowledge_documents(source_kind='improved_qa')``.
The KB doc's ``content_text`` is only ``question + improved_answer``; the full
original answer / score / critique / transcript provenance stay on the QA row.
``interview_qa.saved_document_id`` is the back-reference. Re-saving refreshes the
same doc (idempotent reindex: ingest delete-replaces the doc's chunks + Milvus).
"""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.models.interview_qa import InterviewQA
from app.models.interview_record import InterviewRecord
from app.models.knowledge import KnowledgeDocument

logger = logging.getLogger(__name__)

DEFAULT_CATEGORY = "我的弱项"


def build_qa_content(qa: InterviewQA) -> str:
    return (
        f"## 问题\n{(qa.question or '').strip()}\n\n"
        f"## 改进回答\n{(qa.improved_answer or '').strip()}"
    )


async def save_qa_to_knowledge(
    db: Session,
    *,
    user_pk: int,
    qa: InterviewQA,
    record: InterviewRecord,
    category: str = DEFAULT_CATEGORY,
) -> KnowledgeDocument:
    """Create or refresh the improved_qa knowledge doc for one QA + index it.

    The doc row + ``saved_document_id`` back-ref are committed BEFORE indexing,
    so an index hiccup never loses the save (a reindex recovers it).
    """
    content_text = build_qa_content(qa)

    doc: KnowledgeDocument | None = None
    if qa.saved_document_id:
        doc = (
            db.query(KnowledgeDocument)
            .filter(
                KnowledgeDocument.id == qa.saved_document_id,
                KnowledgeDocument.user_id == user_pk,
                KnowledgeDocument.deleted_at.is_(None),
            )
            .first()
        )
    if doc is None:
        doc = KnowledgeDocument(
            user_id=user_pk,
            source_kind="improved_qa",
            source_ref_type="interview_qa",
            source_ref_id=qa.id,
            source_interview_record_id=record.id,
            category=category,
        )
    doc.title = (qa.question or "改进问答").strip()[:120] or "改进问答"
    doc.content_text = content_text
    doc.category = category
    doc.status = "ready"
    doc.deleted_at = None
    db.add(doc)
    db.flush()  # assign doc.id
    qa.saved_document_id = doc.id
    db.add(qa)
    db.commit()
    db.refresh(doc)

    # Index the QA as one natural unit (Markdown content_text -> chunks + Milvus).
    from app.rag.ingestion import ingest_text

    result = await ingest_text(
        text=content_text, source_kind="improved_qa", user_id=user_pk,
        metadata={"category": category}, document_id=doc.id,
    )
    doc.chunk_count = int(result.get("chunk_count") or 0) if result else 0
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


def unsave_qa_from_knowledge(db: Session, *, user_pk: int, qa: InterviewQA) -> bool:
    """Delete the improved_qa knowledge doc saved from this QA + clear the ref.

    Returns False if the QA had no saved doc. Used both for an explicit "unsave"
    and for the optional cascade when an interview record is deleted.
    """
    if not qa.saved_document_id:
        return False
    doc = (
        db.query(KnowledgeDocument)
        .filter(
            KnowledgeDocument.id == qa.saved_document_id,
            KnowledgeDocument.user_id == user_pk,
        )
        .first()
    )
    if doc is not None:
        from app.services.knowledge.knowledge_service import hard_delete_knowledge_document

        hard_delete_knowledge_document(db, doc)
    qa.saved_document_id = None
    db.add(qa)
    db.commit()
    return True


def delete_saved_qa_docs_for_record(db: Session, *, user_pk: int, record_id: str) -> int:
    """Hard-delete every improved_qa knowledge doc produced by a record's QAs.

    Used when an interview is deleted and the user opts to also remove the
    knowledge documents it published. Returns the number of docs removed.
    """
    docs = (
        db.query(KnowledgeDocument)
        .filter(
            KnowledgeDocument.user_id == user_pk,
            KnowledgeDocument.source_kind == "improved_qa",
            KnowledgeDocument.source_interview_record_id == record_id,
            KnowledgeDocument.deleted_at.is_(None),
        )
        .all()
    )
    from app.services.knowledge.knowledge_service import hard_delete_knowledge_document

    removed = 0
    for doc in docs:
        try:
            hard_delete_knowledge_document(db, doc)
            removed += 1
        except Exception as exc:  # noqa: BLE001 — best-effort cascade
            logger.warning("cascade delete of improved_qa doc %s failed: %s", doc.id, exc)
    return removed
