"""Mandatory in CI: unified account locks, history and expansion migration.

Fresh PostgreSQL only; no production credentials, provider network or old-user
content. Tests do not treat a SQLite lock approximation as PostgreSQL proof.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker
from alembic import command

from app.core.config import settings
from app.models.user import User
from app.models.model_budget import (
    UsageAccount,
    ModelBudgetReservation,
    ModelBudgetWindow,
    UsageAdjustment,
)
from app.usage import service, reconciliation
from tests.test_db.test_alembic_migrations import fresh_pg_db, _make_alembic_config  # noqa: F401

NOW = datetime(2026, 9, 19, tzinfo=UTC)


@pytest.fixture
def accounting_db(fresh_pg_db):  # noqa: F811
    config = _make_alembic_config(fresh_pg_db)
    command.upgrade(config, "head")
    engine = create_engine(fresh_pg_db)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        user = User(username="meter-owner", hashed_password="fixture")
        db.add(user)
        db.flush()
        db.add(UsageAccount(user_id=user.id))
        db.commit()
        uid = user.id
    try:
        yield config, factory, uid
    finally:
        engine.dispose()


def admit(db, uid, meter, name="one", now=NOW):
    return service.reserve(
        db,
        user_id=uid,
        turn_id="unified-concurrency",
        call_id=name,
        token_allowance=0,
        meter=meter,
        provider="fixture",
        model="fixture",
        units={"requests": 1},
        now=now,
    )


def test_last_money_allowance_is_shared_across_categories(accounting_db, monkeypatch):
    _, factory, uid = accounting_db
    monkeypatch.setattr(
        settings,
        "USAGE_RATE_CARD_JSON",
        '{"speech:fixture:fixture":{"requests":"0.01"},"embedding:fixture:fixture":{"requests":"0.01"}}',
    )
    monkeypatch.setattr(settings, "USAGE_DAILY_COST_LIMIT_MICROS", 10000)
    barrier = Barrier(2)

    def execute(meter):
        with factory() as db:
            db.execute(text("SET LOCAL lock_timeout = '8s'"))
            barrier.wait(timeout=10)
            try:
                admit(db, uid, meter, name=meter)
                db.commit()
                return "admitted"
            except service.ModelBudgetExceededError:
                db.rollback()
                return "denied"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(execute, ["speech", "embedding"])) == [
            "admitted",
            "denied",
        ]
    with factory() as db:
        window = db.query(ModelBudgetWindow).one()
        assert (window.calls_admitted, window.cost_reserved_micros) == (1, 10000)
        assert db.query(ModelBudgetReservation).count() == 1


def test_accounting_does_not_wait_for_business_user_lock(accounting_db):
    _, factory, uid = accounting_db
    with factory() as business:
        business.execute(
            select(User).where(User.id == uid).with_for_update()
        ).scalar_one()

        def bill():
            with factory() as accounting:
                accounting.execute(text("SET LOCAL lock_timeout = '2s'"))
                receipt = admit(accounting, uid, "speech")
                accounting.commit()
                return receipt

        with ThreadPoolExecutor(max_workers=1) as pool:
            identity = pool.submit(bill).result(timeout=6)
        # The business lock is intentionally still held when admission returns.
        assert identity
        business.rollback()


def test_operator_reconciliation_is_atomic_cas_and_keeps_history(
    accounting_db, monkeypatch
):
    _, factory, uid = accounting_db
    with factory() as db:
        receipt = admit(db, uid, "speech")
        service.settle_identity(db, user_id=uid, identity=receipt, outcome="unknown")
        db.commit()
        revision = db.get(ModelBudgetReservation, receipt).revision
    barrier = Barrier(2)

    def correct(index):
        with factory() as db:
            barrier.wait(timeout=10)
            try:
                reconciliation.reconcile(
                    db,
                    user_id=uid,
                    receipt_id=receipt,
                    expected_revision=revision,
                    request_id=f"operator-{index}",
                    operator="fixture",
                    evidence_ref="sha256:" + "a" * 64,
                    outcome="completed",
                    observed_units={"requests": 1},
                    observed_tokens=0,
                    currency="USD",
                    invoice_cost_micros=4000,
                    quiesced=True,
                )
                db.commit()
                return "applied"
            except ValueError as exc:
                db.rollback()
                return str(exc)

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(correct, [1, 2])) == [
            "applied",
            "usage_receipt_revision_changed",
        ]
    with factory() as db:
        assert db.query(UsageAdjustment).count() == 1
        row = db.get(ModelBudgetReservation, receipt)
        window = db.query(ModelBudgetWindow).one()
        assert row.status == "settled" and row.invoice_cost_micros == 4000
        assert window.cost_reserved_micros == 0 and window.cost_used_micros == 4000
        assert window.calls_admitted == 1  # corrections are not a new provider call


def test_0052_preserves_old_balances_and_rejects_destructive_rollback(fresh_pg_db):  # noqa: F811
    config = _make_alembic_config(fresh_pg_db)
    command.upgrade(config, "0051")
    engine = create_engine(fresh_pg_db)
    try:
        with engine.begin() as db:
            uid = db.execute(
                text(
                    "INSERT INTO users (username,hashed_password,created_at) VALUES ('upgrade-user','fixture',:now) RETURNING id"
                ),
                {"now": NOW},
            ).scalar_one()
            db.execute(
                text(
                    "INSERT INTO model_budget_windows (user_id,window_date,call_limit,token_limit,calls_admitted,tokens_used,tokens_reserved,created_at) VALUES (:uid,:day,500,2000000,2,17,4,:now)"
                ),
                {"uid": uid, "day": NOW.date(), "now": NOW},
            )
            db.execute(
                text(
                    "INSERT INTO model_budget_reservations (id,user_id,window_date,reserved_tokens,observed_tokens,status,created_at) VALUES (:id,:uid,:day,4,0,'unknown',:now)"
                ),
                {"id": "a" * 64, "uid": uid, "day": NOW.date(), "now": NOW},
            )
        command.upgrade(config, "head")
        command.check(config)
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        with factory() as db:
            assert db.get(UsageAccount, uid) is not None
            window = db.get(ModelBudgetWindow, (uid, NOW.date()))
            assert (
                window.calls_admitted,
                window.tokens_used,
                window.tokens_reserved,
            ) == (2, 17, 4)
            assert db.get(ModelBudgetReservation, "a" * 64).status == "unknown"
        command.downgrade(config, "0051")
        command.upgrade(config, "head")
        with factory() as db:
            identity = admit(db, uid, "embedding")
            db.commit()
        with pytest.raises(RuntimeError, match="rollback_requires"):
            command.downgrade(config, "0051")
        with factory() as db:
            assert db.get(ModelBudgetReservation, identity).meter == "embedding"
            assert db.get(ModelBudgetReservation, "a" * 64).status == "unknown"
            assert db.get(ModelBudgetWindow, (uid, NOW.date())).tokens_used == 17
        command.check(config)
    finally:
        engine.dispose()
