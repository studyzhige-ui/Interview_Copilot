"""Mandatory in CI: unified account locks, history and expansion migration.

Fresh PostgreSQL only; no production credentials, provider network or old-user
content. Tests do not treat a SQLite lock approximation as PostgreSQL proof.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
import hashlib
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
                    "INSERT INTO users (username,hashed_password,email_verified,is_active,created_at,updated_at) VALUES ('upgrade-user','fixture',false,true,:now,:now) RETURNING id"
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


def test_upgrade_preserves_each_old_state_owner_day_and_reconciles_in_place(
    fresh_pg_db,  # noqa: F811
):
    """Old settled/estimated/rejected/unknown/reserved rows must remain usable.

    Reflect the *old* schema: using current accounting ORM inserts before the
    migration could accidentally require new columns and hide a real upgrade.
    """
    from sqlalchemy import MetaData, Table

    config = _make_alembic_config(fresh_pg_db)
    command.upgrade(config, "0051")
    engine = create_engine(fresh_pg_db)
    ids = {}
    old_states = (
        ("reserved", 11, 0),
        ("unknown", 17, 5),
        ("settled", 23, 19),
        ("estimated", 29, 29),
        ("rejected", 31, 0),
    )
    days = (NOW.date() - timedelta(days=1), NOW.date())
    try:
        metadata = MetaData()
        users = Table("users", metadata, autoload_with=engine)
        windows = Table("model_budget_windows", metadata, autoload_with=engine)
        receipts = Table("model_budget_reservations", metadata, autoload_with=engine)
        with engine.begin() as db:
            owners = [
                db.execute(
                    users.insert()
                    .values(
                        username=f"migration-owner-{index}",
                        hashed_password="fixture",
                        email_verified=False,
                        is_active=True,
                        created_at=NOW,
                        updated_at=NOW,
                    )
                    .returning(users.c.id)
                ).scalar_one()
                for index in range(3)
            ]
            for uid in owners[:2]:
                for day in days:
                    db.execute(
                        windows.insert().values(
                            user_id=uid,
                            window_date=day,
                            call_limit=500,
                            token_limit=2_000_000,
                            calls_admitted=5,
                            tokens_used=48,
                            tokens_reserved=28,
                            created_at=NOW,
                        )
                    )
                    for status, reserved, observed in old_states:
                        identity = hashlib.sha256(
                            f"{uid}:{day}:{status}".encode()
                        ).hexdigest()
                        ids[uid, day, status] = identity
                        db.execute(
                            receipts.insert().values(
                                id=identity,
                                user_id=uid,
                                window_date=day,
                                reserved_tokens=reserved,
                                observed_tokens=observed,
                                status=status,
                                created_at=NOW,
                                settled_at=NOW
                                if status in {"settled", "estimated", "rejected"}
                                else None,
                                reconciliation_ref="fixture:original"
                                if status == "settled"
                                else None,
                            )
                        )
            before_windows = [
                dict(r)
                for r in db.execute(
                    select(windows).order_by(windows.c.user_id, windows.c.window_date)
                ).mappings()
            ]
            before_receipts = [
                dict(r)
                for r in db.execute(select(receipts).order_by(receipts.c.id)).mappings()
            ]
        command.upgrade(config, "head")
        command.check(config)
        with engine.connect() as db:
            assert [
                dict(r)
                for r in db.execute(
                    select(windows).order_by(windows.c.user_id, windows.c.window_date)
                ).mappings()
            ] == before_windows
            assert [
                dict(r)
                for r in db.execute(select(receipts).order_by(receipts.c.id)).mappings()
            ] == before_receipts
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        with factory() as db:
            assert (
                db.query(UsageAccount).count() == 3
            )  # include a user with no past calls
            assert db.query(ModelBudgetReservation).count() == 20
            for row in db.scalars(select(ModelBudgetReservation)):
                assert row.meter == "primary" and row.revision == 0
                assert row.provider is None and row.model is None
                assert (
                    row.price_snapshot_json is None and row.cost_observed_micros is None
                )
                assert row.reserved_units_json == {"requests": 1}
                expected = (
                    None if row.status in {"reserved", "unknown"} else {"requests": 1}
                )
                assert row.observed_units_json == expected
            for window in db.scalars(select(ModelBudgetWindow)):
                assert window.units_reserved_json == {"requests": 2}
                assert window.units_used_json == {"requests": 3}
                assert window.cost_reserved_micros == window.cost_used_micros == 0
            uid, day = owners[0], days[0]
            identity = ids[uid, day, "unknown"]
            reconciliation.reconcile(
                db,
                user_id=uid,
                receipt_id=identity,
                expected_revision=0,
                request_id="after-upgrade",
                operator="fixture",
                evidence_ref="sha256:" + "c" * 64,
                outcome="completed",
                observed_units={"requests": 1},
                observed_tokens=7,
                currency="USD",
                invoice_cost_micros=500,
                quiesced=True,
            )
            db.commit()
            window = db.get(ModelBudgetWindow, (uid, day))
            assert (
                window.calls_admitted,
                window.tokens_used,
                window.tokens_reserved,
            ) == (5, 55, 11)
            assert (window.cost_used_micros, window.cost_reserved_micros) == (500, 0)
            assert window.units_reserved_json == {"requests": 1}
            assert window.units_used_json == {"requests": 4}
            assert db.get(ModelBudgetReservation, identity).price_snapshot_json is None
            assert db.query(UsageAdjustment).count() == 1
            # Another user/day is unchanged, including its uncertain exposure.
            untouched = db.get(ModelBudgetWindow, (owners[1], days[1]))
            assert (
                untouched.calls_admitted,
                untouched.tokens_used,
                untouched.tokens_reserved,
            ) == (5, 48, 28)
        with pytest.raises(RuntimeError, match="rollback_requires"):
            command.downgrade(config, "0051")
        command.check(config)
    finally:
        engine.dispose()


def test_same_call_identity_cannot_be_reused_from_fresh_connection(accounting_db):
    _, factory, uid = accounting_db
    barrier = Barrier(2)

    def execute(_):
        with factory() as db:
            db.execute(text("SET LOCAL lock_timeout = '8s'"))
            barrier.wait(timeout=10)
            try:
                identity = admit(db, uid, "external_tool", name="stable-call")
                db.commit()
                return ("admitted", identity)
            except ValueError as exc:
                assert str(exc) == "model_budget_reservation_already_exists"
                db.rollback()
                return ("denied", None)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(execute, range(2)))
    assert sorted(r[0] for r in results) == ["admitted", "denied"]
    identity = next(r[1] for r in results if r[0] == "admitted")
    with factory() as db:
        service.settle_identity(db, user_id=uid, identity=identity, outcome="unknown")
        db.commit()
    # New transaction / newly-created session simulates a restarted caller. The
    # receipt has no dependency on a live chat object or an in-memory semaphore.
    with factory() as db:
        with pytest.raises(ValueError, match="model_budget_reservation_already_exists"):
            admit(
                db,
                uid,
                "external_tool",
                name="stable-call",
                now=NOW + timedelta(days=1),
            )
        db.rollback()
    with factory() as db:
        assert db.query(ModelBudgetReservation).count() == 1
        row = db.get(ModelBudgetReservation, identity)
        assert row.status == "unknown" and row.window_date == NOW.date()
        assert db.get(ModelBudgetWindow, (uid, NOW.date())).calls_admitted == 1
        assert (
            db.get(ModelBudgetWindow, (uid, (NOW + timedelta(days=1)).date())) is None
        )
