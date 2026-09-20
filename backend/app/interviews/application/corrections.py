"""Owned QA correction is one versioned transaction, not an in-place UI patch."""

from __future__ import annotations

from sqlalchemy.orm import Session
from app.core.command_errors import CommandError
from app.core.user_identity import resolve_user_pk
from app.db.types import utc_now
from app.interviews.application.review_fence import lock_record
from app.models.interview_qa import InterviewQA
from app.models.interview_qa_revision import InterviewQARevision
from app.schemas.interview import QAEditRequest

_FIELDS = ("question", "answer", "critique", "improved_answer")


def edit_qa(
    db: Session, *, record_id: str, qa_id: str, payload: QAEditRequest, current_user
):
    user_pk = resolve_user_pk(db, current_user.username)
    record = lock_record(db, record_id)
    if record is None or record.user_id != user_pk:
        raise CommandError("not_found", "QA row not found")
    qa = (
        db.query(InterviewQA)
        .filter(InterviewQA.record_id == record_id, InterviewQA.id == qa_id)
        .with_for_update()
        .populate_existing()
        .first()
    )
    if qa is None:
        raise CommandError("not_found", "QA row not found")
    if qa.version != payload.expected_version:
        raise CommandError(
            "conflict", "答案版本已改变。请核对最新内容后重新保存，未覆盖你的修改。"
        )
    if record.status == "mock_in_progress":
        raise CommandError("conflict", "进行中的面试请先结束，再纠正复盘证据。")
    changes = {
        field: getattr(payload, field)
        for field in _FIELDS
        if getattr(payload, field) is not None
        and getattr(payload, field) != getattr(qa, field)
    }
    if not changes:
        db.rollback()
        return qa

    before = {field: getattr(qa, field) for field in _FIELDS}
    all_rows = (
        db.query(InterviewQA)
        .filter(InterviewQA.record_id == record_id)
        .order_by(InterviewQA.order_idx)
        .with_for_update()
        .all()
    )
    # Preserve the last report and per-question judgments before invalidating.
    archived = {
        "generation": record.review_generation,
        "report": record.analysis_json,
        "questions": [
            {
                "qa_id": row.id,
                "version": row.version,
                "score": row.score,
                "critique": row.critique,
                "improved_answer": row.improved_answer,
                "key_points_json": row.key_points_json,
                "assessment": row.answer_quality_json,
                "analyzed_at": row.analyzed_at.isoformat() if row.analyzed_at else None,
            }
            for row in all_rows
        ],
    }
    for row in all_rows:
        row.score = None
        row.critique = None
        row.improved_answer = None
        row.key_points_json = None
        row.analyzed_at = None
        row.answer_quality_json = None
    for field, value in changes.items():
        setattr(qa, field, value)
    # Every sibling's analysis version changes too: a stale editor may not
    # inadvertently restore a feedback value that was just invalidated.
    for row in all_rows:
        row.version += 1
    qa.source_provenance_json = {
        **(qa.source_provenance_json or {}),
        "manual_override": {
            **((qa.source_provenance_json or {}).get("manual_override") or {}),
            **{field: True for field in ("question", "answer") if field in changes},
            "updated_at": utc_now().isoformat(),
        },
    }
    record.review_generation += 1
    record.ability_signal_generation += 1
    record.analysis_json = None
    record.analyzed_qa_count = 0
    record.completed_at = None
    record.status = "review_failed" if record.source == "mock" else "failed"
    record.error_message = (
        "内容已纠正，旧评分已失效。请明确重新分析；不会自动产生模型调用。"
    )
    record.updated_at = utc_now()
    from app.career.application.signals import (
        invalidate_ability_signals_for_interview_reanalysis,
    )

    invalidate_ability_signals_for_interview_reanalysis(
        db, user_pk=user_pk, interview_record_id=record_id
    )

    from app.models.knowledge import KnowledgeDocument

    document_ids = [row.saved_document_id for row in all_rows if row.saved_document_id]
    if document_ids:
        for doc in (
            db.query(KnowledgeDocument)
            .filter(
                KnowledgeDocument.id.in_(document_ids),
                KnowledgeDocument.user_id == user_pk,
            )
            .all()
        ):
            # Canonical hydration excludes non-ready documents; never serve an
            # old improved answer as if it still described current evidence.
            doc.status = "stale"
            doc.error_message = "source_qa_corrected: 请重新分析并显式更新知识库内容"
            doc.updated_at = utc_now()
    receipt = InterviewQARevision(
        record_id=record_id,
        qa_id=qa_id,
        author_id=user_pk,
        previous_version=payload.expected_version,
        new_version=qa.version,
        before_json=before,
        after_json={field: getattr(qa, field) for field in _FIELDS},
        invalidated_review_json=archived,
    )
    db.add(receipt)
    db.commit()
    db.refresh(qa)
    return qa


def list_corrections(
    db: Session,
    *,
    record_id: str,
    user_pk: int,
    before: str | None = None,
    limit: int = 30,
):
    from app.models.interview_record import InterviewRecord

    record = (
        db.query(InterviewRecord.id)
        .filter(InterviewRecord.id == record_id, InterviewRecord.user_id == user_pk)
        .first()
    )
    if record is None:
        raise CommandError("not_found", "Interview record not found")
    # Pagination by an explicit offset belongs to a stable record-local order.
    # Use a monotonic created_at/id cursor to avoid exporting unbounded history.
    query = db.query(InterviewQARevision).filter(
        InterviewQARevision.record_id == record_id
    )
    if before:
        anchor = query.filter(InterviewQARevision.id == before).first()
        if anchor is None:
            raise CommandError("invalid", "invalid history cursor")
        from sqlalchemy import or_, and_

        query = query.filter(
            or_(
                InterviewQARevision.created_at < anchor.created_at,
                and_(
                    InterviewQARevision.created_at == anchor.created_at,
                    InterviewQARevision.id < anchor.id,
                ),
            )
        )
    rows = (
        query.order_by(
            InterviewQARevision.created_at.desc(), InterviewQARevision.id.desc()
        )
        .limit(limit + 1)
        .all()
    )
    return {
        "items": [
            {
                "id": row.id,
                "qa_id": row.qa_id,
                "previous_version": row.previous_version,
                "new_version": row.new_version,
                "before": row.before_json,
                "after": row.after_json,
                "created_at": row.created_at.isoformat(),
            }
            for row in rows[:limit]
        ],
        "next_cursor": rows[limit - 1].id if len(rows) > limit else None,
    }
