"""Mock-interview run orchestration.

The start flow OWNS creation of the whole run — it atomically creates the
``interview_records`` (status=mock_in_progress), the ``conversations``
(type=mock_interview, bound via subject_type/subject_id) and the
ephemeral ``mock_interview_runtime`` cursor in one transaction.
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
from dataclasses import dataclass

from app.schemas.chat import MockAnswerRequest, MockAnswerResp, MockLiveMessage
from app.interviews.application import mock_answer_receipts

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.user_identity import resolve_user_pk
from app.interviews.domain.specification import InterviewSpecification, InterviewPurpose
from app.models.chat import Conversation, ConversationMessage, generate_uuid
from app.models.interview_record import InterviewRecord
from app.interviews.application import mock_interview_service
from app.interviews.application import mock_runtime_service
from app.interviews.application.interview_record_service import STATUS_MOCK_IN_PROGRESS
from app.interviews.application.interview_record_service import STATUS_PROCESSING_REVIEW
from app.interviews.application.interview_record_service import interview_record_service
from app.task_queue.dispatch import dispatch_mock_interview_review

logger = logging.getLogger(__name__)


class StaleQuestionError(ValueError):
    """The answer references a question that is no longer current — a
    concurrent submit already advanced the interview (MOCK-3)."""


class PendingAnswerConflictError(ValueError):
    """An unanswered persisted answer cannot be silently replaced on retry."""


class QuestionBusyError(ValueError):
    """Another request is already generating the reply for this question."""


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


def conversation_messages(db: Session, conversation_id: str) -> list[dict[str, str]]:
    rows = (
        db.query(ConversationMessage)
        .filter(ConversationMessage.conversation_id == conversation_id)
        .order_by(ConversationMessage.seq.asc())
        .all()
    )
    return [{"role": r.role, "content": r.content or ""} for r in rows]


def live_messages(db: Session, conversation_id: str) -> list[dict[str, object]]:
    """Return the user-facing mock transcript from the canonical message log."""
    rows = (
        db.query(ConversationMessage)
        .filter(
            ConversationMessage.conversation_id == conversation_id,
            ConversationMessage.role.in_(["assistant", "user"]),
        )
        .order_by(ConversationMessage.seq.asc())
        .all()
    )
    return [
        {
            "id": row.id,
            "speaker": "interviewer" if row.role == "assistant" else "candidate",
            "text": row.content or "",
        }
        for row in rows
    ]


class ResumeNotFoundError(ValueError):
    pass


class ResumeNotReadyError(RuntimeError):
    pass


@dataclass(frozen=True)
class ResolvedResumeContext:
    text: str
    artifact_id: str | None
    artifact_version_id: str | None


def resolve_resume_context(
    db: Session,
    *,
    username: str,
    resume_id: str,
) -> str:
    """Load one parsed personal resume for interview planning."""
    return _resolve_resume_reference(db, username=username, resume_id=resume_id).text


def _resolve_resume_reference(
    db: Session,
    *,
    username: str,
    resume_id: str,
) -> ResolvedResumeContext:
    """Resolve only the canonical resume Artifact and exact current version.

    ``resume_id`` may be a pre-cut-over identity only when migration 0029 has
    recorded it as ``ArtifactResumeState.legacy_resume_id``. The runtime never
    reads the retired Resume or ResumeSection tables.
    """
    try:
        from app.career.application.resumes import resume_artifact_service

        user_pk = resolve_user_pk(db, username)
        try:
            canonical = resume_artifact_service.resolve_owned_resume(
                db, user_pk=user_pk, resume_id=resume_id
            )
        except resume_artifact_service.ResumeArtifactNotFoundError as exc:
            raise ResumeNotFoundError(
                "简历 Artifact 不存在或无权访问；旧简历标识必须先由迁移 0029 映射"
            ) from exc
        try:
            snapshot = resume_artifact_service.read_resume_text(canonical)
        except resume_artifact_service.ResumeArtifactNotReadyError as exc:
            raise ResumeNotReadyError(str(exc)) from exc
        return ResolvedResumeContext(
            text=snapshot,
            artifact_id=canonical.artifact.id,
            artifact_version_id=canonical.current_version.id,
        )
    except Exception as exc:  # noqa: BLE001
        if isinstance(exc, (ResumeNotFoundError, ResumeNotReadyError)):
            raise
        logger.warning("mock resume context load failed: %s", exc)
        raise ResumeNotReadyError("简历读取失败，请稍后重试") from exc


# ── Ownership ────────────────────────────────────────────────────────────


def get_owned_mock_record(
    db: Session, record_id: str, username: str, *, for_update: bool = False
) -> InterviewRecord | None:
    query = db.query(InterviewRecord).filter(
        InterviewRecord.id == record_id,
        InterviewRecord.user_id == resolve_user_pk(db, username),
        InterviewRecord.source == "mock",
    )
    if for_update:
        query = query.with_for_update().populate_existing()
    return query.first()


# ── Run lifecycle ────────────────────────────────────────────────────────


@dataclass
class StartedMock:
    record: InterviewRecord
    conversation: Conversation
    runtime: object
    plan: object


@dataclass(frozen=True)
class SubmittedTurn:
    question_message_id: int
    interviewer_message: str
    is_ready_to_finish: bool


def start_mock(
    db: Session,
    *,
    username: str,
    resume_id: str | None,
    jd_text: str | None,
    interviewer_style: str,
    target_question_count: int,
    job_opportunity_id: str | None = None,
    jd_snapshot_id: str | None = None,
    jd_snapshot_version: int | None = None,
    purpose: InterviewPurpose = "full",
    focus: str | None = None,
) -> StartedMock:
    """Atomically create record + conversation + opening message + runtime.

    Flushes everything into ONE uncommitted transaction — the caller commits
    (so it can offload the commit to a thread) and rolls back on failure.
    """
    user_pk = resolve_user_pk(db, username)
    normalized_job_id = interview_record_service.require_owned_job_opportunity(
        db,
        user_pk=user_pk,
        job_opportunity_id=job_opportunity_id,
    )
    from app.schemas.mock_preparation import MockPreparationRequest

    command = MockPreparationRequest(
        resume_id=resume_id,
        jd_text=jd_text,
        jd_snapshot_id=jd_snapshot_id,
        jd_snapshot_version=jd_snapshot_version,
        job_opportunity_id=normalized_job_id,
        purpose=purpose,
        focus=focus,
        interviewer_style=interviewer_style,
        target_question_count=target_question_count,
    )
    spec = InterviewSpecification(purpose=command.purpose, focus=command.focus)
    resolved_resume = (
        _resolve_resume_reference(db, username=username, resume_id=resume_id)
        if resume_id
        else ResolvedResumeContext("", None, None)
    )
    resume_context = resolved_resume.text
    from app.interviews.application.mock_sources import resolve_job_description

    jd_context = (
        resolve_job_description(
            db,
            user_pk=user_pk,
            jd_text=jd_text,
            job_opportunity_id=normalized_job_id,
            jd_snapshot_id=jd_snapshot_id,
            jd_snapshot_version=jd_snapshot_version,
        )
        if jd_text is not None or jd_snapshot_id is not None
        else ""
    )

    plan = mock_interview_service.generate_plan(
        specification=spec,
        resume_context=resume_context,
        jd_context=jd_context,
        interviewer_style=interviewer_style,
        user_id=username,
    )

    # 1) record (mock_in_progress) — freezes the resume/JD snapshots + plan.
    record = interview_record_service.create_for_mock(
        user_id=username,
        title=spec.title,
        resume_artifact_id=resolved_resume.artifact_id,
        resume_artifact_version_id=resolved_resume.artifact_version_id,
        resume_text_snapshot=resume_context,
        jd_text_snapshot=jd_context,
        job_opportunity_id=normalized_job_id,
        status=STATUS_MOCK_IN_PROGRESS,
        db=db,
    )

    record.specification_json = spec.model_dump()

    # 2) conversation (bound to the record via subject_type/subject_id).
    conversation = Conversation(
        id=generate_uuid(),
        user_id=user_pk,
        title=spec.title,
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
        db,
        conversation.id,
        "assistant",
        plan.opening_message,
        content_blocks_json=json.dumps(
            [{"type": "stage", "stage_key": plan.first_stage_key}],
            ensure_ascii=False,
        ),
    )

    # 4) runtime (in_progress), pointed at the opening question.
    runtime = mock_runtime_service.create_runtime(
        db,
        user_id=username,
        interview_record_id=record.id,
        conversation_id=conversation.id,
        plan=plan.stages,
        interviewer_style=interviewer_style,
        target_question_count=target_question_count,
        current_stage_key=plan.first_stage_key,
        current_question_message_id=opening.id,
        commit=False,
    )

    return StartedMock(
        record=record, conversation=conversation, runtime=runtime, plan=plan
    )


async def submit_answer(
    db: Session,
    *,
    record: InterviewRecord,
    runtime,
    answer_text: str,
    answer_audio_file_asset_id: str | None,
    user_id: str | None = None,
    question_message_id: int,
    request_id: str,
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
    (409 at the API).

    Returns only the persisted interviewer fields needed by the live API.
    """
    command = MockAnswerRequest(
        request_id=request_id,
        answer_text=answer_text,
        answer_audio_file_asset_id=answer_audio_file_asset_id,
        question_message_id=question_message_id,
    )
    record_id, owner = record.id, record.user_id
    active_record = (
        db.query(InterviewRecord)
        .filter_by(id=record_id, user_id=owner, source="mock")
        .with_for_update()
        .populate_existing()
        .one_or_none()
    )
    if active_record is None:
        raise StaleQuestionError("the mock interview is no longer available")
    replay = mock_answer_receipts.replay(db, record_id, command)
    if replay is not None:
        # Release this read lock too; no model, file or cursor mutation on replay.
        db.rollback()
        return SubmittedTurn(
            question_message_id=replay.message.id,
            interviewer_message=replay.message.text,
            is_ready_to_finish=replay.end_suggested,
        )
    if active_record.status != STATUS_MOCK_IN_PROGRESS or runtime is None:
        raise StaleQuestionError("the mock interview is no longer active")
    # Refresh the cursor under the record lock, not a caller's stale identity map.
    db.refresh(runtime)
    if runtime.interview_record_id != record_id or runtime.user_id != owner:
        raise StaleQuestionError("the mock runtime does not belong to this record")
    conversation_id = runtime.conversation_id
    target_question_count = runtime.target_question_count
    if question_message_id != runtime.current_question_message_id:
        raise StaleQuestionError(
            f"answer targets message {question_message_id}, current is "
            f"{runtime.current_question_message_id}"
        )

    stages = runtime.plan_json
    current_stage = runtime.current_stage_key
    prefix = mock_interview_service.build_prefix(
        record.resume_text_snapshot or "",
        record.jd_text_snapshot or "",
        runtime.interviewer_style,
        specification=active_record.specification_json,
    )
    # Full dialog BEFORE this answer. The new answer is passed separately so it
    # is not duplicated in the prompt. The advisory target guides pacing, so a
    # second summarization/analysis pipeline is unnecessary here.
    history = conversation_messages(db, conversation_id)

    claim = mock_runtime_service.claim_question(
        db,
        runtime,
        question_message_id=question_message_id,
    )
    if claim == "stale":
        raise StaleQuestionError("the current question changed before it was claimed")
    if claim == "busy":
        raise QuestionBusyError("the current question is already being answered")

    claim_generation = runtime.answer_claim_generation
    mock_answer_receipts.start(db, record_id, command, claim_generation)

    # ── Phase A: persist the answer, commit ─────────────────────────
    last = _last_message(db, conversation_id)
    if (
        last is not None
        and last.role == "user"
        and (last.content or "").strip() != (answer_text or "").strip()
    ):
        raise PendingAnswerConflictError(
            "a different answer is already saved for this question"
        )
    dangling_retry = (
        last is not None
        and last.role == "user"
        and (last.content or "").strip() == (answer_text or "").strip()
    )
    if dangling_retry:
        # A retried answer must not appear twice in the prompt: it is already
        # the last history message AND passed separately as ``user_answer``.
        if history and history[-1].get("role") == "user":
            history = history[:-1]
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
                isinstance(b, dict)
                and b.get("file_asset_id") == answer_audio_file_asset_id
                for b in blocks
            ):
                blocks.append(
                    {"type": "audio", "file_asset_id": answer_audio_file_asset_id}
                )
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
        append_message(
            db, conversation_id, "user", answer_text, content_blocks_json=user_blocks
        )
    answered_turns = count_answered_turns(db, conversation_id)
    db.commit()

    # ── LLM turn (no transaction open) ──────────────────────────────
    try:
        turn = await mock_interview_service.generate_next_turn(
            prefix=prefix,
            stages=stages,
            current_stage_key=current_stage,
            conversation_messages=history,
            user_answer=answer_text,
            user_id=user_id,
            length_warning_active=answered_turns >= target_question_count,
        )
    except BaseException:
        mock_runtime_service.release_question_claim(
            db,
            record_id,
            question_message_id=question_message_id,
            claim_generation=claim_generation,
            request_id=request_id,
        )
        raise

    # ── Phase B: persist the reply + advance runtime, commit ────────
    try:
        current = mock_runtime_service.lock_question_lease(
            db,
            interview_record_id=record_id,
            question_message_id=question_message_id,
            claim_generation=claim_generation,
        )
        if current is None:
            raise StaleQuestionError(
                "the answer lease changed while generating the next question"
            )
        assistant_msg = append_message(
            db,
            conversation_id,
            "assistant",
            turn.interviewer_message,
            content_blocks_json=json.dumps(
                [{"type": "stage", "stage_key": turn.next_stage_key}],
                ensure_ascii=False,
            ),
        )

        mock_runtime_service.advance_runtime(
            db,
            current,
            current_stage_key=turn.next_stage_key,
            current_question_message_id=assistant_msg.id,
            commit=False,
        )
        current.answer_claimed_at = None
        result = MockAnswerResp(
            message=MockLiveMessage(
                id=assistant_msg.id,
                speaker="interviewer",
                text=turn.interviewer_message,
            ),
            end_suggested=turn.is_ready_to_finish,
        )
        mock_answer_receipts.complete(
            db, record_id, request_id, claim_generation, result
        )
        db.commit()
    except BaseException:
        mock_runtime_service.release_question_claim(
            db,
            record_id,
            question_message_id=question_message_id,
            claim_generation=claim_generation,
            request_id=request_id,
        )
        raise
    return SubmittedTurn(
        question_message_id=result.message.id,
        interviewer_message=result.message.text,
        is_ready_to_finish=result.end_suggested,
    )


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
    delete_live_runtime: bool = False,
) -> object:
    """Dispatch review, persist the task id and optionally remove live state.

    If the broker is unreachable, roll the record back to
    ``rollback_status`` before re-raising — without the rollback the
    record parks in ``processing_review`` with no task, invisible in
    every list for the grace period and stuck after it.

    The finish path keeps the runtime until the broker accepts the task. A
    dispatch failure restores ``mock_in_progress`` and the unchanged runtime
    remains resumable. Review retries happen after that runtime is gone.
    """
    from app.interviews.application.review_dispatch import dispatch_review_command

    task = dispatch_review_command(
        db,
        record_id,
        sender=dispatch_mock_interview_review,
        rollback_status=rollback_status,
        error_message="复盘派发未确认，请核对状态后重试。旧任务已失效。",
    )
    if delete_live_runtime:
        runtime = mock_runtime_service.get_runtime_for_record(
            db, interview_record_id=record_id
        )
        if runtime is not None:
            db.delete(runtime)
    db.commit()
    return task


def delete_mock_audio_assets(db: Session, conversation_id: str, user_pk: int) -> None:
    """Best-effort: delete file assets referenced by this conversation's
    messages (the mock voice clips) — rows hard-deleted, blobs via the
    outbox (UP-2; rows used to be dropped while the objects lived on in
    MinIO forever). Non-fatal."""
    try:
        from app.models.file_asset import FileAsset
        from app.files.application.file_asset_service import enqueue_asset_blob_delete

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
        logger.warning(
            "mock audio asset cleanup skipped for %s: %s", conversation_id, exc
        )


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
        db.query(Conversation).filter(Conversation.id == conversation_id).delete(
            synchronize_session=False
        )
    if runtime is not None:
        db.delete(runtime)
    # interview_qa + any runtime left auto-cascade on the record delete.
    db.delete(record)


def finish_for_review(
    db: Session, *, record_id: str, username: str, retry: bool = False
):
    """One lifecycle command for every adapter; caller maps transport errors."""
    from app.core.command_errors import CommandError
    from app.interviews.application.interview_record_service import STATUS_REVIEW_FAILED

    record = get_owned_mock_record(db, record_id, username, for_update=True)
    if record is None:
        raise CommandError("not_found", "Mock interview not found")
    if retry:
        if record.status not in (STATUS_REVIEW_FAILED, STATUS_PROCESSING_REVIEW):
            raise CommandError("invalid", "当前状态不可重试复盘")
    else:
        if record.status != STATUS_MOCK_IN_PROGRESS:
            raise CommandError(
                "conflict", "该面试不在进行中（复盘可能已在生成或已完成）"
            )
        runtime = mock_runtime_service.get_runtime_for_record(
            db, interview_record_id=record_id
        )
        if runtime is None:
            raise CommandError("conflict", "该模拟面试不在进行中")
        if count_answered_turns(db, runtime.conversation_id) == 0:
            raise CommandError("invalid", "至少回答一题才能生成复盘")
    record.status = STATUS_PROCESSING_REVIEW
    db.commit()
    try:
        if retry:
            dispatch_review(db, record_id, rollback_status=STATUS_REVIEW_FAILED)
        else:
            dispatch_review(db, record_id, delete_live_runtime=True)
    except Exception as exc:
        raise CommandError(
            "unavailable",
            "复盘任务派发失败（任务队列暂不可用），面试内容已保留，请稍后重试。",
        ) from exc
    return {"status": "processing_review", "record_id": record_id}
