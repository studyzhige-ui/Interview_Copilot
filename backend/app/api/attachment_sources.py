"""Typed attachment state, retry, and InterviewRecord source promotion APIs.

This router is intentionally thin.  It is mounted by the application root;
all ownership and lifecycle rules live in the shared Application Service.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.core.user_identity import resolve_user_pk
from app.db.database import get_db
from app.models.knowledge import KnowledgeDocument
from app.models.user import User
from app.schemas.attachment_source import (
    AttachmentRetryView,
    AttachmentSourceView,
    ConversationAttachmentRemovalView,
    DebriefSourcePromotionView,
)
from app.services.chat.attachment_source_service import (
    AttachmentSourceCommandError,
    AttachmentSourceNotFoundError,
    get_attachment_source_state,
    list_claimed_attachment_sources,
    list_debrief_project_sources,
    list_pending_submission_sources,
    mark_attachment_retry_dispatch_failed,
    prepare_attachment_projection_retry,
    promote_attachment_to_debrief,
    remove_failed_conversation_attachment,
    remove_debrief_project_source,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["attachment-sources"])


def _view(state) -> AttachmentSourceView:
    return AttachmentSourceView.model_validate(state)


def _translate_error(exc: AttachmentSourceCommandError) -> HTTPException:
    status = 404 if isinstance(exc, AttachmentSourceNotFoundError) else 409
    return HTTPException(status_code=status, detail=str(exc))


@router.get(
    "/chat/{session_id}/attachment-sources",
    response_model=list[AttachmentSourceView],
)
def list_conversation_attachment_sources(
    session_id: str,
    submission_id: str | None = Query(default=None, max_length=128),
    turn_id: str | None = Query(default=None, max_length=128),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Read queued or claimed source state without silently dropping failures."""

    user_pk = resolve_user_pk(db, current_user.username)
    try:
        if submission_id is not None:
            states = list_pending_submission_sources(
                db,
                user_pk=user_pk,
                conversation_id=session_id,
                submission_id=submission_id,
            )
        else:
            states = list_claimed_attachment_sources(
                db,
                user_pk=user_pk,
                conversation_id=session_id,
                turn_id=turn_id,
            )
    except AttachmentSourceCommandError as exc:
        raise _translate_error(exc) from exc
    return [_view(state) for state in states]


@router.post(
    "/chat/{session_id}/attachment-sources/{source_id}/retry",
    response_model=AttachmentRetryView,
)
def retry_attachment_source(
    session_id: str,
    source_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retry the same parsing projection; never mint a new attachment identity."""

    user_pk = resolve_user_pk(db, current_user.username)
    try:
        retry = prepare_attachment_projection_retry(
            db,
            user_pk=user_pk,
            conversation_id=session_id,
            source_id=source_id,
        )
        db.commit()
    except AttachmentSourceCommandError as exc:
        db.rollback()
        raise _translate_error(exc) from exc

    if retry.should_dispatch:
        from app.task_queue.dispatch import dispatch_document_ingestion

        try:
            task = dispatch_document_ingestion(retry.state.document_id or "")
            document = db.get(KnowledgeDocument, retry.state.document_id)
            if document is not None and document.status == "processing":
                document.task_id = task.id
                db.commit()
        except Exception:  # noqa: BLE001
            db.rollback()
            logger.exception(
                "attachment retry dispatch failed for %s", retry.state.document_id
            )
            mark_attachment_retry_dispatch_failed(
                db,
                document_id=retry.state.document_id or "",
                message="后台处理队列暂时不可用，请稍后重试。",
            )
            db.commit()
            state = get_attachment_source_state(
                db,
                user_pk=user_pk,
                conversation_id=session_id,
                source_id=source_id,
            )
            return AttachmentRetryView(source=_view(state), dispatched=False)
    return AttachmentRetryView(
        source=_view(retry.state), dispatched=retry.should_dispatch
    )


@router.delete(
    "/chat/{session_id}/attachment-sources/{attachment_ref_id}",
    response_model=ConversationAttachmentRemovalView,
)
def remove_failed_conversation_source(
    session_id: str,
    attachment_ref_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Explicitly drop a failed claimed source and resume the same Turn."""

    user_pk = resolve_user_pk(db, current_user.username)
    try:
        ref, turn_id = remove_failed_conversation_attachment(
            db,
            user_pk=user_pk,
            conversation_id=session_id,
            attachment_ref_id=attachment_ref_id,
        )
        db.commit()
    except AttachmentSourceCommandError as exc:
        db.rollback()
        raise _translate_error(exc) from exc

    from app.services.chat.attachment_waiting_service import (
        wake_attachment_turn_if_terminal,
    )

    return ConversationAttachmentRemovalView(
        source_id=ref.id,
        resumed_turn=wake_attachment_turn_if_terminal(turn_id),
    )


@router.post(
    "/chat/{session_id}/attachment-sources/{attachment_ref_id}/debrief",
    response_model=DebriefSourcePromotionView,
)
def promote_conversation_attachment_to_debrief(
    session_id: str,
    attachment_ref_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_pk = resolve_user_pk(db, current_user.username)
    try:
        promoted = promote_attachment_to_debrief(
            db,
            user_pk=user_pk,
            conversation_id=session_id,
            attachment_ref_id=attachment_ref_id,
        )
        db.commit()
        states = list_debrief_project_sources(
            db,
            user_pk=user_pk,
            interview_record_id=promoted.interview_record_id,
        )
        state = next(item for item in states if item.source_id == promoted.id)
    except AttachmentSourceCommandError as exc:
        db.rollback()
        raise _translate_error(exc) from exc
    # Promotion is idempotent; clients care about the resulting scope grant,
    # not whether this transport attempt inserted the row.
    return DebriefSourcePromotionView(source=_view(state))


@router.get(
    "/interviews/{record_id}/debrief-sources",
    response_model=list[AttachmentSourceView],
)
def get_debrief_project_sources(
    record_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_pk = resolve_user_pk(db, current_user.username)
    try:
        states = list_debrief_project_sources(
            db,
            user_pk=user_pk,
            interview_record_id=record_id,
        )
    except AttachmentSourceCommandError as exc:
        raise _translate_error(exc) from exc
    return [_view(state) for state in states]


@router.delete(
    "/interviews/{record_id}/debrief-sources/{source_ref_id}",
    response_model=dict[str, str],
)
def remove_debrief_source(
    record_id: str,
    source_ref_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_pk = resolve_user_pk(db, current_user.username)
    try:
        ref = remove_debrief_project_source(
            db,
            user_pk=user_pk,
            interview_record_id=record_id,
            source_ref_id=source_ref_id,
        )
        db.commit()
    except AttachmentSourceCommandError as exc:
        db.rollback()
        raise _translate_error(exc) from exc
    return {"source_ref_id": ref.id, "status": "removed"}


__all__ = ["router"]
