"""Invalidate derived judgments inside the caller's locked record transaction."""

from __future__ import annotations

from app.db.types import utc_now


def invalidate_review(db, record, rows, *, message: str):
    """Return the archived report/QA snapshot. No commit or network side effects."""
    archived = {
        "generation": record.review_generation,
        "report": record.analysis_json,
        "questions": [
            {
                "qa_id": row.id,
                "version": row.version,
                "question": row.question,
                "answer": row.answer,
                "phase": row.phase,
                "order_idx": row.order_idx,
                "source_transcript_id": row.source_transcript_id,
                "source_provenance": row.source_provenance_json,
                "score": row.score,
                "critique": row.critique,
                "improved_answer": row.improved_answer,
                "key_points_json": row.key_points_json,
                "assessment": row.answer_quality_json,
                "saved_document_id": row.saved_document_id,
                "analyzed_at": row.analyzed_at.isoformat() if row.analyzed_at else None,
            }
            for row in rows
        ],
    }
    for row in rows:
        row.score = row.critique = row.improved_answer = None
        row.key_points_json = row.analyzed_at = row.answer_quality_json = None
        row.version += 1
    record.review_generation += 1
    record.ability_signal_generation += 1
    record.analysis_json = None
    record.analyzed_qa_count = 0
    record.completed_at = None
    record.status = "review_failed" if record.source == "mock" else "failed"
    record.error_message = message
    record.updated_at = utc_now()
    from app.career.application.signals import (
        invalidate_ability_signals_for_interview_reanalysis,
    )

    invalidate_ability_signals_for_interview_reanalysis(
        db, user_pk=record.user_id, interview_record_id=record.id
    )
    from app.models.knowledge import KnowledgeDocument

    ids = [row.saved_document_id for row in rows if row.saved_document_id]
    if ids:
        for doc in (
            db.query(KnowledgeDocument)
            .filter(
                KnowledgeDocument.id.in_(ids),
                KnowledgeDocument.user_id == record.user_id,
            )
            .all()
        ):
            doc.status = "stale"
            doc.error_message = "source_qa_corrected: 请重新分析并显式更新知识库内容"
            doc.updated_at = utc_now()
    return archived
