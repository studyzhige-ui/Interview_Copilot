"""Resources are owned by one event loop, never by the importing process."""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RuntimeResources:
    redis: dict[str, Any] = field(default_factory=dict)
    openai: OrderedDict = field(default_factory=OrderedDict)
    anthropic: OrderedDict = field(default_factory=OrderedDict)
    llms: OrderedDict = field(default_factory=OrderedDict)
    closing: set[asyncio.Task] = field(default_factory=set)

    def retire(self, client: Any) -> None:
        task = asyncio.create_task(_close(client))
        self.closing.add(task)

        def finished(task):
            self.closing.discard(task)
            if not task.cancelled() and task.exception() is not None:
                logging.getLogger(__name__).warning(
                    "Resource close failed: %s", type(task.exception()).__name__
                )

        task.add_done_callback(finished)


def current_resources() -> RuntimeResources:
    loop = asyncio.get_running_loop()
    resources = getattr(loop, "_interview_resources", None)
    if resources is None:
        resources = RuntimeResources()
        loop._interview_resources = resources
    return resources


async def _close(client: Any) -> None:
    # LlamaIndex wrappers own both sync and async clients.
    if hasattr(client, "_get_aclient"):
        await _close(client._get_aclient())
        await _close(client._get_client())
        return
    close = getattr(client, "aclose", None) or getattr(client, "close", None)
    if close is not None:
        result = close()
        if inspect.isawaitable(result):
            await result


async def close_current_resources() -> None:
    loop = asyncio.get_running_loop()
    resources = getattr(loop, "_interview_resources", None)
    if resources is None:
        return
    clients = list(resources.redis.values())
    for cache in (resources.openai, resources.anthropic, resources.llms):
        clients.extend(entry[1] for entry in cache.values())
        cache.clear()
    resources.redis.clear()
    try:
        results = await asyncio.gather(
            *(_close(client) for client in clients), return_exceptions=True
        )
        for result in results:
            if isinstance(result, BaseException):
                logging.getLogger(__name__).warning(
                    "Resource close failed: %s", type(result).__name__
                )
    finally:
        if resources.closing:
            await asyncio.gather(*resources.closing, return_exceptions=True)
        delattr(loop, "_interview_resources")
