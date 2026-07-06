"""Interview analysis + record HTTP endpoints.

Thin router: auth, request validation, and HTTP status mapping only.
Business logic lives in ``app.services.interview`` (analysis_intake for
the /analyze flow, record_admin for owned-record maintenance,
interview_record_service for record persistence).
"""
import asyncio
import json
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.rate_limit import RATE_EXPENSIVE, limiter
from app.core.security import get_current_user
from app.core.user_identity import resolve_user_pk
from app.db.database import get_db
from app.models.interview_qa import InterviewQA
from app.models.user import User
from app.schemas.interview import (
    AnalyzeRequest,
    InterviewRecordListItem,
    InterviewRecordUpdateRequest,
    QAEditRequest,
    SaveQARequest,
)
from app.services.analytics.diagnostics_report_service import generate_comprehensive_report
from app.services.interview import analysis_intake, record_admin
from app.services.interview.interview_record_service import (
    STATUS_ANALYZING,
    STATUS_COMPLETED,
    STATUS_EXTRACTING,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_PROCESSING_REVIEW,
    STATUS_REVIEW_FAILED,
    STATUS_REVIEW_READY,
    STATUS_TRANSCRIBING,
    interview_record_service,
)
from app.api.file_assets import require_uploaded
from app.services.uploads.file_asset_service import (
    UPLOAD_STATUS_CONSUMED,
    get_owned_file_asset,
)

router = APIRouter()


@router.get("/uploads/resumes")
def list_user_resumes(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List the user's personal resumes — the first-class ``resumes`` entity.

    MockSetup / analyze setup pass the returned ``resume_id`` to start a mock or
    dispatch an analysis. Resumes are a personal-profile asset and are NOT
    knowledge documents.
    """
    from app.services.resume import resume_entity_service

    resumes = resume_entity_service.list_resumes(db, user_id=current_user.username)
    return {
        "resumes": [
            {
                "resume_id": r.id,
                "title": r.title,
                "is_default": bool(r.is_default),
                "parse_status": r.parse_status,
                "created_at": r.created_at.isoformat() if r.created_at else "",
            }
            for r in resumes
        ],
    }


@router.post("/analyze")
@limiter.limit(RATE_EXPENSIVE)
async def analyze_interview_endpoint(
    request: Request,
    response: Response,
    body: AnalyzeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create an InterviewRecord from an uploaded audio file and dispatch the
    unified analysis orchestrator."""
    try:
        upload = get_owned_file_asset(
            db,
            file_asset_id=body.upload_id,
            user_id=current_user.username,
            purpose="interview_audio",
        )
        if upload is None:
            raise HTTPException(status_code=404, detail="Audio upload not found")
        if upload.upload_status == UPLOAD_STATUS_CONSUMED:
            raise HTTPException(status_code=409, detail="Audio upload has already been consumed")
        # Confirm-on-consume (UP-1): verification (exists / size cap / magic)
        # can't be skipped by never calling /confirm.
        upload = require_uploaded(db, upload, "音频文件")

        try:
            resume_ctx = await analysis_intake.resolve_resume_context(
                db,
                user_id=current_user.username,
                resume_id=body.resume_id,
                resume_file_asset_id=body.resume_file_asset_id,
            )
        except analysis_intake.ResumeNotFound:
            raise HTTPException(status_code=404, detail="Resume not found")
        except analysis_intake.ResumeUploadNotFound:
            raise HTTPException(status_code=404, detail="Resume upload not found")

        jd_text, jd_file_asset_id = await analysis_intake.resolve_jd_context(
            db,
            user_id=current_user.username,
            jd_text=body.jd_text,
            jd_file_asset_id=body.jd_file_asset_id,
        )

        record, task = analysis_intake.create_record_and_dispatch(
            db,
            user_id=current_user.username,
            upload=upload,
            resume_ctx=resume_ctx,
            jd_text=jd_text,
            jd_file_asset_id=jd_file_asset_id,
            language=body.language,
        )

        return {
            "status": "processing",
            "message": "Task dispatched to background workers successfully.",
            "record_id": record.id,
            "task_id": task.id,
        }
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/analyze/{record_id}/cancel")
async def cancel_analysis(
    record_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Revoke a running analysis task. Used when the user discards the draft
    or deletes the in-flight record before completion."""
    record = record_admin.get_owned_record(db, record_id, current_user.username)
    if not record:
        raise HTTPException(status_code=404, detail="Interview record not found")
    revoked = record_admin.cancel_analysis(db, record)
    return {"status": "cancelled", "revoked": revoked, "record_id": record_id}


@router.get("/analytics/report")
async def get_analytics_report(
    limit: int = Query(20, description="Max personal memory items to scan."),
    current_user: User = Depends(get_current_user),
):
    try:
        return await generate_comprehensive_report(limit, user_id=current_user.username)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Failed to generate report: {exc}") from exc


# ── InterviewRecord endpoints ─────────────────────────────────────────


@router.get("/interview-records", response_model=List[InterviewRecordListItem])
def list_interview_records(
    current_user: User = Depends(get_current_user),
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
):
    records = interview_record_service.list_by_user(
        current_user.username, offset=offset, limit=limit,
    )
    return [
        InterviewRecordListItem(
            id=r.id,
            source=r.source,
            title=r.title or "",
            tag=r.tag,
            status=r.status,
            created_at=r.created_at.isoformat() if r.created_at else "",
        )
        for r in records
    ]


@router.get("/interview-records/{record_id}")
def get_interview_record(
    record_id: str,
    current_user: User = Depends(get_current_user),
):
    record = interview_record_service.get(record_id, current_user.username)
    if record is None:
        raise HTTPException(status_code=404, detail="Interview record not found")
    analysis = None
    if record.analysis_json:
        try:
            analysis = json.loads(record.analysis_json)
        except json.JSONDecodeError:
            analysis = None
    qa_rows = interview_record_service.list_qa(record_id)
    transcript = interview_record_service.get_transcript_payload(record_id)
    return {
        "id": record.id,
        "source": record.source,
        "title": record.title,
        "tag": record.tag,
        "category": record.category,
        "status": record.status,
        "analyzed_qa_count": record.analyzed_qa_count,
        "audio_file_asset_id": record.audio_file_asset_id,
        "resume_id": record.resume_id,
        "resume_file_asset_id": record.resume_file_asset_id,
        "resume_source": record.resume_source,
        "jd_file_asset_id": record.jd_file_asset_id,
        "transcript": transcript["text"],
        "transcript_segments": _safe_json_loads(transcript["segments_json"]),
        "interview_plan": _safe_json_loads(record.interview_plan),
        "analysis": analysis,
        "qa": [_serialize_qa(qa) for qa in qa_rows],
        "error_message": record.error_message,
        "created_at": record.created_at.isoformat() if record.created_at else "",
        "updated_at": record.updated_at.isoformat() if record.updated_at else "",
        "completed_at": record.completed_at.isoformat() if record.completed_at else None,
    }


def _safe_json_loads(value: Optional[str]) -> Optional[object]:
    if not value:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None


def _serialize_qa(qa: InterviewQA) -> dict:
    return {
        "id": qa.id,
        "order_idx": qa.order_idx,
        "phase": qa.phase,
        "phase_label": qa.phase_label,
        "question": qa.question,
        "answer": qa.answer,
        "question_summary": qa.question_summary,
        "is_follow_up": qa.is_follow_up,
        "follow_up_depth": qa.follow_up_depth,
        "grounding_refs": _safe_json_loads(qa.grounding_refs_json) or [],
        "score": qa.score,
        "critique": qa.critique,
        "improved_answer": qa.improved_answer,
        "key_points": _safe_json_loads(qa.key_points_json) or [],
        "answer_input_mode": qa.answer_input_mode,
        "question_audio_url": qa.question_audio_url,
        "answer_audio_url": qa.answer_audio_url,
        "source_segment_start": qa.source_segment_start,
        "source_segment_end": qa.source_segment_end,
        "analyzed_at": qa.analyzed_at.isoformat() if qa.analyzed_at else None,
        "saved_document_id": qa.saved_document_id,
    }


@router.get("/interview-records/{record_id}/summary")
def get_interview_record_summary(
    record_id: str,
    current_user: User = Depends(get_current_user),
):
    """Short analysis summary for context injection (slot 2)."""
    summary = interview_record_service.get_analysis_summary(record_id, current_user.username)
    if not summary:
        raise HTTPException(status_code=404, detail="Interview record or analysis not found")
    return {"summary": summary}


@router.patch("/interview-records/{record_id}")
def update_interview_record(
    record_id: str,
    payload: InterviewRecordUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    record = record_admin.get_owned_record(db, record_id, current_user.username)
    if record is None:
        raise HTTPException(status_code=404, detail="Interview record not found")
    changed = record_admin.update_record_fields(
        db, record, title=payload.title, tag=payload.tag,
    )
    if not changed:
        raise HTTPException(status_code=400, detail="No field to update")
    return {"status": "success", "id": record.id, "title": record.title, "tag": record.tag}


@router.delete("/interview-records/{record_id}")
def delete_interview_record(
    record_id: str,
    cascade_knowledge: bool = Query(False),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Hard-delete an interview record and every trace tied to it.

    See ``record_admin.delete_record_cascade`` for the full cascade
    contract (chat sessions go, v3 memory survives, knowledge docs only
    with ``cascade_knowledge=true``).
    """
    import logging

    record = record_admin.get_owned_record(db, record_id, current_user.username)
    if record is None:
        raise HTTPException(status_code=404, detail="Interview record not found")

    try:
        stats = record_admin.delete_record_cascade(
            db, record, cascade_knowledge=cascade_knowledge,
        )
        return {"status": "success", "id": record_id, **stats}
    except Exception as exc:  # noqa: BLE001
        logging.getLogger(__name__).exception(
            "delete_interview_record failed for record_id=%s user=%s: %s",
            record_id, current_user.username, exc,
        )
        raise HTTPException(
            status_code=500,
            detail=f"删除失败: {type(exc).__name__}: {exc}",
        ) from exc


@router.patch("/interview-records/{record_id}/qa/{qa_id}")
def edit_interview_qa(
    record_id: str,
    qa_id: str,
    payload: QAEditRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Edit a single InterviewQA row by id."""
    qa = record_admin.get_owned_qa(
        db, user_pk=resolve_user_pk(db, current_user.username),
        record_id=record_id, qa_id=qa_id,
    )
    if qa is None:
        raise HTTPException(status_code=404, detail="QA row not found")

    if payload.question is not None:
        qa.question = payload.question
    if payload.answer is not None:
        qa.answer = payload.answer
    if payload.critique is not None:
        qa.critique = payload.critique
    if payload.improved_answer is not None:
        qa.improved_answer = payload.improved_answer
    db.add(qa)
    db.commit()
    db.refresh(qa)
    return {"status": "success", "qa": _serialize_qa(qa)}


@router.post("/interview-records/{record_id}/qa/{qa_id}/save-to-knowledge")
@limiter.limit(RATE_EXPENSIVE)
async def save_qa_to_knowledge_endpoint(
    request: Request,
    response: Response,
    record_id: str,
    qa_id: str,
    body: SaveQARequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Publish a QA's improved answer to the knowledge base (RFC §6.9).

    Creates/refreshes a ``knowledge_documents(source_kind='improved_qa')`` from
    question + improved_answer, indexes it, and backfills ``saved_document_id``.
    """
    user_pk = resolve_user_pk(db, current_user.username)
    qa = record_admin.get_owned_qa(db, user_pk=user_pk, record_id=record_id, qa_id=qa_id)
    if qa is None:
        raise HTTPException(status_code=404, detail="QA row not found")
    if not (qa.improved_answer or "").strip():
        raise HTTPException(status_code=400, detail="该题暂无改进回答，无法保存到知识库")
    record = record_admin.get_owned_record(db, record_id, current_user.username)
    if record is None:
        raise HTTPException(status_code=404, detail="Interview record not found")
    from app.services.knowledge.qa_publish_service import (
        DEFAULT_CATEGORY,
        save_qa_to_knowledge,
    )
    try:
        doc = await save_qa_to_knowledge(
            db, user_pk=user_pk, qa=qa, record=record,
            category=(body.category or "").strip() or DEFAULT_CATEGORY,
        )
    except Exception as exc:  # noqa: BLE001
        from app.core.error_messages import humanize_error
        raise HTTPException(
            status_code=500, detail=f"保存到知识库失败：{humanize_error(exc)}",
        ) from exc
    return {
        "status": "success",
        "document_id": doc.id,
        "saved_document_id": qa.saved_document_id,
    }


@router.delete("/interview-records/{record_id}/qa/{qa_id}/save-to-knowledge")
def unsave_qa_from_knowledge_endpoint(
    record_id: str,
    qa_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Remove the knowledge document previously saved from this QA."""
    user_pk = resolve_user_pk(db, current_user.username)
    qa = record_admin.get_owned_qa(db, user_pk=user_pk, record_id=record_id, qa_id=qa_id)
    if qa is None:
        raise HTTPException(status_code=404, detail="QA row not found")
    from app.services.knowledge.qa_publish_service import unsave_qa_from_knowledge
    removed = unsave_qa_from_knowledge(db, user_pk=user_pk, qa=qa)
    return {"status": "success", "removed": removed}


# ── SSE progress stream ───────────────────────────────────────────────
#
# Status-driven progress bands (honest, not wall-clock guesses). Within a
# band the percent creeps slowly toward the ceiling; the analyzing band
# interpolates on REAL per-question progress (analyzed_qa_count/qa_total —
# the orchestrator bumps the counter per completed question).
_STAGE_BANDS: dict[str, tuple[int, int]] = {
    STATUS_PENDING: (2, 5),
    STATUS_TRANSCRIBING: (5, 50),
    STATUS_EXTRACTING: (50, 70),
    STATUS_ANALYZING: (70, 95),
    # Mock review runs the analyzing pipeline under its own status.
    STATUS_PROCESSING_REVIEW: (70, 95),
}
# The two bands with a real sub-progress signal (analyzed_qa_count/qa_total).
_INTERPOLATED_STAGES = {STATUS_ANALYZING, STATUS_PROCESSING_REVIEW}
# Slow in-band creep for stages with no sub-progress signal: +1% every
# 2 ticks (3s), capped 1 below the ceiling so a band can't lie about
# being finished.
_CREEP_TICKS_PER_PERCENT = 2

_TERMINAL_DONE = {STATUS_COMPLETED, STATUS_REVIEW_READY}
_TERMINAL_FAILED = {STATUS_FAILED, STATUS_REVIEW_FAILED}


@router.get("/interview-records/{record_id}/events")
async def interview_record_events_stream(
    record_id: str,
    current_user: User = Depends(get_current_user),
):
    """SSE progress stream for the unified analysis pipeline.

    Polls InterviewRecord.status + analyzed_qa_count/qa_total. Handles both
    sources: upload (pending→transcribing→extracting→analyzing→completed/
    failed) and mock (processing_review→review_ready/review_failed).

    Each poll opens its own short-lived DB session (via
    ``record_admin.poll_record_snapshot`` + ``asyncio.to_thread``) so
    concurrent viewers don't pin the connection pool. The owner check at
    the top does one short read; the generator opens its own sessions.
    """
    if not await asyncio.to_thread(
        record_admin.record_exists_for_user, record_id, current_user.username,
    ):
        raise HTTPException(status_code=404, detail="Interview record not found")

    POLL_INTERVAL = 1.5
    # Aligned with the analysis task's celery time_limit (30 min). The old
    # 8-minute cap fired "timeout" on analyses that were still legitimately
    # running — the most trust-destroying failure mode this stream had.
    MAX_TICKS = 1200

    async def event_generator():
        last_status: str | None = None
        last_percent = 0
        stage_entered_tick = 0
        try:
            for tick in range(MAX_TICKS):
                snap = await asyncio.to_thread(record_admin.poll_record_snapshot, record_id)
                if snap is None:
                    yield f"data: {json.dumps({'type': 'error', 'message': 'record disappeared'})}\n\n"
                    return
                status = snap["status"]
                if status != last_status:
                    last_status = status
                    stage_entered_tick = tick

                band = _STAGE_BANDS.get(status)
                if band is not None:
                    lo, hi = band
                    analyzed = snap["analyzed_qa_count"]
                    total = snap.get("qa_total") or 0
                    if status in _INTERPOLATED_STAGES and total > 0:
                        # Real progress: interpolate on questions completed.
                        percent = lo + int((hi - lo) * min(analyzed, total) / total)
                    else:
                        # No sub-progress signal — slow creep, honest cap.
                        ticks_in_stage = tick - stage_entered_tick
                        percent = min(hi - 1, lo + ticks_in_stage // _CREEP_TICKS_PER_PERCENT)
                    # Monotonic guard: interpolation can start below where
                    # creep already got to (qa_total lands mid-stage) and a
                    # retry resets the counter — never move the bar backwards.
                    percent = max(percent, last_percent)
                    last_percent = percent
                    yield "data: " + json.dumps(
                        {
                            "type": "progress",
                            "status": status,
                            "percent": percent,
                            "analyzed_qa_count": snap["analyzed_qa_count"],
                            "qa_total": snap.get("qa_total") or 0,
                        },
                        ensure_ascii=False,
                    ) + "\n\n"

                if status in _TERMINAL_DONE:
                    overall = {}
                    if snap["analysis_json"]:
                        try:
                            overall = (json.loads(snap["analysis_json"]) or {}).get("overall", {})
                        except json.JSONDecodeError:
                            overall = {}
                    yield "data: " + json.dumps(
                        {
                            "type": "done",
                            "record_id": snap["id"],
                            "status": status,
                            "percent": 100,
                            "analysis": {
                                "score": overall.get("score"),
                                "summary": overall.get("summary") or overall.get("feedback") or "",
                            },
                        },
                        ensure_ascii=False,
                    ) + "\n\n"
                    return
                if status in _TERMINAL_FAILED:
                    yield "data: " + json.dumps(
                        {
                            "type": "error",
                            "status": status,
                            "message": snap["error_message"] or "分析失败",
                        },
                        ensure_ascii=False,
                    ) + "\n\n"
                    return
                if band is None:
                    # Non-terminal but unbanded — e.g. a failed finish
                    # dispatch rolled the record back to mock_in_progress
                    # while we were streaming. There is no run to watch any
                    # more; end the stream instead of polling a dead record
                    # for the remaining 30 minutes.
                    yield "data: " + json.dumps(
                        {"type": "error", "status": status, "message": "分析已中止"},
                        ensure_ascii=False,
                    ) + "\n\n"
                    return
                await asyncio.sleep(POLL_INTERVAL)
            yield f"data: {json.dumps({'type': 'error', 'message': 'timeout'})}\n\n"
        except asyncio.CancelledError:
            # Client disconnect — every SessionLocal() opened inside
            # the loop was already ``with``-closed on its iteration,
            # so there's nothing to release here.
            return

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
