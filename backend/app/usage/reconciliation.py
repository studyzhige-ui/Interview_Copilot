"""Evidence-backed operator corrections; never sends/retries a provider request.

CLI access is deliberately separate from the user API and Agent Tools. An
invoice can aggregate requests: do not allocate that total to a single receipt
without a verifiable allocation. Original rate snapshots remain immutable.
"""

from __future__ import annotations

import hashlib
import json
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db.types import utc_now
from app.models.model_budget import ModelBudgetReservation, UsageAdjustment
from app.usage import service
from app.usage.pricing import MAX_COST, cost_micros, freeze, quantities


def _state(row):
    return {
        "status": row.status,
        "revision": row.revision,
        "reserved_tokens": row.reserved_tokens,
        "observed_tokens": row.observed_tokens,
        "reserved_units": row.reserved_units_json or {},
        "observed_units": row.observed_units_json or {},
        "cost_reserved_micros": row.cost_reserved_micros,
        "cost_observed_micros": row.cost_observed_micros,
        "invoice_cost_micros": row.invoice_cost_micros,
        "valuation_snapshot": row.valuation_snapshot_json,
        "reconciliation_ref": row.reconciliation_ref,
    }


def reconcile(
    db: Session,
    *,
    user_id: int,
    receipt_id: str,
    expected_revision: int,
    request_id: str,
    operator: str,
    evidence_ref: str,
    outcome: str,
    observed_units: dict[str, int],
    observed_tokens: int,
    currency: str,
    invoice_cost_micros: int | None = None,
    rates: dict[str, str] | None = None,
    quiesced: bool = False,
) -> UsageAdjustment:
    """Apply one CAS/idempotent audited correction in the caller's transaction.

    A live/unknown dispatch requires the operator to attest it is quiesced and
    supply verified external evidence. A local timeout alone is not evidence.
    Neither user/API nor model can call this function through a product Tool.
    """
    for text, bound in (
        (receipt_id, 64),
        (request_id, 128),
        (operator, 120),
        (evidence_ref, 256),
    ):
        if not isinstance(text, str) or not 1 <= len(text.strip()) <= bound:
            raise ValueError("invalid_reconciliation_identity")
    if type(quiesced) is not bool:
        raise ValueError("quiesced_requires_boolean_attestation")
    if type(expected_revision) is not int or expected_revision < 0:
        raise ValueError("invalid_reconciliation_revision")
    if outcome not in {"completed", "rejected"}:
        raise ValueError("reconciliation_requires_known_outcome")
    actual = quantities(observed_units)
    if actual.get("requests") != 1:
        raise ValueError("reconciliation_must_retain_admitted_attempt")
    if type(observed_tokens) is not int or not 0 <= observed_tokens <= 2**31 - 1:
        raise ValueError("invalid_reconciled_tokens")
    if {"input_tokens", "output_tokens"} <= actual.keys() and observed_tokens != sum(
        actual.get(k, 0)
        for k in (
            "input_tokens",
            "output_tokens",
            "cache_read_tokens",
            "cache_write_tokens",
        )
    ):
        raise ValueError("inconsistent_reconciled_token_buckets")
    if invoice_cost_micros is not None and (
        type(invoice_cost_micros) is not int or not 0 <= invoice_cost_micros <= MAX_COST
    ):
        raise ValueError("invalid_invoice_amount")
    if outcome == "rejected" and (
        observed_tokens
        or any(
            v
            for k, v in actual.items()
            if k not in {"requests", "external_requests", "tool_invocations"}
        )
    ):
        raise ValueError("rejected_request_cannot_contain_consumed_tokens")
    payload = dict(
        receipt_id=receipt_id,
        expected_revision=expected_revision,
        operator=operator,
        evidence_ref=evidence_ref,
        outcome=outcome,
        units=actual,
        tokens=observed_tokens,
        currency=currency,
        invoice_cost_micros=invoice_cost_micros,
        rates=rates,
        quiesced=quiesced,
    )
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, allow_nan=False).encode()
    ).hexdigest()
    identity = hashlib.sha256(f"{user_id}:{request_id}".encode()).hexdigest()
    service._lock_account(db, user_id)
    existing = db.get(UsageAdjustment, identity)
    if existing is not None:
        if existing.payload_fingerprint != digest:
            raise ValueError("reconciliation_idempotency_conflict")
        return existing
    row = db.scalar(
        select(ModelBudgetReservation)
        .where(
            ModelBudgetReservation.id == receipt_id,
            ModelBudgetReservation.user_id == user_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise ValueError("usage_receipt_not_found")
    if row.revision != expected_revision:
        raise ValueError("usage_receipt_revision_changed")
    active = row.status in {"reserved", "unknown"}
    if active and not quiesced:
        raise ValueError("quiesce_and_verify_dispatch_before_reconciliation")
    window = service._window(db, user_id, row.window_date)
    if currency != window.currency:
        raise ValueError("reconciliation_currency_mismatch")
    snapshot = row.price_snapshot_json
    if rates is not None:
        snapshot = freeze(
            raw=json.dumps({f"{row.meter}:{row.provider}:{row.model}": rates}),
            currency=currency,
            meter=row.meter,
            provider=row.provider,
            model=row.model,
        )
    rated = cost_micros(snapshot, actual)
    value = invoice_cost_micros if invoice_cost_micros is not None else rated
    if value is None:
        raise ValueError("reconciliation_requires_price_or_verified_invoice_amount")
    # Preserve physical attempts and all categories, including zero observations.
    if set(row.reserved_units_json or {}) - set(actual):
        raise ValueError("reconciliation_missing_resource_observation")
    for key in ("requests", "external_requests", "tool_invocations"):
        if actual.get(key, 0) != (row.reserved_units_json or {}).get(key, 0):
            raise ValueError("reconciliation_cannot_erase_attempts")
    before = _state(row)
    if active:
        window.tokens_reserved -= row.reserved_tokens
        window.cost_reserved_micros -= row.cost_reserved_micros
        window.units_reserved_json = service._add(
            window.units_reserved_json or {}, row.reserved_units_json or {}, -1
        )
        old_tokens, old_cost, old_units = 0, 0, {}
    else:
        old_tokens, old_cost, old_units = (
            row.observed_tokens,
            row.cost_observed_micros or 0,
            row.observed_units_json or {},
        )
    window.tokens_used += observed_tokens - old_tokens
    if not 0 <= window.cost_used_micros + value - old_cost <= 2**63 - 1:
        raise ValueError("reconciled_window_cost_out_of_range")
    window.cost_used_micros += value - old_cost
    window.units_used_json = service._add(
        service._add(window.units_used_json or {}, old_units, -1), actual
    )
    row.observed_tokens, row.observed_units_json = observed_tokens, actual
    row.cost_observed_micros, row.invoice_cost_micros = value, invoice_cost_micros
    row.valuation_snapshot_json = snapshot
    row.status = "rejected" if outcome == "rejected" else "settled"
    row.revision += 1
    row.reconciliation_ref, row.settled_at = evidence_ref, utc_now()
    adjustment = UsageAdjustment(
        id=identity,
        user_id=user_id,
        receipt_id=receipt_id,
        payload_fingerprint=digest,
        operator=operator,
        evidence_ref=evidence_ref,
        before_json=before,
        after_json=_state(row),
    )
    db.add(adjustment)
    db.flush()
    return adjustment
