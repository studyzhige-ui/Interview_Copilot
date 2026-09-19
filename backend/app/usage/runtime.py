"""Short-transaction accounting around real work, with explicit attribution.

Context carries only trusted owner/operation identity, never a DB Session.
Threads receive copies; worker entry points must restore it from owned rows.
No context means no billable dispatch, not an unmetered platform fallback.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from threading import Lock
from typing import Any, Callable

from app.core.config import settings
from app.core.execution_errors import ModelOutcomeUnknownError
from app.core.provider_usage import accumulate, ledger_units
from sqlalchemy import select
from app.db.database import SessionLocal
from app.usage import service
from app.usage.pricing import model_units, quantities


@dataclass
class ConsumptionScope:
    user_id: int
    operation_id: str
    username: str | None = None
    counters: dict[str, int] = field(default_factory=dict)
    lock: Lock = field(default_factory=Lock)

    def call_id(self, fingerprint: str) -> str:
        with self.lock:
            ordinal = self.counters.get(fingerprint, 0)
            self.counters[fingerprint] = ordinal + 1
        return f"{fingerprint}:{ordinal}"


_scope: ContextVar[ConsumptionScope | None] = ContextVar(
    "consumption_scope", default=None
)


def bind(user_id: int, operation_id: str, *, username: str | None = None):
    if type(user_id) is not int or user_id <= 0 or not operation_id:
        raise ValueError("invalid_consumption_scope")
    return _scope.set(ConsumptionScope(user_id, operation_id, username=username))


def reset(token) -> None:
    _scope.reset(token)


def current() -> ConsumptionScope:
    value = _scope.get()
    if value is None:
        raise RuntimeError(
            "consumption_owner_missing: authenticated request or owned worker scope required"
        )
    return value


@contextmanager
def scope(user_id: int, operation_id: str, *, username: str | None = None):
    token = bind(user_id, operation_id, username=username)
    try:
        yield current()
    finally:
        reset(token)


@contextmanager
def for_owner(user_id: int, *, operation: str, username: str | None = None):
    """Use an already authorized numeric owner; never switch an active account.

    The caller obtains this ID from canonical business data or authentication,
    not arbitrary request metadata. No Session is retained in the scope.
    """
    if type(user_id) is not int or user_id <= 0 or not operation:
        raise ValueError("invalid_consumption_scope")
    active = _scope.get()
    if active is not None:
        if active.user_id != user_id:
            raise ValueError("consumption_owner_mismatch")
        yield active
    else:
        with scope(
            user_id, f"{operation}:{uuid.uuid4().hex}", username=username
        ) as actor:
            yield actor


@contextmanager
def for_username(username: str | None):
    active = _scope.get()
    if active is not None:
        if username and active.username != username:
            from app.models.user import User

            with SessionLocal() as db:
                actual = db.scalar(
                    select(User.username).where(User.id == active.user_id)
                )
            if actual != username:
                raise ValueError("consumption_owner_mismatch")
        yield active
        return
    if not username:
        raise RuntimeError("consumption_owner_missing")
    from app.models.user import User

    with SessionLocal() as db:
        owner = db.scalar(select(User.id).where(User.username == username))
    if owner is None:
        raise RuntimeError("consumption_owner_not_found")
    with scope(int(owner), f"direct:{uuid.uuid4().hex}") as value:
        yield value


def fingerprint(meter: str, provider: str, model: str, content: Any) -> str:
    raw = json.dumps(
        [meter, provider, model, content],
        ensure_ascii=False,
        sort_keys=True,
        default=str,
        allow_nan=False,
    )
    return hmac.new(
        settings.SECRET_KEY.encode(), ("usage-v1\0" + raw).encode(), hashlib.sha256
    ).hexdigest()


@dataclass(frozen=True)
class Receipt:
    user_id: int
    identity: str


def begin(
    *,
    meter: str,
    provider: str,
    model: str,
    content: Any,
    units: dict[str, int],
    token_allowance: int = 0,
) -> Receipt:
    actor = current()
    digest = fingerprint(meter, provider, model, content)
    call_id = actor.call_id(digest)
    with SessionLocal() as db:
        identity = service.reserve(
            db,
            user_id=actor.user_id,
            turn_id=actor.operation_id,
            call_id=call_id,
            token_allowance=token_allowance,
            meter=meter,
            provider=provider,
            model=model,
            units=units,
            fingerprint=digest,
        )
        db.commit()
    return Receipt(actor.user_id, identity)


def finish(receipt: Receipt, outcome: str, units: dict | None = None) -> None:
    logical_tokens = (
        None
        if units is None or not {"input_tokens", "output_tokens"}.issubset(units)
        else sum(
            units.get(k, 0)
            for k in (
                "input_tokens",
                "output_tokens",
                "cache_read_tokens",
                "cache_write_tokens",
            )
        )
    )
    with SessionLocal() as db:
        service.settle_identity(
            db,
            user_id=receipt.user_id,
            identity=receipt.identity,
            outcome=outcome,
            observed_tokens=logical_tokens,
            observed_units=units,
        )
        db.commit()


def failure_outcome(exc: BaseException) -> str:
    status = getattr(exc, "status_code", None)
    response = getattr(exc, "response", None)
    if status is None and response is not None:
        status = getattr(response, "status_code", None)
    return (
        "rejected" if status in {400, 401, 402, 403, 404, 413, 422, 429} else "unknown"
    )


async def begin_async(**kwargs) -> Receipt:
    task = asyncio.create_task(asyncio.to_thread(begin, **kwargs))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        # The admission transaction may have committed. No request was sent;
        # do not leak a reservation simply because its waiter was cancelled.
        receipt = await task
        await asyncio.shield(asyncio.to_thread(finish, receipt, "rejected"))
        raise


async def finish_async(receipt, outcome, units=None):
    task = asyncio.create_task(asyncio.to_thread(finish, receipt, outcome, units))
    try:
        await asyncio.shield(task)
    except asyncio.CancelledError:
        await task
        raise


def invoke_sync(call: Callable, *, observed: Callable | None = None, **descriptor):
    receipt = begin(**descriptor)
    try:
        result = call()
    except BaseException as exc:
        outcome = failure_outcome(exc)
        finish(receipt, outcome)
        if outcome == "unknown" and isinstance(exc, Exception):
            raise ModelOutcomeUnknownError("consumption_outcome_unknown") from exc
        raise
    # Result/usage parsing errors after dispatch do not release the allowance.
    try:
        units = observed(result) if observed is not None else None
    except Exception:
        finish(receipt, "completed")
        raise
    finish(receipt, "completed", units)
    return result


async def invoke_async(
    call: Callable, *, observed: Callable | None = None, **descriptor
):
    receipt = await begin_async(**descriptor)
    try:
        async with asyncio.timeout(settings.MODEL_STREAM_DEADLINE_SECONDS):
            result = await call()
    except BaseException as exc:
        outcome = failure_outcome(exc)
        await finish_async(receipt, outcome)
        if outcome == "unknown" and isinstance(exc, Exception):
            raise ModelOutcomeUnknownError("consumption_outcome_unknown") from exc
        raise
    try:
        units = observed(result) if observed is not None else None
    except Exception:
        await finish_async(receipt, "completed")
        raise
    await finish_async(receipt, "completed", units)
    return result


def llm_allowance(prompt: Any, max_tokens: int) -> tuple[dict, int]:
    encoded = json.dumps(prompt, ensure_ascii=False, default=str).encode()
    # UTF-8 byte bound deliberately conservative, not a claim of actual usage.
    amount = len(encoded) + 1024
    values = quantities(
        {
            "input_tokens": amount,
            "output_tokens": max_tokens,
            "cache_read_tokens": amount,
            "cache_write_tokens": amount,
            "requests": 1,
        }
    )
    return values, amount + max_tokens


def completion_usage(result) -> dict | None:
    raw = getattr(result, "raw", result)
    usage = raw.get("usage") if isinstance(raw, dict) else getattr(raw, "usage", None)
    native = (
        ("input_tokens" in usage)
        if isinstance(usage, dict)
        else hasattr(usage, "input_tokens")
    )
    return model_units(usage, anthropic=native)


class MeteredLLM:
    """Compatibility completion interface; no second model-selection engine."""

    def __init__(self, inner, profile, meter: str, username=None):
        self._inner, self._profile, self._meter, self._username = (
            inner,
            profile,
            meter,
            username,
        )

    def __getattr__(self, name):
        if name in {
            "chat",
            "achat",
            "stream_chat",
            "astream_chat",
            "stream_complete",
            "astream_complete",
        }:
            raise AttributeError(
                "unmetered_completion_method_forbidden: use complete/acomplete or the native streaming adapter"
            )
        return getattr(self._inner, name)

    def _descriptor(self, prompt, kwargs):
        maximum = kwargs.get("max_tokens") or self._profile.max_output_tokens or 4096
        units, tokens = llm_allowance(
            {"prompt": prompt, "kwargs": kwargs}, int(maximum)
        )
        return dict(
            meter=self._meter,
            provider=self._profile.provider,
            model=self._profile.model,
            content={"prompt": prompt, "kwargs": kwargs},
            units=units,
            token_allowance=tokens,
        )

    def complete(self, prompt, **kwargs):
        with for_username(self._username):
            return invoke_sync(
                lambda: self._inner.complete(prompt, **kwargs),
                observed=completion_usage,
                **self._descriptor(prompt, kwargs),
            )

    async def acomplete(self, prompt, **kwargs):
        with for_username(self._username):
            return await invoke_async(
                lambda: self._inner.acomplete(prompt, **kwargs),
                observed=completion_usage,
                **self._descriptor(prompt, kwargs),
            )


class MeteredStream:
    """Owns the receipt from connection start through stream exhaustion/close."""

    def __init__(self, stream, receipt, deadline):
        self.stream, self.iterator, self.receipt = stream, stream.__aiter__(), receipt
        self.deadline, self.bytes, self.usage, self.closed = deadline, 0, {}, False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.closed:
            raise StopAsyncIteration
        try:
            remaining = self.deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise TimeoutError("metered_stream_deadline")
            event = await asyncio.wait_for(anext(self.iterator), remaining)
            self.bytes += len(str(event).encode())
            if self.bytes > settings.MODEL_STREAM_MAX_BYTES:
                raise ValueError("metered_stream_capacity")
            usage = getattr(event, "usage", None)
            if usage is not None:
                accumulate(self.usage, usage)
            return event
        except StopAsyncIteration:
            values = ledger_units(self.usage)
            self.closed = True
            try:
                await finish_async(self.receipt, "completed", values)
            finally:
                from app.core.provider_streams import close_provider_stream

                await close_provider_stream(self.stream)
            raise
        except BaseException:
            await self.aclose()
            raise

    async def aclose(self):
        if self.closed:
            return
        self.closed = True
        try:
            await finish_async(self.receipt, "unknown")
        finally:
            from app.core.provider_streams import close_provider_stream

            await close_provider_stream(self.stream)


async def start_stream(call, **descriptor):
    deadline = (
        asyncio.get_running_loop().time() + settings.MODEL_STREAM_DEADLINE_SECONDS
    )
    receipt = await begin_async(**descriptor)
    try:
        stream = await asyncio.wait_for(
            call(), max(0.001, deadline - asyncio.get_running_loop().time())
        )
    except BaseException as exc:
        outcome = failure_outcome(exc)
        await finish_async(receipt, outcome)
        if outcome == "unknown" and isinstance(exc, Exception):
            raise ModelOutcomeUnknownError("consumption_outcome_unknown") from exc
        raise
    return MeteredStream(stream, receipt, deadline)


def claim_primary(request, profile) -> None:
    """Consume a primary transport permit exactly once, before network I/O."""
    from sqlalchemy import update
    from app.models.model_budget import ModelBudgetReservation
    from app.core.model_request_identity import request_fingerprint
    from app.db.types import utc_now

    actor = current()
    digest = request_fingerprint(
        messages=request.messages,
        tools=request.tools,
        system=request.system,
        max_tokens=request.max_tokens,
        temperature=request.temperature,
    )
    with SessionLocal() as db:
        changed = db.execute(
            update(ModelBudgetReservation)
            .where(
                ModelBudgetReservation.id == request.usage_permit,
                ModelBudgetReservation.user_id == actor.user_id,
                ModelBudgetReservation.status == "reserved",
                ModelBudgetReservation.meter == "primary",
                ModelBudgetReservation.provider == profile.provider,
                ModelBudgetReservation.model == profile.model,
                ModelBudgetReservation.request_fingerprint == digest,
                ModelBudgetReservation.transport_claimed_at.is_(None),
            )
            .values(transport_claimed_at=utc_now())
        ).rowcount
        if changed != 1:
            raise RuntimeError("primary_transport_permit_unavailable")
        db.commit()


def provider_reference(receipt: Receipt, provider_request_id: str) -> None:
    """Persist an upstream receipt for later reconciliation, never a prompt."""
    from app.models.model_budget import ModelBudgetReservation

    if (
        not isinstance(provider_request_id, str)
        or not 1 <= len(provider_request_id) <= 255
    ):
        raise ValueError("invalid_provider_request_identity")
    with SessionLocal() as db:
        service._lock_account(db, receipt.user_id)
        row = db.get(ModelBudgetReservation, receipt.identity, with_for_update=True)
        if row is None or row.user_id != receipt.user_id:
            raise ValueError("unknown_usage_receipt")
        if row.provider_request_id not in (None, provider_request_id):
            raise ValueError("provider_request_identity_conflict")
        row.provider_request_id = provider_request_id
        db.commit()
