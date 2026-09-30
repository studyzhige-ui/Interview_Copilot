"""Conversation commands. Session creation and future-mode CAS have one owner.

UI routes and internal product orchestration use these commands. They never
change snapshots already admitted into a PendingSubmission or ConversationTurn.
"""

import logging
from uuid import NAMESPACE_URL, uuid5
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from app.core.command_errors import CommandError
from app.core.user_identity import resolve_user_pk
from app.models.user import User
from app.models.chat import Conversation, generate_uuid
from app.conversation.runtime_profile import runtime_profile_for_type
from app.schemas.chat import (
    SessionCreateRequest,
    SessionCreateResponse,
    SessionExecutionModeResponse,
    SessionExecutionModeUpdateRequest,
    SessionRenameRequest,
)

logger = logging.getLogger(__name__)


def create_chat_session(request: SessionCreateRequest, current_user: User, db: Session):
    req = request
    # mock_interview conversations are created by the mock-interview start
    # endpoint (it owns the atomic record + conversation + runtime creation),
    # never here. This endpoint only opens general / debrief chats.
    conv_type = req.type

    subject_type: str | None = None
    subject_id: str | None = None
    if conv_type == "debrief":
        if not req.subject_id:
            raise CommandError(kind="invalid", message="debrief 对话必须绑定面试记录")
        from app.models.interview_record import InterviewRecord

        record = (
            db.query(InterviewRecord)
            .filter(
                InterviewRecord.id == req.subject_id,
                InterviewRecord.user_id == resolve_user_pk(db, current_user.username),
            )
            .first()
        )
        if record is None:
            raise CommandError(kind="not_found", message="Interview record not found")
        subject_type = "interview_record"
        subject_id = req.subject_id

    default_titles = {"general": "通用对话", "debrief": "面试复盘"}
    title = req.title or default_titles.get(conv_type, "新的面试对话")
    user_pk = resolve_user_pk(db, current_user.username)
    session_id = (
        str(
            uuid5(
                NAMESPACE_URL,
                f"interview-copilot:session:{user_pk}:{req.client_request_id}",
            )
        )
        if req.client_request_id
        else generate_uuid()
    )

    def response_for(row: Conversation) -> SessionCreateResponse:
        if (
            row.user_id != user_pk
            or row.type != conv_type
            or row.subject_id != subject_id
        ):
            raise CommandError(
                kind="conflict", message="创建请求与已有对话不一致，请重新开始"
            )
        return SessionCreateResponse(
            session_id=row.id,
            title=row.title,
            type=row.type,
            execution_mode=row.execution_mode,
            execution_mode_version=row.execution_mode_version,
        )

    existing = db.get(Conversation, session_id) if req.client_request_id else None
    if existing is not None:
        return response_for(existing)

    try:
        new_session = Conversation(
            id=session_id,
            user_id=user_pk,
            title=title,
            type=conv_type,
            mode=runtime_profile_for_type(conv_type).default_mode,
            execution_mode=(
                getattr(current_user, "default_execution_mode", None) or "standard"
            ),
            subject_type=subject_type,
            subject_id=subject_id,
        )
        db.add(new_session)
        db.commit()
        db.refresh(new_session)
        return SessionCreateResponse(
            session_id=new_session.id,
            title=new_session.title,
            type=new_session.type,
            execution_mode=new_session.execution_mode,
            execution_mode_version=new_session.execution_mode_version,
        )
    except IntegrityError:
        db.rollback()
        existing = db.get(Conversation, session_id) if req.client_request_id else None
        if existing is not None:
            return response_for(existing)
        raise
    except CommandError:
        raise
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.exception(
            "create_chat_session failed (user=%s, type=%s, subject_id=%s): %s",
            current_user.username,
            conv_type,
            req.subject_id,
            exc,
        )
        raise CommandError(
            kind="failed",
            message="创建对话失败",
        ) from exc


def _owned_conversation(db: Session, *, session_id: str, user_pk: int):
    row = (
        db.query(Conversation)
        .filter(Conversation.id == session_id, Conversation.user_id == user_pk)
        .one_or_none()
    )
    if row is None:
        raise CommandError(
            kind="not_found", message="Session not found or access denied"
        )
    return row


def update_session_execution_mode(
    session_id: str,
    payload: SessionExecutionModeUpdateRequest,
    current_user: User,
    db: Session,
):
    """CAS-update only the Conversation's setting for future admissions.

    PendingSubmission and ConversationTurn rows already own admitted snapshots;
    this endpoint intentionally never touches them.
    """
    user_pk = resolve_user_pk(db, current_user.username)
    changed = (
        db.query(Conversation)
        .filter(
            Conversation.id == session_id,
            Conversation.user_id == user_pk,
            Conversation.execution_mode_version == payload.expected_version,
        )
        .update(
            {
                Conversation.execution_mode: payload.execution_mode,
                Conversation.execution_mode_version: payload.expected_version + 1,
            },
            synchronize_session=False,
        )
    )
    if changed != 1:
        db.rollback()
        # Preserve owner isolation: a missing/foreign id is always a 404. A
        # same-owner row with a newer token is a conflict; clients reread the
        # authoritative projection instead of trusting their stale copy.
        _owned_conversation(db, session_id=session_id, user_pk=user_pk)
        raise CommandError(kind="conflict", message="execution mode version conflict")
    db.commit()
    row = _owned_conversation(db, session_id=session_id, user_pk=user_pk)
    return SessionExecutionModeResponse(
        session_id=row.id,
        execution_mode=row.execution_mode,
        version=int(row.execution_mode_version),
    )


def update_session_title(
    session_id: str, payload: SessionRenameRequest, current_user: User, db: Session
):
    new_title = payload.title.strip()
    if not new_title:
        raise CommandError(kind="invalid", message="title 不能为空")
    row = db.query(Conversation).filter(Conversation.id == session_id).first()
    if not row or row.user_id != resolve_user_pk(db, current_user.username):
        raise CommandError(
            kind="not_found", message="Session not found or access denied"
        )
    row.title = new_title
    db.commit()
    return {"status": "success", "session_id": session_id, "new_title": new_title}
