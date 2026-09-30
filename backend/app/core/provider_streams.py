"""Bounded transport cleanup; independent of model selection or accounting."""

import asyncio
import inspect
import logging
from typing import Any


async def close_provider_stream(stream: Any) -> None:
    """Close native HTTP response ownership even when a wrapper is cancelled.

    Cleanup has its own short bound and never changes a settled paid outcome.
    Error values/headers may contain secrets, so log only the exception type.
    """
    close = getattr(stream, "aclose", None) or getattr(stream, "close", None)
    if not callable(close):
        return
    try:
        result = close()
        if inspect.isawaitable(result):
            await asyncio.wait_for(result, timeout=5.0)
    except Exception as exc:
        logging.getLogger(__name__).warning(
            "Provider stream close failed (%s)", type(exc).__name__
        )
