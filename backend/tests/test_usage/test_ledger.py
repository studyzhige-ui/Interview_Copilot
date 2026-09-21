"""Real SQL ledger tests with synthetic tariffs, never assertions of vendor price."""

from datetime import UTC, datetime, timedelta
import json

import pytest
from sqlalchemy import select
from app.core.config import settings
from app.models.user import User
from app.models.model_budget import ModelBudgetReservation, UsageAdjustment
from app.usage import service, reconciliation, queries
from app.usage.pricing import cost_micros, freeze, model_units, quantities

NOW = datetime(2026, 9, 19, tzinfo=UTC)


def owner(db):
    row = User(username="usage-test", hashed_password="x")
    db.add(row)
    db.flush()
    return row.id


def reserve(db, user, *, name="1", meter="embedding", units=None, **kw):
    units = units or {"requests": 1, "input_tokens": 10, "output_tokens": 0}
    return service.reserve(
        db,
        user_id=user,
        turn_id="operation",
        call_id=name,
        meter=meter,
        provider="fixture",
        model="fixture",
        units=units,
        token_allowance=units.get("input_tokens", 0) + units.get("output_tokens", 0),
        now=NOW,
        **kw,
    )


def view(db, user):
    return service.usage_view(db, user_id=user, now=NOW)


@pytest.mark.parametrize(
    "meter",
    [
        "primary",
        "internal_router",
        "internal_worker",
        "compaction",
        "vision",
        "model_completion",
        "embedding",
        "reranking",
        "transcription",
        "speech",
        "external_tool",
        "external_request",
        "diarization",
        "document_parsing",
    ],
)
def test_all_categories_consume_the_same_account_allowance(
    db_session, monkeypatch, meter
):
    user = owner(db_session)
    monkeypatch.setattr(settings, "MODEL_DAILY_CALL_LIMIT", 1)
    reserve(db_session, user, meter=meter)
    with pytest.raises(service.ModelBudgetExceededError, match="额度"):
        reserve(db_session, user, name="new", meter="different_category")
    assert view(db_session, user)["calls_admitted"] == 1


def test_rate_version_frozen_and_missing_price_not_free(db_session, monkeypatch):
    user = owner(db_session)
    monkeypatch.setattr(
        settings,
        "USAGE_RATE_CARD_JSON",
        json.dumps({"embedding:fixture:fixture": {"input_tokens": "0.0000001"}}),
    )
    identity = reserve(db_session, user)
    original = db_session.get(
        ModelBudgetReservation, identity
    ).price_snapshot_json.copy()
    monkeypatch.setattr(
        settings,
        "USAGE_RATE_CARD_JSON",
        json.dumps({"embedding:fixture:fixture": {"input_tokens": "999"}}),
    )
    service.settle_identity(
        db_session,
        user_id=user,
        identity=identity,
        outcome="completed",
        observed_tokens=10,
        observed_units={"input_tokens": 10, "output_tokens": 0, "requests": 1},
    )
    row = db_session.get(ModelBudgetReservation, identity)
    assert row.cost_observed_micros == 1
    assert row.price_snapshot_json == original
    reserve(
        db_session,
        user,
        name="unpriced",
        meter="speech",
        units={"requests": 1, "characters": 3},
    )
    assert view(db_session, user)["unpriced_requests"] == 1


def test_currency_cap_requires_all_historical_requests_valued(db_session, monkeypatch):
    user = owner(db_session)
    first = reserve(db_session, user)
    service.settle_identity(
        db_session,
        user_id=user,
        identity=first,
        outcome="completed",
        observed_tokens=10,
    )
    monkeypatch.setattr(
        settings,
        "USAGE_RATE_CARD_JSON",
        json.dumps({"embedding:fixture:fixture": {"input_tokens": "0.01"}}),
    )
    monkeypatch.setattr(settings, "USAGE_DAILY_COST_LIMIT_MICROS", 1000000)
    with pytest.raises(service.ModelBudgetExceededError) as err:
        reserve(db_session, user, name="second")
    assert err.value.code == "historical_usage_needs_pricing_reconciliation"
    reconciliation.reconcile(
        db_session,
        user_id=user,
        receipt_id=first,
        expected_revision=1,
        request_id="correction1",
        operator="test-operator",
        evidence_ref="sha256:fixture",
        outcome="completed",
        observed_units={"input_tokens": 10, "output_tokens": 0, "requests": 1},
        observed_tokens=10,
        currency="USD",
        invoice_cost_micros=100000,
    )
    reserve(db_session, user, name="second")
    assert view(db_session, user)["rated_cost_used_micros"] == 100000
    assert view(db_session, user)["unpriced_requests"] == 0


def test_no_price_blocks_before_admission_when_money_enforced(db_session, monkeypatch):
    user = owner(db_session)
    monkeypatch.setattr(settings, "USAGE_DAILY_COST_LIMIT_MICROS", 1000)
    with pytest.raises(service.ModelBudgetExceededError) as err:
        reserve(db_session, user)
    assert err.value.code == "usage_price_required"
    assert view(db_session, user)["calls_admitted"] == 0


def test_removed_resource_limit_cannot_relax_frozen_day(db_session, monkeypatch):
    user = owner(db_session)
    monkeypatch.setattr(settings, "USAGE_DAILY_UNITS_JSON", '{"documents":1}')
    reserve(db_session, user, units={"requests": 1, "documents": 1})
    monkeypatch.setattr(settings, "USAGE_DAILY_UNITS_JSON", "{}")
    with pytest.raises(service.ModelBudgetExceededError):
        reserve(db_session, user, name="next", units={"requests": 1, "documents": 1})


def test_rejection_keeps_physical_attempt_units(db_session):
    user = owner(db_session)
    identity = reserve(db_session, user, units={"requests": 1, "external_requests": 1})
    service.settle_identity(
        db_session, user_id=user, identity=identity, outcome="rejected"
    )
    assert view(db_session, user)["units_used"] == {
        "requests": 1,
        "external_requests": 1,
    }


def test_partial_usage_retains_unobserved_resources_and_estimate(
    db_session, monkeypatch
):
    user = owner(db_session)
    monkeypatch.setattr(
        settings,
        "USAGE_RATE_CARD_JSON",
        '{"embedding:fixture:fixture":{"input_tokens":"0.001"}}',
    )
    identity = reserve(
        db_session,
        user,
        units={"requests": 1, "input_tokens": 100, "output_tokens": 0, "documents": 3},
    )
    service.settle_identity(
        db_session,
        user_id=user,
        identity=identity,
        outcome="completed",
        observed_units={"requests": 1, "documents": 3},
    )
    row = db_session.get(ModelBudgetReservation, identity)
    assert row.status == "estimated"
    assert row.observed_tokens == 100
    assert row.cost_observed_micros == 100000


def test_unknown_holds_the_larger_observation_and_across_days_cap(
    db_session, monkeypatch
):
    user = owner(db_session)
    monkeypatch.setattr(settings, "USAGE_MAX_UNRESOLVED", 1)
    identity = reserve(db_session, user)
    service.settle_identity(
        db_session,
        user_id=user,
        identity=identity,
        outcome="unknown",
        observed_tokens=30,
        observed_units={"input_tokens": 30},
    )
    service.settle_identity(
        db_session, user_id=user, identity=identity, outcome="rejected"
    )
    assert view(db_session, user)["tokens_reserved"] == 30
    with pytest.raises(service.ModelBudgetExceededError):
        service.reserve(
            db_session,
            user_id=user,
            turn_id="next-day",
            call_id="1",
            token_allowance=1,
            now=NOW + timedelta(days=1),
        )


def test_operator_correction_is_cas_idempotent_and_preserves_frozen_price(
    db_session, monkeypatch
):
    user = owner(db_session)
    monkeypatch.setattr(
        settings,
        "USAGE_RATE_CARD_JSON",
        '{"embedding:fixture:fixture":{"input_tokens":"0.001"}}',
    )
    identity = reserve(db_session, user)
    service.settle_identity(
        db_session, user_id=user, identity=identity, outcome="unknown"
    )
    data = dict(
        user_id=user,
        receipt_id=identity,
        expected_revision=1,
        request_id="op1",
        operator="ops-fixture",
        evidence_ref="sha256:external-fixture",
        outcome="completed",
        observed_units={"requests": 1, "input_tokens": 5, "output_tokens": 0},
        observed_tokens=5,
        currency="USD",
        invoice_cost_micros=4000,
        quiesced=True,
    )
    saved = reconciliation.reconcile(db_session, **data)
    repeated = reconciliation.reconcile(db_session, **data)
    assert saved.id == repeated.id
    assert db_session.scalar(select(UsageAdjustment.id)) == saved.id
    assert saved.before_json["status"] == "unknown"
    assert saved.after_json["invoice_cost_micros"] == 4000
    row = db_session.get(ModelBudgetReservation, identity)
    assert row.price_snapshot_json["rates"]["input_tokens"] == "0.001"
    assert view(db_session, user)["tokens_used"] == 5
    assert view(db_session, user)["tokens_reserved"] == 0
    assert view(db_session, user)["rated_cost_used_micros"] == 4000
    with pytest.raises(ValueError, match="idempotency"):
        reconciliation.reconcile(db_session, **{**data, "invoice_cost_micros": 0})
    with pytest.raises(ValueError, match="revision"):
        reconciliation.reconcile(db_session, **{**data, "request_id": "op2"})
    # Reconciliation does not create another send permit for the same identity.
    with pytest.raises(ValueError, match="already_exists"):
        reserve(db_session, user)


@pytest.mark.parametrize(
    "change,code",
    [
        ({"quiesced": False}, "quiesce"),
        ({"currency": "CNY"}, "currency"),
        ({"observed_units": {"requests": 0}}, "attempt"),
        ({"invoice_cost_micros": True}, "invoice"),
    ],
)
def test_reconciliation_rejects_unsafe_mutations(db_session, change, code):
    user = owner(db_session)
    identity = reserve(db_session, user)
    data = dict(
        user_id=user,
        receipt_id=identity,
        expected_revision=0,
        request_id="op",
        operator="ops",
        evidence_ref="proof",
        outcome="completed",
        observed_units={"requests": 1, "input_tokens": 0, "output_tokens": 0},
        observed_tokens=0,
        currency="USD",
        invoice_cost_micros=0,
        quiesced=True,
    )
    with pytest.raises(ValueError, match=code):
        reconciliation.reconcile(db_session, **{**data, **change})


def test_history_has_owner_boundary_and_stable_keyset(db_session):
    user = owner(db_session)
    ids = [reserve(db_session, user, name=str(i)) for i in range(3)]
    first = queries.history(db_session, user_id=user, limit=2)
    second = queries.history(
        db_session, user_id=user, before=first["next_cursor"], limit=2
    )
    assert len(first["items"]) == 2 and len(second["items"]) == 1
    assert {r["id"] for r in first["items"] + second["items"]} == set(ids)
    assert queries.history(db_session, user_id=user + 10)["items"] == []
    with pytest.raises(ValueError, match="cursor"):
        queries.history(db_session, user_id=user + 10, before=ids[0])


def test_decimal_rates_round_up_once_without_binary_float():
    card = freeze(
        raw='{"speech:fixture:m":{"characters":"0.000000000001"}}',
        currency="USD",
        meter="speech",
        provider="fixture",
        model="m",
    )
    assert cost_micros(card, {"characters": 3}) == 1
    assert cost_micros(None, {"characters": 3}) is None
    assert cost_micros(card, {"characters": 0}) == 0


@pytest.mark.parametrize("rate", ["NaN", "Infinity", "-1", "1e-100"])
def test_invalid_rates_rejected(rate):
    with pytest.raises(ValueError):
        freeze(
            raw=json.dumps({"m:p:x": {"requests": rate}}),
            currency="USD",
            meter="m",
            provider="p",
            model="x",
        )


def test_cache_buckets_do_not_double_count():
    a = model_units(
        {
            "input_tokens": 10,
            "output_tokens": 4,
            "cache_read_input_tokens": 7,
            "cache_creation_input_tokens": 3,
        },
        anthropic=True,
    )
    b = model_units(
        {
            "prompt_tokens": 20,
            "completion_tokens": 4,
            "prompt_tokens_details": {"cached_tokens": 7},
        }
    )
    assert a == {
        "input_tokens": 10,
        "output_tokens": 4,
        "cache_read_tokens": 7,
        "cache_write_tokens": 3,
        "requests": 1,
    }
    assert b["input_tokens"] == 13 and b["cache_write_tokens"] == 0
    with pytest.raises(ValueError):
        model_units(
            {
                "prompt_tokens": 1,
                "completion_tokens": 2,
                "prompt_tokens_details": {"cached_tokens": 3},
            }
        )
    with pytest.raises(ValueError):
        quantities({"requests": True})


def test_admitted_tightening_of_policy_is_durable(db_session, monkeypatch):
    user = owner(db_session)
    monkeypatch.setattr(settings, "MODEL_DAILY_CALL_LIMIT", 10)
    monkeypatch.setattr(settings, "USAGE_DAILY_COST_LIMIT_MICROS", None)
    monkeypatch.setattr(
        settings,
        "USAGE_RATE_CARD_JSON",
        '{"embedding:fixture:fixture":{"requests":"0.01"}}',
    )
    reserve(db_session, user, name="one")
    monkeypatch.setattr(settings, "MODEL_DAILY_CALL_LIMIT", 2)
    monkeypatch.setattr(settings, "USAGE_DAILY_COST_LIMIT_MICROS", 30000)
    reserve(db_session, user, name="two")
    monkeypatch.setattr(settings, "MODEL_DAILY_CALL_LIMIT", 100)
    monkeypatch.setattr(settings, "USAGE_DAILY_COST_LIMIT_MICROS", None)
    with pytest.raises(service.ModelBudgetExceededError):
        reserve(db_session, user, name="three")
    assert view(db_session, user)["call_limit"] == 2
    assert view(db_session, user)["cost_limit_micros"] == 30000
