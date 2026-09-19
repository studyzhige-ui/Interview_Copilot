"""Accounted outbound connector operations, not an implicit HTTP monkeypatch.

OAuth bootstrap/refresh/revocation and provider catalog discovery are control
plane operations, not model/tool billable consumption. Resource calls use this
boundary after authorization. Opaque MCP tools use invocation tariffs because
this application cannot observe a remote server's internal requests.
"""

from __future__ import annotations

from contextlib import asynccontextmanager, contextmanager
import uuid
import asyncio
from app.core.config import settings
from app.usage import runtime


@contextmanager
def owned_scope(user_id: int):
    active = runtime._scope.get()
    if active is not None:
        if active.user_id != user_id:
            raise ValueError("connector_consumption_owner_mismatch")
        yield active
    else:
        with runtime.scope(user_id, f"connector:{uuid.uuid4().hex}") as actor:
            yield actor


async def request(
    send, *, provider: str, operation: str, content, owner: int | None = None
):
    async def execute():
        receipt = await runtime.begin_async(
            meter="external_request",
            provider=provider,
            model=operation,
            content=content,
            units={"requests": 1, "external_requests": 1},
        )
        try:
            async with asyncio.timeout(settings.MODEL_STREAM_DEADLINE_SECONDS):
                response = await send()
        except BaseException as exc:
            await runtime.finish_async(receipt, runtime.failure_outcome(exc))
            raise
        status = getattr(response, "status_code", 200)
        outcome = (
            "unknown"
            if status >= 500 or status == 408
            else "rejected"
            if status >= 400
            else "completed"
        )
        await runtime.finish_async(
            receipt, outcome, {"requests": 1, "external_requests": 1}
        )
        return response

    if owner is None:
        return await execute()
    with owned_scope(owner):
        return await execute()


@asynccontextmanager
async def stream(
    open_response, *, provider: str, operation: str, content, max_bytes: int
):
    receipt = await runtime.begin_async(
        meter="external_request",
        provider=provider,
        model=operation,
        content=content,
        units={"requests": 1, "external_requests": 1, "bytes": max_bytes},
    )
    try:
        async with (
            asyncio.timeout(settings.MODEL_STREAM_DEADLINE_SECONDS),
            open_response() as response,
        ):
            yield response
            status = response.status_code
            outcome = (
                "unknown"
                if status >= 500 or status == 408
                else "rejected"
                if status >= 400
                else "completed"
            )
            measured = {"requests": 1, "external_requests": 1}
            size = getattr(response, "num_bytes_downloaded", None)
            if type(size) is int:
                measured["bytes"] = size
    except BaseException as exc:
        await runtime.finish_async(receipt, runtime.failure_outcome(exc))
        raise
    # Transport and response cleanup have finished. A settlement COMMIT failure
    # is not a network failure and must not enter the transport recovery branch.
    await runtime.finish_async(receipt, outcome, measured)
