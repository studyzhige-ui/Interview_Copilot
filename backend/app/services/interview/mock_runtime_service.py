"""Persistence helpers for the ephemeral live mock-interview cursor."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.core.user_identity import resolve_user_pk
from app.db.types import utc_now
from app.models.mock_interview_runtime import MockInterviewRuntime

ANSWER_CLAIM_TTL_SECONDS = 600


def create_runtime(
    db: Session,
    *,
    user_id: str,
    interview_record_id: str,
    conversation_id: str,
    plan: list[dict[str, Any]],
    interviewer_style: str,
    target_question_count: int,
    current_stage_key: str,
    current_question_message_id: int,
    commit: bool = True,
) -> MockInterviewRuntime:
    """Create the runtime for a newly-started mock interview.

    ``user_id`` is the caller's username; it's resolved to the stable
    ``users.id`` for the FK.
    """
    user_pk = resolve_user_pk(db, user_id)
    if user_pk is None:
        raise ValueError(f"Unknown user: {user_id}")
    runtime = MockInterviewRuntime(
        user_id=user_pk,
        interview_record_id=interview_record_id,
        conversation_id=conversation_id,
        plan_json=plan,
        interviewer_style=interviewer_style,
        target_question_count=target_question_count,
        current_stage_key=current_stage_key,
        current_question_message_id=current_question_message_id,
    )
    db.add(runtime)
    if commit:
        db.commit()
        db.refresh(runtime)
    return runtime


def get_active_runtime(db: Session, *, user_id: str) -> MockInterviewRuntime | None:
    """The user's active mock, for resume-after-refresh.

    ``user_id`` is the username; resolved to the stable ``users.id`` for the
    query (returns None for an unknown user)."""
    user_pk = resolve_user_pk(db, user_id)
    if user_pk is None:
        return None
    return (
        db.query(MockInterviewRuntime)
        .filter(MockInterviewRuntime.user_id == user_pk)
        .first()
    )


def get_runtime_for_record(
    db: Session,
    *,
    interview_record_id: str,
) -> MockInterviewRuntime | None:
    return (
        db.query(MockInterviewRuntime)
        .filter(MockInterviewRuntime.interview_record_id == interview_record_id)
        .first()
    )


def claim_question(
    db: Session,
    runtime: MockInterviewRuntime,
    *,
    question_message_id: int,
) -> str:
    """Atomically claim one question before the slow interviewer LLM call.

    Returns ``claimed``, ``stale`` or ``busy``. The caller commits the claim in
    the same short transaction as the candidate answer. A lease older than ten
    minutes is reclaimable after an API hard kill.
    """
    now = utc_now()
    stale_before = now - timedelta(seconds=ANSWER_CLAIM_TTL_SECONDS)
    updated = (
        db.query(MockInterviewRuntime)
        .filter(
            MockInterviewRuntime.interview_record_id == runtime.interview_record_id,
            MockInterviewRuntime.current_question_message_id == question_message_id,
            (
                MockInterviewRuntime.answer_claimed_at.is_(None)
                | (MockInterviewRuntime.answer_claimed_at < stale_before)
            ),
        )
        .update(
            {
                MockInterviewRuntime.answer_claimed_at: now,
                MockInterviewRuntime.last_activity_at: now,
            },
            synchronize_session=False,
        )
    )
    if updated:
        runtime.answer_claimed_at = now
        runtime.last_activity_at = now
        return "claimed"

    db.expire_all()
    current = db.get(MockInterviewRuntime, runtime.interview_record_id)
    if current is None or current.current_question_message_id != question_message_id:
        return "stale"
    return "busy"


def release_question_claim(
    db: Session,
    interview_record_id: str,
    *,
    question_message_id: int,
) -> None:
    """Release a failed turn without disturbing a newer question."""
    db.rollback()
    (
        db.query(MockInterviewRuntime)
        .filter(
            MockInterviewRuntime.interview_record_id == interview_record_id,
            MockInterviewRuntime.current_question_message_id == question_message_id,
        )
        .update(
            {MockInterviewRuntime.answer_claimed_at: None},
            synchronize_session=False,
        )
    )
    db.commit()


def advance_runtime(
    db: Session,
    runtime: MockInterviewRuntime,
    *,
    current_stage_key: str,
    current_question_message_id: int,
    commit: bool = True,
) -> MockInterviewRuntime:
    """Update the live stage/question cursor and activity timestamp."""
    runtime.current_stage_key = current_stage_key
    runtime.current_question_message_id = current_question_message_id
    runtime.last_activity_at = utc_now()
    db.add(runtime)
    if commit:
        db.commit()
        db.refresh(runtime)
    return runtime


def delete_runtime(
    db: Session, runtime: MockInterviewRuntime, *, commit: bool = True
) -> None:
    """Delete the live cursor after dispatch or as part of abandon."""
    db.delete(runtime)
    if commit:
        db.commit()
