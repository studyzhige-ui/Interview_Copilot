"""Accounting invariants, not a quality benchmark or a provider invoice."""

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.agent_runtime.retry_utils import ErrorCategory, classify_api_error
from app.core.config import settings
from app.models.model_budget import ModelBudgetReservation
from app.models.model_dispatch import AgentModelDispatch
from app.models.user import User
from app.services.chat import model_budget_service as budget
from app.services.chat import model_dispatch_service as dispatch
from tests.conftest import patch_session_locals
from tests.test_services.chat.test_model_dispatch_service import _turn

NOW = datetime(2026, 9, 19, 12, tzinfo=UTC)


def owner(db):
    row = User(username="account-budget", hashed_password="x")
    db.add(row)
    db.flush()
    return row.id


def test_account_limit_spans_conversations_and_survives_new_session(
    db_session, monkeypatch
):
    user_id = owner(db_session)
    monkeypatch.setattr(settings, "MODEL_DAILY_CALL_LIMIT", 2)
    monkeypatch.setattr(settings, "MODEL_DAILY_TOKEN_LIMIT", 100)
    for n in range(2):
        budget.reserve(
            db_session,
            user_id=user_id,
            turn_id=f"different-turn-{n}",
            call_id="1",
            token_allowance=30,
            now=NOW,
        )
    db_session.commit()
    db_session.expire_all()
    with pytest.raises(budget.ModelBudgetExceededError):
        budget.reserve(
            db_session,
            user_id=user_id,
            turn_id="new-conversation",
            call_id="1",
            token_allowance=1,
            now=NOW,
        )
    view = budget.usage_view(db_session, user_id=user_id, now=NOW)
    assert view["calls_admitted"] == 2
    assert view["tokens_reserved"] == 60
    assert view["scope"] == "primary_chat_agent"
    # This ledger contains no FK to Turn/Conversation and no prompt content.
    assert not any(
        fk.target_fullname.startswith(("conversation_turns.", "conversations."))
        for c in ModelBudgetReservation.__table__.columns
        for fk in c.foreign_keys
    )


def test_unknown_retains_allowance_until_evidenced_reconciliation(
    db_session, monkeypatch
):
    user_id = owner(db_session)
    monkeypatch.setattr(settings, "MODEL_DAILY_TOKEN_LIMIT", 100)
    budget.reserve(
        db_session,
        user_id=user_id,
        turn_id="t",
        call_id="c",
        token_allowance=90,
        now=NOW,
    )
    args = dict(user_id=user_id, turn_id="t", call_id="c")
    budget.settle(db_session, **args, outcome="unknown", observed_tokens=2)
    budget.settle(db_session, **args, outcome="rejected", observed_tokens=0)
    assert (
        budget.usage_view(db_session, user_id=user_id, now=NOW)["tokens_reserved"] == 90
    )
    with pytest.raises(budget.ModelBudgetExceededError):
        budget.reserve(
            db_session,
            user_id=user_id,
            turn_id="new",
            call_id="c",
            token_allowance=11,
            now=NOW,
        )
    budget.settle(
        db_session,
        **args,
        outcome="completed",
        observed_tokens=15,
        reconciliation_ref="provider-receipt:test",
    )
    budget.settle(
        db_session,
        **args,
        outcome="completed",
        observed_tokens=15,
        reconciliation_ref="provider-receipt:test",
    )
    view = budget.usage_view(db_session, user_id=user_id, now=NOW)
    assert (view["tokens_used"], view["tokens_reserved"]) == (15, 0)


def test_window_is_utc_and_limits_freeze_for_existing_day(db_session, monkeypatch):
    user_id = owner(db_session)
    monkeypatch.setattr(settings, "MODEL_DAILY_CALL_LIMIT", 1)
    budget.reserve(
        db_session,
        user_id=user_id,
        turn_id="1",
        call_id="c",
        token_allowance=10,
        now=NOW,
    )
    monkeypatch.setattr(settings, "MODEL_DAILY_CALL_LIMIT", 100)
    with pytest.raises(budget.ModelBudgetExceededError):
        budget.reserve(
            db_session,
            user_id=user_id,
            turn_id="2",
            call_id="c",
            token_allowance=10,
            now=NOW,
        )
    budget.reserve(
        db_session,
        user_id=user_id,
        turn_id="2",
        call_id="c",
        token_allowance=10,
        now=NOW + timedelta(days=1),
    )
    assert budget.usage_view(db_session, user_id=user_id, now=NOW)["call_limit"] == 1
    assert (
        budget.usage_view(db_session, user_id=user_id, now=NOW + timedelta(days=1))[
            "calls_admitted"
        ]
        == 1
    )


def test_observation_above_preflight_keeps_debt_not_negative_balance(
    db_session, monkeypatch
):
    user_id = owner(db_session)
    monkeypatch.setattr(settings, "MODEL_DAILY_TOKEN_LIMIT", 50)
    budget.reserve(
        db_session,
        user_id=user_id,
        turn_id="t",
        call_id="c",
        token_allowance=40,
        now=NOW,
    )
    budget.settle(
        db_session,
        user_id=user_id,
        turn_id="t",
        call_id="c",
        outcome="completed",
        observed_tokens=60,
    )
    view = budget.usage_view(db_session, user_id=user_id, now=NOW)
    assert (view["tokens_used"], view["tokens_reserved"]) == (60, 0)
    with pytest.raises(budget.ModelBudgetExceededError):
        budget.reserve(
            db_session,
            user_id=user_id,
            turn_id="2",
            call_id="c",
            token_allowance=1,
            now=NOW,
        )


@pytest.mark.parametrize("allowance", [0, -1, True, 1.5])
def test_invalid_allowance_is_not_admitted(db_session, allowance):
    user_id = owner(db_session)
    with pytest.raises(ValueError):
        budget.reserve(
            db_session,
            user_id=user_id,
            turn_id="t",
            call_id="c",
            token_allowance=allowance,
        )
    assert db_session.query(ModelBudgetReservation).count() == 0


def test_definite_rejection_releases_tokens_but_consumes_retry_call(db_session):
    user_id = owner(db_session)
    budget.reserve(
        db_session,
        user_id=user_id,
        turn_id="t",
        call_id="c",
        token_allowance=40,
        now=NOW,
    )
    budget.settle(
        db_session,
        user_id=user_id,
        turn_id="t",
        call_id="c",
        outcome="rejected",
        observed_tokens=None,
    )
    view = budget.usage_view(db_session, user_id=user_id, now=NOW)
    assert (view["calls_admitted"], view["tokens_used"], view["tokens_reserved"]) == (
        1,
        0,
        0,
    )


def test_usage_unavailable_consumes_estimate_instead_of_zero(db_session):
    user_id = owner(db_session)
    budget.reserve(
        db_session,
        user_id=user_id,
        turn_id="t",
        call_id="c",
        token_allowance=40,
        now=NOW,
    )
    budget.settle(
        db_session,
        user_id=user_id,
        turn_id="t",
        call_id="c",
        outcome="completed",
        observed_tokens=None,
    )
    assert budget.usage_view(db_session, user_id=user_id, now=NOW)["tokens_used"] == 40
    assert db_session.query(ModelBudgetReservation).one().status == "estimated"


def test_identity_and_capacity_failures_cannot_enter_optimistic_retry():
    for exc in [
        budget.ModelBudgetExceededError(),
        dispatch.ModelOutcomeUnknownError(),
        dispatch.ModelDispatchConflictError(),
    ]:
        assert classify_api_error(exc) == ErrorCategory.FATAL
    assert dispatch.dispatch_failure_status(TimeoutError()) == "unknown"
    assert dispatch.dispatch_failure_status(asyncio.CancelledError()) == "unknown"
    refusal = RuntimeError("rate limited")
    refusal.status_code = 429
    assert dispatch.dispatch_failure_status(refusal) == "failed"


def test_fingerprint_includes_system_output_and_sampling():
    base = dict(messages=[{"role": "user", "content": "hello"}], tools=[])
    digest = dispatch.request_fingerprint(
        **base, system="a", max_tokens=10, temperature=0.2
    )
    assert digest != dispatch.request_fingerprint(
        **base, system="b", max_tokens=10, temperature=0.2
    )
    assert digest != dispatch.request_fingerprint(
        **base, system="a", max_tokens=11, temperature=0.2
    )
    assert digest != dispatch.request_fingerprint(
        **base, system="a", max_tokens=10, temperature=0.5
    )


def test_dispatch_and_allowance_commit_together_and_do_not_double_cache_tokens(
    db_session, monkeypatch
):
    patch_session_locals(monkeypatch, db_session, dispatch)
    user, turn = _turn(db_session)
    dispatch.start_model_dispatch(
        db_session,
        user_id=user.id,
        turn_id=turn.id,
        call_id="c",
        dispatch_generation=3,
        provider="test",
        model="test",
        fingerprint="f",
        token_allowance=100,
    )
    dispatch.finish_model_dispatch(
        turn_id=turn.id,
        call_id="c",
        dispatch_generation=3,
        status="completed",
        usage={
            "prompt_tokens": 10,
            "completion_tokens": 3,
            "cache_read_tokens": 5,
            "cache_creation_tokens": 3,
        },
    )
    view = budget.usage_view(db_session, user_id=user.id)
    assert (view["tokens_used"], view["tokens_reserved"]) == (13, 0)
    assert db_session.query(AgentModelDispatch).one().status == "completed"


def test_slow_drip_deadline_does_not_reset_and_closes_stream(monkeypatch):
    monkeypatch.setattr(settings, "MODEL_STREAM_DEADLINE_SECONDS", 0.03)
    closed = []

    async def source():
        try:
            while True:
                await asyncio.sleep(0.004)
                yield SimpleNamespace(text_delta="x", usage=None)
        finally:
            closed.append(True)

    async def run():
        with pytest.raises(TimeoutError):
            async for _ in dispatch.durable_model_stream(
                source(), turn_id=None, call_id=None, dispatch_generation=1
            ):
                pass

    asyncio.run(run())
    assert closed == [True]


def test_stream_overflow_holds_reservation_and_closes(db_session, monkeypatch):
    patch_session_locals(monkeypatch, db_session, dispatch)
    monkeypatch.setattr(settings, "MODEL_STREAM_MAX_BYTES", 100)
    user, turn = _turn(db_session)
    dispatch.start_model_dispatch(
        db_session,
        user_id=user.id,
        turn_id=turn.id,
        call_id="c",
        dispatch_generation=3,
        provider="test",
        model="test",
        fingerprint="f",
        token_allowance=100,
    )
    closed = []

    async def source():
        try:
            yield SimpleNamespace(text_delta="x" * 200, usage=None)
        finally:
            closed.append(True)

    async def run():
        with pytest.raises(dispatch.ModelStreamCapacityError):
            async for _ in dispatch.durable_model_stream(
                source(), turn_id=turn.id, call_id="c", dispatch_generation=3
            ):
                pass

    asyncio.run(run())
    db_session.expire_all()
    assert db_session.query(AgentModelDispatch).one().status == "unknown"
    assert db_session.query(ModelBudgetReservation).one().status == "unknown"
    assert budget.usage_view(db_session, user_id=user.id)["tokens_reserved"] == 100
    assert closed == [True]


@pytest.mark.asyncio
async def test_split_native_usage_is_retained_and_repeated_usage_not_doubled(
    db_session, monkeypatch
):
    from app.core.model_provider_adapter import ProviderStreamEvent, ProviderUsage

    recorded = []
    monkeypatch.setattr(
        dispatch, "finish_model_dispatch", lambda **kwargs: recorded.append(kwargs)
    )

    async def source():
        yield ProviderStreamEvent(
            usage=ProviderUsage(
                prompt_tokens=68, cache_read_tokens=50, cache_creation_tokens=7
            )
        )
        yield ProviderStreamEvent(usage=ProviderUsage(completion_tokens=9))
        yield ProviderStreamEvent(usage=ProviderUsage(completion_tokens=9))

    _ = [
        x
        async for x in dispatch.durable_model_stream(
            source(), turn_id="t", call_id="c", dispatch_generation=1
        )
    ]
    assert recorded[-1]["status"] == "completed"
    assert recorded[-1]["usage"] == {
        "prompt_tokens": 68,
        "completion_tokens": 9,
        "cache_read_tokens": 50,
        "cache_creation_tokens": 7,
    }


@pytest.mark.asyncio
async def test_impossible_provider_usage_is_unknown_not_overflowing(monkeypatch):
    recorded = []
    monkeypatch.setattr(
        dispatch, "finish_model_dispatch", lambda **kwargs: recorded.append(kwargs)
    )

    async def source():
        yield SimpleNamespace(usage=SimpleNamespace(prompt_tokens=2**63 - 1))

    with pytest.raises(dispatch.ModelStreamCapacityError):
        async for _ in dispatch.durable_model_stream(
            source(), turn_id="t", call_id="c", dispatch_generation=1
        ):
            pass
    assert recorded[-1]["status"] == "unknown"
    assert recorded[-1]["usage"] == {}
