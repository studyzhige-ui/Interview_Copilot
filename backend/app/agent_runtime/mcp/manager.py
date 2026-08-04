from __future__ import annotations

import asyncio
import hashlib
import os
import re
import time
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

import httpx

from app.core.config import settings
from app.core.ssrf import validate_safe_url
from app.services.capabilities.mcp_server_service import MCPServerConfig


@dataclass(frozen=True)
class MCPToolDescriptor:
    name: str
    server_id: int
    server_name: str
    remote_name: str
    description: str
    input_schema: dict


@dataclass
class _Request:
    operation: str
    arguments: dict[str, Any]
    future: asyncio.Future[Any]


@dataclass
class _ServerRuntime:
    config: MCPServerConfig
    queue: asyncio.Queue[_Request] = field(default_factory=asyncio.Queue)
    task: asyncio.Task[None] | None = None
    status: str = "connecting"
    last_error: str | None = None
    last_used: float = field(default_factory=time.monotonic)
    tools: list[MCPToolDescriptor] | None = None


def _component(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", value).strip("_") or "tool"


def _tool_name(server: str, remote: str) -> str:
    name = f"mcp__{_component(server)}__{_component(remote)}"
    if len(name) <= 64:
        return name
    digest = hashlib.sha1(name.encode("utf-8")).hexdigest()[:8]
    return f"{name[:55]}_{digest}"


class MCPManager:
    """User+server scoped MCP runtimes backed by one long-lived worker each."""

    def __init__(self) -> None:
        self._runtimes: dict[tuple[int, int], _ServerRuntime] = {}
        self._lock = asyncio.Lock()
        self._reaper_task: asyncio.Task[None] | None = None

    def _ensure_reaper(self) -> None:
        if self._reaper_task is None or self._reaper_task.done():
            self._reaper_task = asyncio.create_task(
                self._reap_idle(),
                name="mcp-runtime-reaper",
            )

    async def _reap_idle(self) -> None:
        interval = max(1, min(60, settings.MCP_RUNTIME_IDLE_SECONDS // 2))
        while True:
            await asyncio.sleep(interval)
            cutoff = time.monotonic() - settings.MCP_RUNTIME_IDLE_SECONDS
            async with self._lock:
                stale = [
                    runtime
                    for runtime in self._runtimes.values()
                    if runtime.last_used < cutoff
                ]
                for runtime in stale:
                    self._runtimes.pop(
                        (runtime.config.user_id, runtime.config.id), None
                    )
            await asyncio.gather(*(self._close(runtime) for runtime in stale))

    async def _validate(self, config: MCPServerConfig) -> None:
        from app.services.capabilities.mcp_server_service import validate_transport

        validate_transport(config.transport)
        if config.transport == "stdio":
            return
        if not config.url:
            raise ValueError("MCP server URL is missing")
        if not settings.MCP_ALLOW_PRIVATE_NETWORKS:
            await asyncio.to_thread(validate_safe_url, config.url)

    @asynccontextmanager
    async def _session(self, config: MCPServerConfig) -> AsyncIterator[Any]:
        await self._validate(config)
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        from mcp.client.streamable_http import streamable_http_client

        async with AsyncExitStack() as stack:
            if config.transport == "streamable_http":
                client = await stack.enter_async_context(
                    httpx.AsyncClient(
                        headers=config.headers,
                        timeout=settings.AGENT_TOOL_TIMEOUT_SECONDS,
                    )
                )
                streams = await stack.enter_async_context(
                    streamable_http_client(config.url or "", http_client=client)
                )
            else:
                params = StdioServerParameters(
                    command=config.command or "",
                    args=config.args,
                    env={**os.environ, **config.env},
                )
                streams = await stack.enter_async_context(stdio_client(params))
            session = await stack.enter_async_context(
                ClientSession(streams[0], streams[1])
            )
            await session.initialize()
            yield session

    async def _run(self, runtime: _ServerRuntime) -> None:
        request: _Request | None = None
        try:
            async with self._session(runtime.config) as session:
                runtime.status = "connected"
                while True:
                    request = await runtime.queue.get()
                    if request.future.cancelled():
                        continue
                    runtime.last_used = time.monotonic()
                    try:
                        if request.operation == "list_tools":
                            value = await session.list_tools()
                        else:
                            value = await session.call_tool(
                                request.arguments["name"],
                                arguments=request.arguments["arguments"],
                            )
                    except BaseException as exc:
                        if not request.future.done():
                            request.future.set_exception(exc)
                        raise
                    else:
                        if not request.future.done():
                            request.future.set_result(value)
                    request = None
        except asyncio.CancelledError:
            runtime.status = "closed"
            if request is not None and not request.future.done():
                request.future.cancel()
            self._cancel_queued(runtime)
            raise
        except BaseException as exc:
            runtime.status = "failed"
            runtime.last_error = str(exc)
            while not runtime.queue.empty():
                request = runtime.queue.get_nowait()
                if not request.future.done():
                    request.future.set_exception(exc)

    @staticmethod
    def _cancel_queued(runtime: _ServerRuntime) -> None:
        """Release callers waiting behind a runtime that is being closed."""
        while not runtime.queue.empty():
            queued = runtime.queue.get_nowait()
            if not queued.future.done():
                queued.future.cancel()

    async def _get_runtime(self, config: MCPServerConfig) -> _ServerRuntime:
        self._ensure_reaper()
        key = (config.user_id, config.id)
        stale: _ServerRuntime | None = None
        async with self._lock:
            runtime = self._runtimes.get(key)
            if runtime is not None and runtime.config.revision != config.revision:
                self._runtimes.pop(key)
                stale = runtime
                runtime = None
            if runtime is None or runtime.task is None or runtime.task.done():
                runtime = _ServerRuntime(config=config)
                runtime.task = asyncio.create_task(
                    self._run(runtime),
                    name=f"mcp:{config.user_id}:{config.id}",
                )
                self._runtimes[key] = runtime
            runtime.last_used = time.monotonic()
        if stale is not None:
            await self._close(stale)
        return runtime

    async def _request(
        self,
        config: MCPServerConfig,
        operation: str,
        arguments: dict[str, Any] | None = None,
    ) -> Any:
        runtime = await self._get_runtime(config)
        future = asyncio.get_running_loop().create_future()
        await runtime.queue.put(_Request(operation, arguments or {}, future))
        try:
            async with asyncio.timeout(settings.AGENT_TOOL_TIMEOUT_SECONDS):
                return await future
        except BaseException:
            await self._discard(runtime)
            raise

    async def list_tools(
        self,
        config: MCPServerConfig,
        *,
        force: bool = False,
    ) -> list[MCPToolDescriptor]:
        if force:
            await self.invalidate(config.user_id, config.id)
        runtime = await self._get_runtime(config)
        if runtime.tools is not None:
            return list(runtime.tools)
        response = await self._request(config, "list_tools")
        tools = [
            MCPToolDescriptor(
                name=_tool_name(config.name, tool.name),
                server_id=config.id,
                server_name=config.name,
                remote_name=tool.name,
                description=tool.description or tool.title or tool.name,
                input_schema=dict(
                    tool.inputSchema or {"type": "object", "properties": {}}
                ),
            )
            for tool in response.tools
        ]
        runtime.tools = tools
        return list(tools)

    async def discover(
        self,
        configs: list[MCPServerConfig],
    ) -> tuple[list[MCPToolDescriptor], dict[int, str]]:
        results = await asyncio.gather(
            *(self.list_tools(config) for config in configs),
            return_exceptions=True,
        )
        tools: list[MCPToolDescriptor] = []
        failures: dict[int, str] = {}
        for config, result in zip(configs, results, strict=True):
            if isinstance(result, BaseException):
                failures[config.id] = str(result)
            else:
                tools.extend(result)
        return tools, failures

    async def call_tool(
        self,
        config: MCPServerConfig,
        tool: MCPToolDescriptor,
        arguments: dict,
    ) -> dict:
        result = await self._request(
            config,
            "call_tool",
            {
                "name": tool.remote_name,
                "arguments": arguments,
            },
        )
        payload = result.model_dump(mode="json", by_alias=True, exclude_none=True)
        if payload.get("isError"):
            return {"error": "mcp_tool_error", "server": config.name, "result": payload}
        return {"server": config.name, "tool": tool.remote_name, "result": payload}

    async def invalidate(self, user_id: int, server_id: int) -> None:
        async with self._lock:
            runtime = self._runtimes.pop((user_id, server_id), None)
        if runtime is not None:
            await self._close(runtime)

    async def _discard(self, runtime: _ServerRuntime) -> None:
        key = (runtime.config.user_id, runtime.config.id)
        async with self._lock:
            if self._runtimes.get(key) is runtime:
                self._runtimes.pop(key)
        await self._close(runtime)

    @staticmethod
    async def _close(runtime: _ServerRuntime) -> None:
        if runtime.task is None or runtime.task.done():
            return
        runtime.task.cancel()
        await asyncio.gather(runtime.task, return_exceptions=True)

    async def close_all(self) -> None:
        reaper = self._reaper_task
        self._reaper_task = None
        if reaper is not None:
            reaper.cancel()
        async with self._lock:
            runtimes = list(self._runtimes.values())
            self._runtimes.clear()
        await asyncio.gather(
            *(self._close(runtime) for runtime in runtimes),
            *([reaper] if reaper is not None else []),
            return_exceptions=True,
        )

    def status(self, user_id: int, server_id: int) -> dict[str, Any] | None:
        runtime = self._runtimes.get((user_id, server_id))
        if runtime is None:
            return None
        return {
            "status": runtime.status,
            "error": runtime.last_error,
            "revision": runtime.config.revision,
            "idle_seconds": round(time.monotonic() - runtime.last_used, 1),
        }


manager = MCPManager()
