"""Bounded, owner-scoped receipt projections; no prompts or credentials."""

from datetime import date
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.model_budget import (
    ModelBudgetReservation,
    ModelBudgetWindow,
    UsageAdjustment,
)


def history(
    db: Session,
    *,
    user_id: int,
    day: date | None = None,
    before: str | None = None,
    limit: int = 50,
) -> dict:
    if not 1 <= limit <= 100:
        raise ValueError("usage_page_limit")
    query = (
        select(ModelBudgetReservation, ModelBudgetWindow.currency)
        .join(
            ModelBudgetWindow,
            (ModelBudgetWindow.user_id == ModelBudgetReservation.user_id)
            & (ModelBudgetWindow.window_date == ModelBudgetReservation.window_date),
        )
        .where(ModelBudgetReservation.user_id == user_id)
    )
    if day is not None:
        query = query.where(ModelBudgetReservation.window_date == day)
    if before:
        anchor = db.scalar(
            select(ModelBudgetReservation).where(
                ModelBudgetReservation.user_id == user_id,
                ModelBudgetReservation.id == before,
            )
        )
        if anchor is None:
            raise ValueError("usage_cursor_not_found")
        from sqlalchemy import or_, and_

        query = query.where(
            or_(
                ModelBudgetReservation.created_at < anchor.created_at,
                and_(
                    ModelBudgetReservation.created_at == anchor.created_at,
                    ModelBudgetReservation.id < anchor.id,
                ),
            )
        )
    rows = db.execute(
        query.order_by(
            ModelBudgetReservation.created_at.desc(), ModelBudgetReservation.id.desc()
        ).limit(limit + 1)
    ).all()
    items = [receipt_view(row, currency=currency) for row, currency in rows[:limit]]
    return {
        "items": items,
        "next_cursor": rows[limit - 1][0].id if len(rows) > limit else None,
    }


def receipt_view(row, *, currency: str):
    return {
        "id": row.id,
        "revision": row.revision,
        "date": row.window_date.isoformat(),
        "currency": currency,
        "meter": row.meter,
        "provider": row.provider,
        "provider_request_id": row.provider_request_id,
        "model": row.model,
        "status": row.status,
        "reserved_units": row.reserved_units_json or {},
        "observed_units": row.observed_units_json,
        "reserved_tokens": row.reserved_tokens,
        "observed_tokens": row.observed_tokens,
        "cost_reserved_micros": row.cost_reserved_micros,
        "cost_observed_micros": row.cost_observed_micros,
        "cost_basis": "provider_invoice"
        if row.invoice_cost_micros is not None
        else "unpriced"
        if row.cost_observed_micros is None and row.price_snapshot_json is None
        else "rated_estimate"
        if row.status in {"reserved", "unknown", "estimated"}
        else "rated_usage",
        "price_version": (
            row.valuation_snapshot_json or row.price_snapshot_json or {}
        ).get("version"),
        "admission_price_version": (row.price_snapshot_json or {}).get("version"),
        "created_at": row.created_at.isoformat(),
        "settled_at": row.settled_at.isoformat() if row.settled_at else None,
        "reconciled": row.reconciliation_ref is not None,
    }


def corrections(db: Session, *, user_id: int, receipt_id: str, limit: int = 50):
    if not 1 <= limit <= 100:
        raise ValueError("usage_page_limit")
    rows = db.scalars(
        select(UsageAdjustment)
        .where(
            UsageAdjustment.user_id == user_id, UsageAdjustment.receipt_id == receipt_id
        )
        .order_by(UsageAdjustment.created_at.desc(), UsageAdjustment.id.desc())
        .limit(limit)
    ).all()
    # Operator/evidence documents may be sensitive. End-user projection exposes
    # correction facts and identity, not internal evidence locations or names.
    return [
        {
            "id": r.id,
            "created_at": r.created_at.isoformat(),
            "before": {
                k: v for k, v in r.before_json.items() if k != "reconciliation_ref"
            },
            "after": {
                k: v for k, v in r.after_json.items() if k != "reconciliation_ref"
            },
        }
        for r in rows
    ]


def wire(value):
    """Money crosses JSON as decimal integer strings, not lossy JS Number."""
    if isinstance(value, dict):
        return {
            k: str(v) if k.endswith("_micros") and type(v) is int else wire(v)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [wire(v) for v in value]
    return value
