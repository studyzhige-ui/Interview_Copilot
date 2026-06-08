"""Lifecycle helpers for ``mock_interview_runtime`` — the live mock state.

The mock-start flow creates one runtime row per interview (atomically with the
``interview_records`` + ``conversations``); answers advance it; finish/abandon
end it. This service is the single home for those transitions so the runtime
never drifts (e.g. two ``in_progress`` rows for one record).
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.user_identity import resolve_user_pk
from app.models.mock_interview_runtime import MockInterviewRuntime

# The single live status; every other status is terminal.
ACTIVE_STATUS = "in_progress"


def create_runtime(
    db: Session,
    *,
    user_id: str,
    interview_record_id: str,
    conversation_id: str | None = None,
    plan: list[dict[str, Any]] | None = None,
    plan_template_key: str = "general",
    interviewer_style: str = "professional",
    voice_mode: str = "hybrid",
    current_stage_key: str | None = None,
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
        status=ACTIVE_STATUS,
        plan_json=json.dumps(plan, ensure_ascii=False) if plan is not None else None,
        plan_template_key=plan_template_key,
        interviewer_style=interviewer_style,
        voice_mode=voice_mode,
        current_stage_key=current_stage_key,
    )
    db.add(runtime)
    if commit:
        db.commit()
        db.refresh(runtime)
    return runtime


def get_active_runtime(db: Session, *, user_id: str) -> MockInterviewRuntime | None:
    """The user's most recent in-progress mock, for resume-after-refresh.

    ``user_id`` is the username; resolved to the stable ``users.id`` for the
    query (returns None for an unknown user)."""
    user_pk = resolve_user_pk(db, user_id)
    if user_pk is None:
        return None
    return (
        db.query(MockInterviewRuntime)
        .filter(
            MockInterviewRuntime.user_id == user_pk,
            MockInterviewRuntime.status == ACTIVE_STATUS,
        )
        .order_by(MockInterviewRuntime.last_activity_at.desc())
        .first()
    )


def get_runtime_for_record(
    db: Session, *, interview_record_id: str,
) -> MockInterviewRuntime | None:
    return (
        db.query(MockInterviewRuntime)
        .filter(MockInterviewRuntime.interview_record_id == interview_record_id)
        .first()
    )


def advance_runtime(
    db: Session,
    runtime: MockInterviewRuntime,
    *,
    current_stage_key: str | None = None,
    stage_index: int | None = None,
    current_question_text: str | None = None,
    current_question_message_id: int | None = None,
    commit: bool = True,
) -> MockInterviewRuntime:
    """Update the live position (stage / current question) + last activity.

    Partial update: only non-None args are applied. The mock flow advances
    forward, so passing ``stage_index=0`` is a no-op by design (the initial
    position is set at create time).
    """
    if current_stage_key is not None:
        runtime.current_stage_key = current_stage_key
    if stage_index is not None:
        runtime.stage_index = stage_index
    if current_question_text is not None:
        runtime.current_question_text = current_question_text
    if current_question_message_id is not None:
        runtime.current_question_message_id = current_question_message_id
    runtime.last_activity_at = datetime.utcnow()
    db.add(runtime)
    if commit:
        db.commit()
        db.refresh(runtime)
    return runtime


def set_status(
    db: Session, runtime: MockInterviewRuntime, status: str, *, commit: bool = True,
) -> MockInterviewRuntime:
    """Transition status (e.g. processing_review / completed / review_failed).

    ``ended_at`` is stamped once, on the first move off ``in_progress`` — so a
    later ``processing_review`` → ``completed`` transition keeps the original
    interview-end time rather than overwriting it with the review-finish time.
    """
    runtime.status = status
    if status != ACTIVE_STATUS and runtime.ended_at is None:
        runtime.ended_at = datetime.utcnow()
    runtime.updated_at = datetime.utcnow()
    db.add(runtime)
    if commit:
        db.commit()
        db.refresh(runtime)
    return runtime


def delete_runtime(db: Session, runtime: MockInterviewRuntime, *, commit: bool = True) -> None:
    """Hard-delete on active abandon (the record/conversation are cleaned up
    by the caller in the same transaction)."""
    db.delete(runtime)
    if commit:
        db.commit()
