"""Mock-interview run orchestration (target architecture, RFC §6.4).

The start flow OWNS creation of the whole run — it atomically creates the
``interview_records`` (status=mock_in_progress), the ``conversations``
(type=mock_interview, bound via subject_type/subject_id) and the
``mock_interview_runtime`` (status=in_progress) in one transaction.
Subsequent operations address the run by ``record_id``.

The process transcript lives in ``conversation_messages``; the structured QA +
scoring is frozen into ``interview_qa`` by the unified analysis orchestrator
(shared with the upload-audio debrief path).

The API router keeps HTTP mapping only; LLM planning/turn generation stays in
``mock_interview_service``; runtime row CRUD in ``mock_runtime_service``.

Transaction ownership: ``submit_answer`` and ``dispatch_review`` COMMIT
internally (two-phase / rollback semantics they own); ``start_mock`` and
``abandon_mock`` flush only — their endpoints commit.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.user_identity import resolve_user_pk
from app.models.chat import Conversation, ConversationMessage, generate_uuid
from app.models.interview_record import InterviewRecord
from app.services.interview import mock_runtime_service
from app.services.interview import mock_interview_service
from app.services.interview.interview_record_service import (
    STATUS_MOCK_IN_PROGRESS,
    STATUS_PROCESSING_REVIEW,
    interview_record_service,
)
from app.worker.tasks import process_interview_analysis

logger = logging.getLogger(__name__)


# Rules-layer hard bound (MOCK-5): once the candidate has answered this
# many turns, ready_to_finish is FORCED true regardless of what the LLM
# says. Lives here — next to the enforcement in submit_answer — not in the
# LLM service, which never reads it.
MOCK_MAX_ANSWERED_TURNS = 30


class StaleQuestionError(ValueError):
    """The answer references a question that is no longer current — a
    concurrent submit already advanced the interview (MOCK-3)."""


# ── Message helpers ──────────────────────────────────────────────────────


def append_message(
    db: Session,
    conversation_id: str,
    role: str,
    content: str,
    *,
    content_blocks_json: str | None = None,
) -> ConversationMessage:
    """Append one message to a conversation (monotonic seq). Flushes so the
    autoincrement id is available to the caller (the runtime records the
    awaiting-answer message id)."""
    max_seq = (
        db.query(func.max(ConversationMessage.seq))
        .filter(ConversationMessage.conversation_id == conversation_id)
        .scalar()
    )
    msg = ConversationMessage(
        conversation_id=conversation_id,
        seq=(max_seq or 0) + 1,
        role=role,
        content=content,
        content_blocks_json=content_blocks_json,
    )
    db.add(msg)
    db.flush()
    return msg


def recent_messages(db: Session, conversation_id: str, limit: int = 8) -> list[dict[str, str]]:
    rows = (
        db.query(ConversationMessage)
        .filter(ConversationMessage.conversation_id == conversation_id)
        .order_by(ConversationMessage.seq.desc())
        .limit(limit)
        .all()
    )
    rows.reverse()
    return [{"role": r.role, "content": r.content or ""} for r in rows]


# ── Resume / JD context resolution ───────────────────────────────────────


def extract_file_asset_text(db: Session, asset_id: str, username: str) -> str:
    """Best-effort: download an owned file asset and extract its plain text."""
    try:
        from app.services.uploads.file_asset_service import (
            READABLE_UPLOAD_STATUSES,
            get_file_asset,
        )
        from app.services.voice.file_parser import extract_resume_text

        asset = get_file_asset(db, asset_id)
        if asset is None or asset.user_id != resolve_user_pk(db, username):
            return ""
        if asset.upload_status not in READABLE_UPLOAD_STATUSES:
            # Never parse unverified bytes; the start endpoint gates its own
            # uploads with require_uploaded, so this is the backstop for any
            # other caller.
            return ""
        storage_uri = asset.storage_uri
        local_path = storage_uri
        is_temp = False
        if storage_uri and storage_uri.startswith("s3://"):
            from app.core.storage import download_file_from_s3

            _, ext = os.path.splitext(storage_uri)
            tmp_fd, local_path = tempfile.mkstemp(suffix=ext)
            os.close(tmp_fd)
            download_file_from_s3(storage_uri, local_path)
            is_temp = True
        try:
            return (extract_resume_text(local_path) or "").strip()
        finally:
            if is_temp and local_path and os.path.exists(local_path):
                os.unlink(local_path)
    except Exception as exc:  # noqa: BLE001
        logger.warning("mock file-asset text extraction failed for %s: %s", asset_id, exc)
        return ""


def resolve_resume_context(
    db: Session,
    *,
    username: str,
    resume_id: str | None,
    resume_file_asset_id: str | None,
) -> tuple[str, str | None]:
    """Return (resume_text, resume_source) from a personal resume entity or an
    uploaded resume file asset. Empty string when neither is provided."""
    if resume_id:
        try:
            from app.services.resume import resume_entity_service
            from app.services.resume.resume_service import resume_service

            resume = resume_entity_service.get_owned_resume(
                db, resume_id=resume_id, user_id=username,
            )
            if resume is not None:
                sections = resume_service.get_sections_by_resume(resume.id)
                if sections:
                    return resume_service.format_for_context(sections), "personal_resume"
                if (resume.raw_text_snapshot or "").strip():
                    return resume.raw_text_snapshot.strip(), "personal_resume"
        except Exception as exc:  # noqa: BLE001
            logger.warning("mock resume context load failed: %s", exc)
        return "", None
    if resume_file_asset_id:
        text = extract_file_asset_text(db, resume_file_asset_id, username)
        return text, ("context_upload" if text else None)
    return "", None


def resolve_jd_context(
    db: Session,
    *,
    username: str,
    jd_text: str | None,
    jd_file_asset_id: str | None,
) -> str:
    if (jd_text or "").strip():
        return jd_text.strip()
    if jd_file_asset_id:
        return extract_file_asset_text(db, jd_file_asset_id, username)
    return ""


# ── Ownership ────────────────────────────────────────────────────────────


def get_owned_mock_record(db: Session, record_id: str, username: str) -> InterviewRecord | None:
    return (
        db.query(InterviewRecord)
        .filter(
            InterviewRecord.id == record_id,
            InterviewRecord.user_id == resolve_user_pk(db, username),
            InterviewRecord.source == "mock",
        )
        .first()
    )


# ── Run lifecycle ────────────────────────────────────────────────────────


@dataclass
class StartedMock:
    record: InterviewRecord
    conversation: Conversation
    runtime: object
    plan: object


def start_mock(
    db: Session,
    *,
    username: str,
    resume_id: str | None,
    resume_file_asset_id: str | None,
    jd_text: str | None,
    jd_file_asset_id: str | None,
    interviewer_style: str | None,
    plan_template_key: str | None,
    voice_mode: bool | None,
) -> StartedMock:
    """Atomically create record + conversation + opening message + runtime.

    Flushes everything into ONE uncommitted transaction — the caller commits
    (so it can offload the commit to a thread) and rolls back on failure.
    """
    resume_context, resume_source = resolve_resume_context(
        db, username=username,
        resume_id=resume_id, resume_file_asset_id=resume_file_asset_id,
    )
    jd_context = resolve_jd_context(
        db, username=username, jd_text=jd_text, jd_file_asset_id=jd_file_asset_id,
    )

    plan = mock_interview_service.generate_plan(
        resume_context=resume_context,
        jd_context=jd_context,
        interviewer_style=interviewer_style,
        plan_template_key=plan_template_key,
    )

    # 1) record (mock_in_progress) — freezes the resume/JD snapshots + plan.
    record = interview_record_service.create_for_mock(
        user_id=username,
        title="模拟面试",
        resume_id=resume_id,
        resume_file_asset_id=resume_file_asset_id,
        resume_source=resume_source,
        jd_file_asset_id=jd_file_asset_id,
        resume_text_snapshot=resume_context,
        jd_text_snapshot=jd_context,
        interview_plan=plan.plan_json,
        status=STATUS_MOCK_IN_PROGRESS,
        db=db,
    )

    # 2) conversation (bound to the record via subject_type/subject_id).
    conversation = Conversation(
        id=generate_uuid(),
        user_id=resolve_user_pk(db, username),
        title="模拟面试",
        type="mock_interview",
        mode="chat",
        subject_type="interview_record",
        subject_id=record.id,
    )
    db.add(conversation)
    db.flush()

    # 3) opening interviewer message (stage meta rides in a content block —
    # the review pipeline reads it back for per-stage attribution, MOCK-8).
    opening = append_message(
        db, conversation.id, "assistant", plan.opening_message,
        content_blocks_json=json.dumps(
            [{"type": "stage", "stage_key": plan.first_stage_key}], ensure_ascii=False,
        ),
    )

    # 4) runtime (in_progress), pointed at the opening question.
    runtime = mock_runtime_service.create_runtime(
        db,
        user_id=username,
        interview_record_id=record.id,
        conversation_id=conversation.id,
        plan=plan.stages,
        plan_template_key=plan.template_key,
        interviewer_style=interviewer_style,
        voice_mode=voice_mode,
        current_stage_key=plan.first_stage_key,
        commit=False,
    )
    runtime.current_question_text = plan.opening_message
    runtime.current_question_message_id = opening.id

    return StartedMock(record=record, conversation=conversation, runtime=runtime, plan=plan)


async def submit_answer(
    db: Session,
    *,
    record: InterviewRecord,
    runtime,
    answer_text: str,
    answer_audio_file_asset_id: str | None,
    user_id: str | None = None,
    question_message_id: int | None = None,
):
    """One turn in TWO short transactions (MOCK-4):

      A. persist the candidate's answer and COMMIT — the LLM call below can
         take tens of seconds and must not hold row locks / a connection
         mid-transaction. A retry after a failed interviewer turn (same
         text, last message is the dangling answer) is deduped, so the
         answer is never double-recorded.
      B. persist the interviewer's reply + advance the runtime and COMMIT.

    ``question_message_id`` (MOCK-3): optimistic concurrency token — the FE
    echoes back the id of the question it is answering; a mismatch means a
    concurrent submit already advanced the interview → StaleQuestionError
    (409 at the API). Legacy clients that don't send it keep the old
    last-write-wins behaviour.

    Returns the ``NextTurn`` with ``question_message_id`` set to the new
    interviewer message's id.
    """
    conversation_id = runtime.conversation_id

    if (
        question_message_id is not None
        and runtime.current_question_message_id is not None
        and question_message_id != runtime.current_question_message_id
    ):
        raise StaleQuestionError(
            f"answer targets message {question_message_id}, current is "
            f"{runtime.current_question_message_id}"
        )

    stages = mock_interview_service.stages_from_plan_json(runtime.plan_json)
    current_stage = runtime.current_stage_key or stages[0]["key"]
    prefix = mock_interview_service.build_prefix(
        record.resume_text_snapshot or "",
        record.jd_text_snapshot or "",
        runtime.interviewer_style,
    )
    # Prior dialog (everything BEFORE this answer) for context. The new answer
    # is passed separately as ``user_answer`` so it isn't double-counted in the
    # prompt — read recent first, then persist the answer.
    recent = recent_messages(db, conversation_id, limit=8)
    asked = list_asked_questions(db, conversation_id)

    # ── Phase A: persist the answer, commit ─────────────────────────
    last = _last_message(db, conversation_id)
    dangling_retry = (
        last is not None
        and last.role == "user"
        and (last.content or "").strip() == (answer_text or "").strip()
    )
    if dangling_retry:
        # A retried answer must not appear twice in the prompt: it's already
        # the last message in ``recent`` AND passed as ``user_answer``.
        if recent and recent[-1].get("role") == "user":
            recent = recent[:-1]
        # A re-recorded clip on retry: attach its block to the EXISTING
        # dangling message — otherwise the (already consumed) asset would be
        # referenced by nothing and leak past every cleanup path.
        if answer_audio_file_asset_id:
            blocks = []
            if last.content_blocks_json:
                try:
                    blocks = json.loads(last.content_blocks_json) or []
                except (json.JSONDecodeError, TypeError):
                    blocks = []
            if not any(
                isinstance(b, dict) and b.get("file_asset_id") == answer_audio_file_asset_id
                for b in blocks
            ):
                blocks.append({"type": "audio", "file_asset_id": answer_audio_file_asset_id})
                last.content_blocks_json = json.dumps(blocks, ensure_ascii=False)
                db.add(last)
    if not dangling_retry:
        # A voice clip (if any) rides along as an audio content block
        # referencing the file asset.
        user_blocks = None
        if answer_audio_file_asset_id:
            user_blocks = json.dumps(
                [
                    {"type": "text", "text": answer_text},
                    {"type": "audio", "file_asset_id": answer_audio_file_asset_id},
                ],
                ensure_ascii=False,
            )
        append_message(db, conversation_id, "user", answer_text, content_blocks_json=user_blocks)
    db.commit()

    # ── LLM turn (no transaction open) ──────────────────────────────
    turn = await mock_interview_service.generate_next_turn(
        prefix=prefix,
        stages=stages,
        current_stage_key=current_stage,
        recent_messages=recent,
        user_answer=answer_text,
        user_id=user_id,
        asked_questions=[q["text"] for q in asked],
        questions_in_current_stage=sum(
            1 for q in asked if q["stage_key"] == current_stage
        ),
    )

    # Rules layer (MOCK-5): the hard cap overrides the LLM's soft signal.
    if count_answered_turns(db, conversation_id) >= MOCK_MAX_ANSWERED_TURNS:
        turn.is_ready_to_finish = True

    # ── Phase B: persist the reply + advance runtime, commit ────────
    assistant_msg = append_message(
        db, conversation_id, "assistant", turn.interviewer_message,
        content_blocks_json=json.dumps(
            [{"type": "stage", "stage_key": turn.next_stage_key}], ensure_ascii=False,
        ),
    )

    stage_index = next(
        (i for i, s in enumerate(stages) if s["key"] == turn.next_stage_key), runtime.stage_index,
    )
    mock_runtime_service.advance_runtime(
        db,
        runtime,
        current_stage_key=turn.next_stage_key,
        stage_index=stage_index,
        current_question_text=turn.interviewer_message,
        current_question_message_id=assistant_msg.id,
        commit=False,
    )
    db.commit()
    turn.question_message_id = assistant_msg.id
    return turn


def list_asked_questions(db: Session, conversation_id: str) -> list[dict[str, str]]:
    """All interviewer lines so far, oldest first, with their stage meta.

    Feeds the anti-repetition inventory (MOCK-6) and the per-stage question
    count. Returns ``[{"text": ..., "stage_key": ...}]``; stage_key is ""
    for legacy messages without the meta block.
    """
    rows = (
        db.query(ConversationMessage.content, ConversationMessage.content_blocks_json)
        .filter(
            ConversationMessage.conversation_id == conversation_id,
            ConversationMessage.role == "assistant",
        )
        .order_by(ConversationMessage.seq)
        .all()
    )
    out: list[dict[str, str]] = []
    for content, blocks_json in rows:
        stage_key = ""
        if blocks_json:
            try:
                for b in json.loads(blocks_json) or []:
                    if isinstance(b, dict) and b.get("type") == "stage":
                        stage_key = str(b.get("stage_key") or "")
                        break
            except (json.JSONDecodeError, TypeError):
                pass
        out.append({"text": (content or "").strip(), "stage_key": stage_key})
    return out


def _last_message(db: Session, conversation_id: str):
    return (
        db.query(ConversationMessage)
        .filter(ConversationMessage.conversation_id == conversation_id)
        .order_by(ConversationMessage.seq.desc())
        .first()
    )


def count_answered_turns(db: Session, conversation_id: str) -> int:
    return (
        db.query(ConversationMessage)
        .filter(
            ConversationMessage.conversation_id == conversation_id,
            ConversationMessage.role == "user",
        )
        .count()
    )


def dispatch_review(
    db: Session,
    record_id: str,
    *,
    rollback_status: str = STATUS_MOCK_IN_PROGRESS,
) -> object:
    """Dispatch the review task and stamp the celery task id. Commits.

    If the broker is unreachable, roll the record back to
    ``rollback_status`` before re-raising — without the rollback the
    record parks in ``processing_review`` with no task, invisible in
    every list for the grace period and stuck after it.

    * finish path: roll back to ``mock_in_progress`` (+ reactivate the
      runtime) — the conversation is intact, the user just hits
      "结束面试" again.
    * retry path: roll back to ``review_failed`` — the interview is over;
      reviving the runtime would resurface a finished interview in the
      resume banner.
    """
    try:
        task = process_interview_analysis.delay(record_id)
    except Exception as exc:  # noqa: BLE001 — broker down / misconfigured
        logger.error("review dispatch failed for record %s: %s", record_id, exc)
        interview_record_service.set_status(record_id, rollback_status, db=db)
        if rollback_status == STATUS_MOCK_IN_PROGRESS:
            runtime = mock_runtime_service.get_runtime_for_record(
                db, interview_record_id=record_id,
            )
            if runtime is not None:
                mock_runtime_service.set_status(
                    db, runtime, mock_runtime_service.ACTIVE_STATUS, commit=False,
                )
        db.commit()
        raise
    interview_record_service.set_status(
        record_id, STATUS_PROCESSING_REVIEW, celery_task_id=task.id, db=db,
    )
    db.commit()
    return task


def delete_mock_audio_assets(db: Session, conversation_id: str, user_pk: int) -> None:
    """Best-effort: delete file assets referenced by this conversation's
    messages (the mock voice clips) — rows hard-deleted, blobs via the
    outbox (UP-2; rows used to be dropped while the objects lived on in
    MinIO forever). Non-fatal."""
    try:
        from app.models.file_asset import FileAsset
        from app.services.uploads.file_asset_service import enqueue_asset_blob_delete

        rows = (
            db.query(ConversationMessage.content_blocks_json)
            .filter(
                ConversationMessage.conversation_id == conversation_id,
                ConversationMessage.content_blocks_json.isnot(None),
            )
            .all()
        )
        asset_ids: set[str] = set()
        for (blocks_json,) in rows:
            try:
                blocks = json.loads(blocks_json) or []
            except (json.JSONDecodeError, TypeError):
                continue
            for b in blocks if isinstance(blocks, list) else []:
                if isinstance(b, dict) and b.get("file_asset_id"):
                    asset_ids.add(str(b["file_asset_id"]))
        if asset_ids:
            assets = (
                db.query(FileAsset)
                .filter(
                    FileAsset.id.in_(asset_ids),
                    FileAsset.user_id == user_pk,
                )
                .all()
            )
            for asset in assets:
                enqueue_asset_blob_delete(db, asset)
                db.delete(asset)
    except Exception as exc:  # noqa: BLE001
        logger.warning("mock audio asset cleanup skipped for %s: %s", conversation_id, exc)


def abandon_mock(db: Session, record: InterviewRecord, runtime) -> None:
    """Delete the run's conversation + messages, runtime, mock audio assets
    and the draft record (abandon = this never happened). Flushes deletes;
    the caller commits / rolls back."""
    conversation_id = runtime.conversation_id if runtime else None
    if conversation_id is None:
        conv = (
            db.query(Conversation)
            .filter(
                Conversation.subject_id == record.id,
                Conversation.type == "mock_interview",
            )
            .first()
        )
        conversation_id = conv.id if conv else None

    if conversation_id:
        delete_mock_audio_assets(db, conversation_id, record.user_id)
        db.query(ConversationMessage).filter(
            ConversationMessage.conversation_id == conversation_id
        ).delete(synchronize_session=False)
        db.query(Conversation).filter(
            Conversation.id == conversation_id
        ).delete(synchronize_session=False)
    if runtime is not None:
        db.delete(runtime)
    # interview_qa + any runtime left auto-cascade on the record delete.
    db.delete(record)
