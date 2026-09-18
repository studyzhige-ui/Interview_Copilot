"""Atomic account admission in the SAME transaction as a model dispatch.

This module never commits, contacts providers, or stores prompt/user data.
Window creation is an upsert; admission is a conditional SQL UPDATE, so two
workers cannot both spend the last allowance. All settlements take the same
reservation -> window order and are idempotent. A new UTC day is an explicit
policy boundary, not an application restart or a new conversation.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.types import utc_now
from app.models.model_budget import ModelBudgetReservation, ModelBudgetWindow


class ModelBudgetExceededError(RuntimeError):
    """An account safety boundary, not a statement that the user's task is done."""

    def __init__(self, code: str = "primary_model_daily_budget_exhausted") -> None:
        self.code = code
        super().__init__(
            "本日回答模型额度不足；已有成果已保留，请查看模型页的已用与预留额度。"
        )


def reservation_id(user_id: int, turn_id: str, call_id: str) -> str:
    return hashlib.sha256(f"{user_id}:{turn_id}:{call_id}".encode()).hexdigest()


def _date(now: datetime | None) -> date:
    value = now or utc_now()
    if value.tzinfo is None:
        raise ValueError("budget clock must be timezone-aware")
    return value.astimezone(UTC).date()


def reserve(
    db: Session,
    *,
    user_id: int,
    turn_id: str,
    call_id: str,
    token_allowance: int,
    now: datetime | None = None,
) -> str:
    if type(token_allowance) is not int or token_allowance <= 0:
        raise ValueError("token_allowance must be a positive integer")
    identity = reservation_id(user_id, turn_id, call_id)
    if db.get(ModelBudgetReservation, identity) is not None:
        # The model dispatcher owns replay. Returning from here must never
        # silently authorize a second provider call for an existing identity.
        raise ValueError("model_budget_reservation_already_exists")
    day = _date(now)
    dialect = db.get_bind().dialect.name
    insert = pg_insert if dialect == "postgresql" else sqlite_insert
    if dialect not in {"postgresql", "sqlite"}:
        raise ValueError("unsupported budget database")
    db.execute(
        insert(ModelBudgetWindow)
        .values(
            user_id=user_id,
            window_date=day,
            call_limit=settings.MODEL_DAILY_CALL_LIMIT,
            token_limit=settings.MODEL_DAILY_TOKEN_LIMIT,
        )
        .on_conflict_do_nothing(index_elements=["user_id", "window_date"])
    )
    changed = db.execute(
        update(ModelBudgetWindow)
        .where(
            ModelBudgetWindow.user_id == user_id,
            ModelBudgetWindow.window_date == day,
            ModelBudgetWindow.calls_admitted < ModelBudgetWindow.call_limit,
            ModelBudgetWindow.tokens_used
            + ModelBudgetWindow.tokens_reserved
            + token_allowance
            <= ModelBudgetWindow.token_limit,
        )
        .values(
            calls_admitted=ModelBudgetWindow.calls_admitted + 1,
            tokens_reserved=ModelBudgetWindow.tokens_reserved + token_allowance,
        )
        .execution_options(synchronize_session=False)
    )
    if changed.rowcount != 1:
        raise ModelBudgetExceededError()
    db.add(
        ModelBudgetReservation(
            id=identity,
            user_id=user_id,
            window_date=day,
            reserved_tokens=token_allowance,
            status="reserved",
        )
    )
    db.flush()
    return identity


def settle(
    db: Session,
    *,
    user_id: int,
    turn_id: str,
    call_id: str,
    outcome: str,
    observed_tokens: int | None,
    reconciliation_ref: str | None = None,
) -> None:
    if outcome not in {"completed", "rejected", "unknown"}:
        raise ValueError("invalid accounting outcome")
    if observed_tokens is not None and (
        type(observed_tokens) is not int or observed_tokens < 0
    ):
        raise ValueError("observed_tokens must be a non-negative integer")
    row = db.execute(
        select(ModelBudgetReservation)
        .where(ModelBudgetReservation.id == reservation_id(user_id, turn_id, call_id))
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if row is None:
        return  # Legacy dispatch created before accounting was introduced.
    if row.status not in {"reserved", "unknown"}:
        return
    if row.status == "unknown" and outcome != "unknown" and not reconciliation_ref:
        # A subsequent error/retry cannot settle an earlier uncertain request.
        return
    if (
        reconciliation_ref is not None
        and not 1 <= len(reconciliation_ref.strip()) <= 256
    ):
        raise ValueError("invalid reconciliation evidence reference")
    if outcome == "unknown":
        # Usage from an interrupted stream may only be partial. Keep the
        # preflight allowance (or an even larger observation) on hold.
        held = max(row.reserved_tokens, observed_tokens or 0)
        delta = held - row.reserved_tokens
        db.execute(
            update(ModelBudgetWindow)
            .where(
                ModelBudgetWindow.user_id == user_id,
                ModelBudgetWindow.window_date == row.window_date,
            )
            .values(tokens_reserved=ModelBudgetWindow.tokens_reserved + delta)
            .execution_options(synchronize_session=False)
        )
        row.reserved_tokens = held
        row.observed_tokens = max(row.observed_tokens, observed_tokens or 0)
        row.status = "unknown"
    else:
        amount = (
            0
            if outcome == "rejected"
            else observed_tokens
            if observed_tokens is not None
            else row.reserved_tokens
        )
        db.execute(
            update(ModelBudgetWindow)
            .where(
                ModelBudgetWindow.user_id == user_id,
                ModelBudgetWindow.window_date == row.window_date,
            )
            .values(
                tokens_reserved=ModelBudgetWindow.tokens_reserved - row.reserved_tokens,
                tokens_used=ModelBudgetWindow.tokens_used + amount,
            )
            .execution_options(synchronize_session=False)
        )
        row.observed_tokens = amount
        row.status = (
            "rejected"
            if outcome == "rejected"
            else "settled"
            if observed_tokens is not None
            else "estimated"
        )
        row.settled_at = utc_now()
        row.reconciliation_ref = reconciliation_ref
    db.flush()


def usage_view(db: Session, *, user_id: int, now: datetime | None = None) -> dict:
    day = _date(now)
    row = db.get(ModelBudgetWindow, (user_id, day), populate_existing=True)
    return {
        "scope": "primary_chat_agent",
        "unit": "logical_tokens_not_currency",
        "window_date": day.isoformat(),
        "timezone": "UTC",
        "call_limit": row.call_limit if row else settings.MODEL_DAILY_CALL_LIMIT,
        "token_limit": row.token_limit if row else settings.MODEL_DAILY_TOKEN_LIMIT,
        "calls_admitted": row.calls_admitted if row else 0,
        "tokens_used": row.tokens_used if row else 0,
        "tokens_reserved": row.tokens_reserved if row else 0,
        "excluded": [
            "internal_models",
            "compaction",
            "embedding",
            "reranking",
            "speech",
            "external_tools",
        ],
    }
