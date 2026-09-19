"""Final accounting invariants; tests use production settlement, not a replica."""

from datetime import UTC, datetime
from pathlib import Path
import ast

import pytest
from sqlalchemy import text
from sqlalchemy.dialects import postgresql

from app.core.config import settings
from app.models.model_budget import ModelBudgetReservation, ModelBudgetWindow
from app.models.user import User
from app.usage import service, reconciliation

NOW = datetime(2026, 9, 19, tzinfo=UTC)


def _reserve(db):
    user = User(username="closeout-owner", hashed_password="fixture")
    db.add(user)
    db.flush()
    identity = service.reserve(
        db,
        user_id=user.id,
        turn_id="closeout",
        call_id="one",
        token_allowance=10,
        meter="embedding",
        provider="fixture",
        model="fixture",
        units={"requests": 1, "input_tokens": 10, "output_tokens": 0},
        now=NOW,
    )
    return user.id, identity


@pytest.mark.parametrize("count", [0, 2])
@pytest.mark.parametrize("outcome", ["completed", "unknown", "rejected"])
def test_settlement_never_rewrites_admitted_attempts(db_session, count, outcome):
    uid, receipt = _reserve(db_session)
    with pytest.raises(ValueError, match="settlement_cannot_change_admitted_attempts"):
        service.settle_identity(
            db_session,
            user_id=uid,
            identity=receipt,
            outcome=outcome,
            observed_units={"requests": count},
        )
    row = db_session.get(ModelBudgetReservation, receipt)
    window = db_session.get(ModelBudgetWindow, (uid, NOW.date()))
    assert row.status == "reserved" and row.revision == 0
    assert window.calls_admitted == 1 and window.tokens_reserved == 10
    assert window.units_reserved_json["requests"] == 1


def test_settlement_rejects_inconsistent_logical_and_disjoint_tokens(db_session):
    uid, receipt = _reserve(db_session)
    with pytest.raises(ValueError, match="inconsistent_settlement_token_buckets"):
        service.settle_identity(
            db_session,
            user_id=uid,
            identity=receipt,
            outcome="completed",
            observed_tokens=1,
            observed_units={"requests": 1, "input_tokens": 4, "output_tokens": 6},
        )
    assert db_session.get(ModelBudgetReservation, receipt).status == "reserved"
    service.settle_identity(
        db_session,
        user_id=uid,
        identity=receipt,
        outcome="completed",
        observed_tokens=10,
        observed_units={"requests": 1, "input_tokens": 4, "output_tokens": 6},
    )
    row = db_session.get(ModelBudgetReservation, receipt)
    assert row.status == "settled" and row.observed_tokens == 10


@pytest.mark.parametrize("value", ["false", "true", 0, 1, None, [], {}])
def test_operator_quiescence_is_an_actual_boolean(db_session, value):
    uid, receipt = _reserve(db_session)
    with pytest.raises(ValueError, match="quiesced_requires_boolean_attestation"):
        reconciliation.reconcile(
            db_session,
            user_id=uid,
            receipt_id=receipt,
            expected_revision=0,
            request_id="fix-one",
            operator="fixture",
            evidence_ref="sha256:" + "a" * 64,
            outcome="rejected",
            observed_units={"requests": 1, "input_tokens": 0, "output_tokens": 0},
            observed_tokens=0,
            currency=settings.USAGE_CURRENCY,
            invoice_cost_micros=0,
            quiesced=value,
        )
    assert db_session.get(ModelBudgetReservation, receipt).status == "reserved"


def test_literal_migration_sql_has_no_accidental_bind_parameters():
    """Compile the actual 0052 op.execute strings, including the JSON backfill.

    SQLAlchemy text treats :1 inside a JSON literal as a bind. PostgreSQL
    integration still executes the migration; this fast regression localizes
    the original fault instead of relying only on an empty-database smoke test.
    """
    path = Path(__file__).parents[3] / "alembic/versions/0052_unified_consumption.py"
    source = ast.parse(path.read_text(encoding="utf-8"))
    statements = []
    for node in ast.walk(source):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "op"
            and node.func.attr == "execute"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            statements.append(node.args[0].value)
    assert len(statements) == 4
    for statement in statements:
        compiled = text(statement).compile(dialect=postgresql.dialect())
        assert not compiled.params, (statement, compiled.params)
    # Positive control demonstrates that the regression detects the old error.
    bad = text("UPDATE example SET value = '{\"requests\":1}'::jsonb")
    assert bad.compile(dialect=postgresql.dialect()).params == {"1": None}


@pytest.mark.parametrize("lost_after_commit", [False, True])
@pytest.mark.parametrize("asynchronous", [False, True])
def test_settlement_failure_never_becomes_permission_to_resend(
    usage_scope, monkeypatch, lost_after_commit, asynchronous
):
    import asyncio
    from sqlalchemy import select
    from app.usage import runtime
    from app.core.execution_errors import ModelOutcomeUnknownError
    from app.agent_runtime.retry_utils import classify_api_error, ErrorCategory

    calls = []
    armed = False
    original_commit = usage_scope.class_.commit

    def commit(db):
        if not armed:
            return original_commit(db)
        if lost_after_commit:
            original_commit(db)
        raise OSError("synthetic settlement connection loss")

    monkeypatch.setattr(usage_scope.class_, "commit", commit)

    def provider():
        nonlocal armed
        calls.append("completed")
        armed = True
        return {"input_tokens": 3, "output_tokens": 0, "requests": 1}

    async def async_provider():
        return provider()

    descriptor = dict(
        meter="embedding",
        provider="fixture",
        model="fixture",
        content="synthetic",
        units={"requests": 1, "input_tokens": 10, "output_tokens": 0},
        token_allowance=10,
        observed=lambda result: result,
    )
    with pytest.raises(
        ModelOutcomeUnknownError, match="settlement_unconfirmed"
    ) as error:
        if asynchronous:
            asyncio.run(runtime.invoke_async(async_provider, **descriptor))
        else:
            runtime.invoke_sync(provider, **descriptor)
    assert classify_api_error(error.value) == ErrorCategory.FATAL
    from app.core.error_messages import humanize_error

    rendered = humanize_error(error.value)
    assert "本地用量结算尚未确认" in rendered
    assert "原收据" in rendered and "synthetic" not in rendered
    assert calls == ["completed"]
    with usage_scope() as db:
        row = db.scalar(select(ModelBudgetReservation))
        assert row.status == ("settled" if lost_after_commit else "reserved")
        window = db.get(ModelBudgetWindow, (row.user_id, row.window_date))
        assert window.calls_admitted == 1
        assert window.tokens_reserved == (0 if lost_after_commit else 10)
        assert window.tokens_used == (3 if lost_after_commit else 0)


@pytest.mark.asyncio
async def test_two_account_scopes_keep_attribution_across_await_and_thread(
    usage_database,
):
    import asyncio
    from sqlalchemy import select
    from app.usage import runtime

    async def call(uid, name):
        with runtime.scope(uid, f"account-{uid}", username=name):
            await asyncio.sleep(0)
            assert (await asyncio.to_thread(runtime.current)).user_id == uid
            receipt = await runtime.begin_async(
                meter="speech",
                provider="fixture",
                model="fixture",
                content=f"synthetic-{uid}",
                units={"requests": 1, "characters": 8},
            )
            await asyncio.sleep(0)
            await runtime.finish_async(
                receipt, "completed", {"requests": 1, "characters": 8}
            )
            assert runtime.current().user_id == uid
            return receipt.identity

    identities = await asyncio.gather(call(1, "alice"), call(2, "bob"))
    assert len(set(identities)) == 2
    with pytest.raises(RuntimeError, match="consumption_owner_missing"):
        runtime.current()
    with usage_database() as db:
        rows = db.scalars(select(ModelBudgetReservation)).all()
        assert {r.user_id for r in rows} == {1, 2}
        assert all(
            r.status == "settled" and r.observed_units_json["characters"] == 8
            for r in rows
        )


def test_unexpected_attempt_dimension_is_not_provider_controlled(db_session):
    uid, receipt = _reserve(db_session)
    for key in ("external_requests", "tool_invocations"):
        with pytest.raises(
            ValueError, match="settlement_cannot_change_admitted_attempts"
        ):
            service.settle_identity(
                db_session,
                user_id=uid,
                identity=receipt,
                outcome="completed",
                observed_units={key: 1},
            )
    assert db_session.get(ModelBudgetReservation, receipt).status == "reserved"
