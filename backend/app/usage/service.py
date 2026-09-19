"""Single durable consumption ledger shared by every provider boundary.

No network I/O, commit, rollback, or prompt storage belongs here. Caller owns a
short transaction. Lock order is accounting-account -> reservation -> window;
no user/business row is locked while acquiring an accounting lock. Historical
primary-model table names and balances are retained, not reset on rollout.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime

from sqlalchemy import func, select, or_, and_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.types import utc_now
from app.models.model_budget import (
    ModelBudgetReservation,
    ModelBudgetWindow,
    UsageAccount,
)
from app.usage.pricing import cost_micros, freeze, quantities


class ModelBudgetExceededError(RuntimeError):
    def __init__(self, code: str = "account_usage_limit_exceeded") -> None:
        self.code = code
        super().__init__(
            "账户调用、资源或费用额度不足；已有成果已保留，请查看用量页面。"
        )


def reservation_id(user_id: int, turn_id: str, call_id: str) -> str:
    return hashlib.sha256(f"{user_id}:{turn_id}:{call_id}".encode()).hexdigest()


def _date(now: datetime | None) -> date:
    value = now or utc_now()
    if value.tzinfo is None:
        raise ValueError("budget clock must be timezone-aware")
    return value.astimezone(UTC).date()


def _insert(db):
    name = db.get_bind().dialect.name
    if name not in {"postgresql", "sqlite"}:
        raise ValueError("unsupported budget database")
    return pg_insert if name == "postgresql" else sqlite_insert


def _lock_account(db: Session, user_id: int) -> None:
    if type(user_id) is not int or user_id <= 0:
        raise ValueError("usage_requires_stable_account_id")
    # Existing accounts do not reacquire the User FK key-share lock. Their
    # business transactions may hold a User FOR UPDATE while a model runs.
    if db.get(UsageAccount, user_id) is None:
        db.execute(
            _insert(db)(UsageAccount)
            .values(user_id=user_id)
            .on_conflict_do_nothing(index_elements=["user_id"])
        )
    db.execute(
        select(UsageAccount).where(UsageAccount.user_id == user_id).with_for_update()
    ).scalar_one()


def _window(db, user_id, day):
    return db.execute(
        select(ModelBudgetWindow)
        .where(
            ModelBudgetWindow.user_id == user_id, ModelBudgetWindow.window_date == day
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one()


def _add(left: dict, right: dict, sign: int = 1) -> dict:
    result = dict(left)
    for key, value in right.items():
        result[key] = result.get(key, 0) + sign * value
        if not 0 <= result[key] < 2**63:
            raise ValueError("usage_counter_integrity_error")
    return result


def reserve(
    db: Session,
    *,
    user_id: int,
    turn_id: str,
    call_id: str,
    token_allowance: int,
    now: datetime | None = None,
    meter: str = "primary",
    provider: str = "legacy",
    model: str = "legacy",
    units: dict | None = None,
    fingerprint: str | None = None,
) -> str:
    if (
        type(token_allowance) is not int
        or token_allowance < 0
        or (meter == "primary" and token_allowance == 0)
    ):
        raise ValueError("token_allowance must be a positive integer")
    if (
        token_allowance > 2**31 - 1
        or not 1 <= len(meter) <= 80
        or len(provider) > 120
        or len(model) > 255
    ):
        raise ValueError("invalid_consumption_descriptor")
    allowed = quantities(
        units
        if units is not None
        else {"input_tokens": token_allowance, "output_tokens": 0, "requests": 1}
    )
    if allowed.get("requests") != 1:
        raise ValueError("admission_requires_one_request")
    limits = quantities(json.loads(settings.USAGE_DAILY_UNITS_JSON))
    snapshot = freeze(
        raw=settings.USAGE_RATE_CARD_JSON,
        currency=settings.USAGE_CURRENCY,
        meter=meter,
        provider=provider,
        model=model,
    )
    estimated = cost_micros(snapshot, allowed)
    if settings.USAGE_DAILY_COST_LIMIT_MICROS is not None and estimated is None:
        raise ModelBudgetExceededError("usage_price_required")
    _lock_account(db, user_id)
    identity = reservation_id(user_id, turn_id, call_id)
    if db.get(ModelBudgetReservation, identity, populate_existing=True) is not None:
        raise ValueError("model_budget_reservation_already_exists")
    outstanding = db.scalar(
        select(func.count())
        .select_from(ModelBudgetReservation)
        .where(
            ModelBudgetReservation.user_id == user_id,
            ModelBudgetReservation.status.in_(["reserved", "unknown"]),
        )
    )
    if outstanding >= settings.USAGE_MAX_UNRESOLVED:
        raise ModelBudgetExceededError("too_many_unresolved_consumptions")
    day = _date(now)
    db.execute(
        _insert(db)(ModelBudgetWindow)
        .values(
            user_id=user_id,
            window_date=day,
            call_limit=settings.MODEL_DAILY_CALL_LIMIT,
            token_limit=settings.MODEL_DAILY_TOKEN_LIMIT,
            currency=settings.USAGE_CURRENCY,
            cost_limit_micros=settings.USAGE_DAILY_COST_LIMIT_MICROS,
            unit_limits_json=limits,
        )
        .on_conflict_do_nothing(index_elements=["user_id", "window_date"])
    )
    window = _window(db, user_id, day)
    if window.currency != settings.USAGE_CURRENCY:
        raise ModelBudgetExceededError("usage_currency_changed_within_window")
    monetary_limit = settings.USAGE_DAILY_COST_LIMIT_MICROS
    if window.cost_limit_micros is not None:
        monetary_limit = (
            min(monetary_limit, window.cost_limit_micros)
            if monetary_limit is not None
            else window.cost_limit_micros
        )
    if monetary_limit is not None:
        if estimated is None:
            raise ModelBudgetExceededError("usage_price_required")
        unpriced = db.scalar(
            select(func.count())
            .select_from(ModelBudgetReservation)
            .where(
                ModelBudgetReservation.user_id == user_id,
                ModelBudgetReservation.window_date == day,
                or_(
                    and_(
                        ModelBudgetReservation.status.in_(["reserved", "unknown"]),
                        ModelBudgetReservation.price_snapshot_json.is_(None),
                    ),
                    and_(
                        ModelBudgetReservation.status.in_(
                            ["settled", "estimated", "rejected"]
                        ),
                        ModelBudgetReservation.cost_observed_micros.is_(None),
                    ),
                ),
            )
        )
        if unpriced:
            raise ModelBudgetExceededError(
                "historical_usage_needs_pricing_reconciliation"
            )
        if (
            window.cost_used_micros + window.cost_reserved_micros + estimated
            > monetary_limit
        ):
            raise ModelBudgetExceededError("account_currency_budget_exhausted")
    if (
        window.cost_used_micros + window.cost_reserved_micros + (estimated or 0)
        > 2**63 - 1
    ):
        raise ModelBudgetExceededError("usage_ledger_capacity_exhausted")
    if window.calls_admitted >= min(window.call_limit, settings.MODEL_DAILY_CALL_LIMIT):
        raise ModelBudgetExceededError("account_call_budget_exhausted")
    if window.tokens_used + window.tokens_reserved + token_allowance > min(
        window.token_limit, settings.MODEL_DAILY_TOKEN_LIMIT
    ):
        raise ModelBudgetExceededError("account_token_budget_exhausted")
    used, held = window.units_used_json or {}, window.units_reserved_json or {}
    # Removing a configured key does not relax an already frozen daily cap.
    frozen_limits = window.unit_limits_json or {}
    effective_limits = {
        key: min(v for v in (limits.get(key), frozen_limits.get(key)) if v is not None)
        for key in limits.keys() | frozen_limits.keys()
    }
    for key, bound in effective_limits.items():
        if used.get(key, 0) + held.get(key, 0) + allowed.get(key, 0) > bound:
            raise ModelBudgetExceededError(f"account_{key}_budget_exhausted")
    # An admitted tighter policy becomes part of this day's durable envelope.
    # Removing a later config value must not silently reopen that allowance.
    window.call_limit = min(window.call_limit, settings.MODEL_DAILY_CALL_LIMIT)
    window.token_limit = min(window.token_limit, settings.MODEL_DAILY_TOKEN_LIMIT)
    window.cost_limit_micros = monetary_limit
    window.unit_limits_json = effective_limits
    window.calls_admitted += 1
    window.tokens_reserved += token_allowance
    window.cost_reserved_micros += estimated or 0
    window.units_reserved_json = _add(held, allowed)
    db.add(
        ModelBudgetReservation(
            id=identity,
            user_id=user_id,
            window_date=day,
            reserved_tokens=token_allowance,
            status="reserved",
            meter=meter,
            provider=provider,
            model=model,
            request_fingerprint=fingerprint,
            reserved_units_json=allowed,
            price_snapshot_json=snapshot,
            cost_reserved_micros=estimated or 0,
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
    observed_units: dict | None = None,
) -> None:
    settle_identity(
        db,
        user_id=user_id,
        identity=reservation_id(user_id, turn_id, call_id),
        outcome=outcome,
        observed_tokens=observed_tokens,
        reconciliation_ref=reconciliation_ref,
        observed_units=observed_units,
    )


def settle_identity(
    db: Session,
    *,
    user_id: int,
    identity: str,
    outcome: str,
    observed_tokens: int | None = None,
    observed_units: dict | None = None,
    reconciliation_ref: str | None = None,
) -> None:
    if outcome not in {"completed", "rejected", "unknown"}:
        raise ValueError("invalid accounting outcome")
    if observed_tokens is not None and (
        type(observed_tokens) is not int or not 0 <= observed_tokens <= 2**31 - 1
    ):
        raise ValueError("invalid observed token count")
    if observed_units is not None:
        observed_units = quantities(observed_units)
    if reconciliation_ref is not None and (
        not isinstance(reconciliation_ref, str)
        or not 1 <= len(reconciliation_ref.strip()) <= 256
    ):
        raise ValueError("invalid reconciliation evidence reference")
    _lock_account(db, user_id)
    row = db.execute(
        select(ModelBudgetReservation)
        .where(
            ModelBudgetReservation.id == identity,
            ModelBudgetReservation.user_id == user_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if row is None:
        return  # A pre-accounting dispatch is not a new billable action.
    if row.status not in {"reserved", "unknown"}:
        return
    if row.status == "unknown" and outcome != "unknown" and not reconciliation_ref:
        return
    reserved = row.reserved_units_json or {}
    # Physical-attempt counters are established by admission, not a provider's
    # usage payload. Missing metrics are permitted; conflicting ones are not.
    for key in ("requests", "external_requests", "tool_invocations"):
        if observed_units is not None and key in observed_units:
            if observed_units[key] != reserved.get(key, 0):
                raise ValueError("settlement_cannot_change_admitted_attempts")
    if (
        observed_tokens is not None
        and observed_units is not None
        and {"input_tokens", "output_tokens"} <= observed_units.keys()
        and observed_tokens
        != sum(
            observed_units.get(key, 0)
            for key in (
                "input_tokens",
                "output_tokens",
                "cache_read_tokens",
                "cache_write_tokens",
            )
        )
    ):
        raise ValueError("inconsistent_settlement_token_buckets")
    window = _window(db, user_id, row.window_date)
    if outcome == "unknown":
        merged = {
            k: max(v, (observed_units or {}).get(k, 0)) for k, v in reserved.items()
        }
        for k, v in (observed_units or {}).items():
            merged[k] = max(merged.get(k, 0), v)
        amount = max(row.reserved_tokens, observed_tokens or 0)
        estimate = max(
            row.cost_reserved_micros, cost_micros(row.price_snapshot_json, merged) or 0
        )
        window.tokens_reserved += amount - row.reserved_tokens
        window.units_reserved_json = _add(
            _add(window.units_reserved_json or {}, reserved, -1), merged
        )
        window.cost_reserved_micros += estimate - row.cost_reserved_micros
        row.reserved_units_json = merged
        row.reserved_tokens = amount
        row.cost_reserved_micros = estimate
        row.observed_tokens = max(row.observed_tokens or 0, observed_tokens or 0)
        row.observed_units_json = observed_units
        row.status = "unknown"
    else:
        if outcome == "rejected":
            actual = {k: 0 for k in reserved}
            for key in ("requests", "external_requests", "tool_invocations"):
                if key in reserved:
                    actual[key] = reserved[key]  # Attempt limits are not refunds.
            amount = 0
        else:
            actual = {**reserved, **(observed_units or {})}
            amount = (
                observed_tokens if observed_tokens is not None else row.reserved_tokens
            )
        rated = cost_micros(row.price_snapshot_json, actual)
        if rated is None and row.price_snapshot_json is not None:
            # A provider omitted a priced unit. Retain the preflight estimate;
            # missing metrics must not turn a priced request into zero cost.
            actual = {**reserved, **actual}
            rated = cost_micros(row.price_snapshot_json, actual)
        window.tokens_reserved -= row.reserved_tokens
        window.tokens_used += amount
        window.units_reserved_json = _add(
            window.units_reserved_json or {}, reserved, -1
        )
        window.units_used_json = _add(window.units_used_json or {}, actual)
        window.cost_reserved_micros -= row.cost_reserved_micros
        window.cost_used_micros += rated or 0
        row.observed_tokens = amount
        row.observed_units_json = actual
        row.cost_observed_micros = rated
        measurement_complete = observed_units is not None and all(
            key in observed_units for key, value in reserved.items() if value
        )
        row.status = (
            "rejected"
            if outcome == "rejected"
            else "settled"
            if measurement_complete
            else "estimated"
        )
        row.settled_at = utc_now()
        row.reconciliation_ref = reconciliation_ref
    row.revision = (row.revision or 0) + 1
    db.flush()


def usage_view(db: Session, *, user_id: int, now: datetime | None = None) -> dict:
    day = _date(now)
    row = db.get(ModelBudgetWindow, (user_id, day), populate_existing=True)
    grouped = db.execute(
        select(
            ModelBudgetReservation.meter, ModelBudgetReservation.status, func.count()
        )
        .where(
            ModelBudgetReservation.user_id == user_id,
            ModelBudgetReservation.window_date == day,
        )
        .group_by(ModelBudgetReservation.meter, ModelBudgetReservation.status)
    ).all()
    unpriced = db.scalar(
        select(func.count())
        .select_from(ModelBudgetReservation)
        .where(
            ModelBudgetReservation.user_id == user_id,
            ModelBudgetReservation.window_date == day,
            or_(
                and_(
                    ModelBudgetReservation.status.in_(["reserved", "unknown"]),
                    ModelBudgetReservation.price_snapshot_json.is_(None),
                ),
                and_(
                    ModelBudgetReservation.status.in_(
                        ["settled", "estimated", "rejected"]
                    ),
                    ModelBudgetReservation.cost_observed_micros.is_(None),
                ),
            ),
        )
    )
    unresolved = db.scalar(
        select(func.count())
        .select_from(ModelBudgetReservation)
        .where(
            ModelBudgetReservation.user_id == user_id,
            ModelBudgetReservation.status.in_(["reserved", "unknown"]),
        )
    )
    return {
        "scope": "account_consumption",
        "unit": "logical_tokens_and_resource_units",
        "window_date": day.isoformat(),
        "timezone": "UTC",
        "call_limit": row.call_limit if row else settings.MODEL_DAILY_CALL_LIMIT,
        "token_limit": row.token_limit if row else settings.MODEL_DAILY_TOKEN_LIMIT,
        "calls_admitted": row.calls_admitted if row else 0,
        "tokens_used": row.tokens_used if row else 0,
        "tokens_reserved": row.tokens_reserved if row else 0,
        "currency": row.currency if row else settings.USAGE_CURRENCY,
        "cost_limit_micros": row.cost_limit_micros
        if row
        else settings.USAGE_DAILY_COST_LIMIT_MICROS,
        "rated_cost_used_micros": row.cost_used_micros if row else 0,
        "rated_cost_reserved_micros": row.cost_reserved_micros if row else 0,
        "cost_is_vendor_invoice": False,
        "unpriced_requests": unpriced,
        "unresolved_all_dates": unresolved,
        "units_used": row.units_used_json if row else {},
        "units_reserved": row.units_reserved_json if row else {},
        "categories": [{"meter": m, "status": s, "count": n} for m, s, n in grouped],
        "excluded": [
            "infrastructure_operating_cost",
            "oauth_and_catalog_control_plane",
        ],
        "invoice_reconciled_requests": db.scalar(
            select(func.count())
            .select_from(ModelBudgetReservation)
            .where(
                ModelBudgetReservation.user_id == user_id,
                ModelBudgetReservation.window_date == day,
                ModelBudgetReservation.invoice_cost_micros.is_not(None),
            )
        ),
        "unit_limits": row.unit_limits_json
        if row
        else json.loads(settings.USAGE_DAILY_UNITS_JSON),
    }
