from __future__ import annotations

import asyncio
import hashlib
import os
import re
import threading
import time
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

import httpx

from app.core.config import settings
from app.core.ssrf import resolve_safe_url, validate_safe_url
from app.capabilities.application.mcp_server_service import MCPServerConfig
from .schema import tool_validator


# A stdio MCP server is a deployment-trusted subprocess, but that does not
# make every secret held by the API process part of its contract.  Keep only
# the small set needed to locate executables and run them reliably across
# POSIX and Windows.  Anything else must be supplied explicitly in the MCP
# server's encrypted ``env`` configuration.
_STDIO_INHERITED_ENV_KEYS = (
    "PATH",
    "PATHEXT",
    "SYSTEMROOT",
    "WINDIR",
    "COMSPEC",
    "TEMP",
    "TMP",
    "TMPDIR",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "TZ",
)
_STDIO_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_STDIO_ENV_MAX_COUNT = 64
_STDIO_ENV_MAX_NAME_CHARS = 128
_STDIO_ENV_MAX_TOTAL_CHARS = 32_000


class _PinnedAsyncTransport(httpx.AsyncBaseTransport):
    """Resolve-once transport for one remote MCP origin.

    Every request is dialled through the already-validated IP while retaining
    the original Host header and TLS SNI. Absolute URLs for any other host are
    rejected rather than creating an unchecked redirect/endpoint hop.
    """

    def __init__(self, *, hostname: str, connect_host: str, host_header: str) -> None:
        self._hostname = hostname.casefold()
        self._connect_host = connect_host
        self._host_header = host_header
        self._inner = httpx.AsyncHTTPTransport()

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        request_host = (request.url.host or "").casefold()
        if request_host not in {self._hostname, self._connect_host.casefold()}:
            raise httpx.ConnectError("MCP endpoint changed origin", request=request)
        request.url = request.url.copy_with(host=self._connect_host)
        request.headers["host"] = self._host_header
        request.extensions["sni_hostname"] = self._hostname
        return await self._inner.handle_async_request(request)

    async def aclose(self) -> None:
        await self._inner.aclose()


def _validated_stdio_config_env(configured: dict[str, str] | None) -> dict[str, str]:
    """Validate the env explicitly granted to one stdio MCP server.

    Validation happens again at execution time so legacy or directly-created
    database rows cannot bypass the API schema.  Error messages deliberately
    name only the key and never reveal configured values.
    """

    if not configured:
        return {}
    if not isinstance(configured, dict):
        raise ValueError("stdio MCP env must be a string mapping")
    if len(configured) > _STDIO_ENV_MAX_COUNT:
        raise ValueError(
            f"stdio MCP env has too many entries (max {_STDIO_ENV_MAX_COUNT})"
        )

    validated: dict[str, str] = {}
    seen_names: set[str] = set()
    total_chars = 0
    for name, value in configured.items():
        if not isinstance(name, str) or not isinstance(value, str):
            raise ValueError("stdio MCP env keys and values must be strings")
        if (
            not name
            or len(name) > _STDIO_ENV_MAX_NAME_CHARS
            or _STDIO_ENV_NAME_RE.fullmatch(name) is None
        ):
            raise ValueError(f"invalid stdio MCP env key: {name!r}")
        if "\x00" in value:
            raise ValueError(f"stdio MCP env value contains NUL: {name!r}")
        folded_name = name.casefold()
        if folded_name in seen_names:
            raise ValueError(f"duplicate stdio MCP env key: {name!r}")
        seen_names.add(folded_name)
        total_chars += len(name) + len(value) + 2
        if total_chars > _STDIO_ENV_MAX_TOTAL_CHARS:
            raise ValueError(
                "stdio MCP env is too large "
                f"(max {_STDIO_ENV_MAX_TOTAL_CHARS} characters)"
            )
        validated[name] = value
    return validated


def _stdio_environment(configured: dict[str, str] | None) -> dict[str, str]:
    """Build the exact environment passed to a stdio MCP subprocess."""

    inherited = {
        name: value
        for name in _STDIO_INHERITED_ENV_KEYS
        if (value := os.environ.get(name)) is not None
    }
    for name, value in _validated_stdio_config_env(configured).items():
        # Avoid ambiguous duplicate keys on Windows, whose environment is
        # case-insensitive, while preserving the explicitly configured spelling.
        for inherited_name in tuple(inherited):
            if inherited_name.casefold() == name.casefold():
                inherited.pop(inherited_name)
        inherited[name] = value
    return inherited


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
    started: bool = False


class MCPConnectionClosed(RuntimeError):
    """A shared connection ended; this is not cancellation of the caller's Turn."""


@dataclass
class _ServerRuntime:
    config: MCPServerConfig
    queue: asyncio.Queue[_Request] = field(default_factory=asyncio.Queue)
    task: asyncio.Task[None] | None = None
    status: str = "connecting"
    last_error: str | None = None
    last_used: float = field(default_factory=time.monotonic)
    tools: list[MCPToolDescriptor] | None = None
    pending: int = 0
    catalog_generation: int = 0


def _component(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", value).strip("_") or "tool"


def _tool_name(server: str, remote: str) -> str:
    name = f"mcp__{_component(server)}__{_component(remote)}"
    if (
        len(name) <= 64
        and _component(server) == server
        and _component(remote) == remote
    ):
        return name
    digest = hashlib.sha256(f"{server}\0{remote}".encode("utf-8")).hexdigest()[:12]
    return f"{name[:51]}_{digest}"


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
                    if runtime.last_used < cutoff and runtime.pending == 0
                ]
                for runtime in stale:
                    self._runtimes.pop(
                        (runtime.config.user_id, runtime.config.id), None
                    )
            await asyncio.gather(*(self._close(runtime) for runtime in stale))

    async def _validate(self, config: MCPServerConfig) -> None:
        from app.capabilities.application.mcp_server_service import validate_transport

        validate_transport(config.transport)
        if config.transport == "stdio":
            if not config.command:
                raise ValueError("stdio MCP command is missing")
            _validated_stdio_config_env(config.env)
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
                resolved = await asyncio.to_thread(
                    resolve_safe_url,
                    config.url or "",
                    allow_private=settings.MCP_ALLOW_PRIVATE_NETWORKS,
                )
                transport = _PinnedAsyncTransport(
                    hostname=resolved.hostname,
                    connect_host=httpx.URL(resolved.connect_url).host,
                    host_header=resolved.host_header,
                )
                client = await stack.enter_async_context(
                    httpx.AsyncClient(
                        headers={**config.headers, "Host": resolved.host_header},
                        timeout=settings.AGENT_TOOL_TIMEOUT_SECONDS,
                        # A server-side user-configured connection must not be
                        # silently rerouted through process-level proxy env or
                        # follow a redirect to a target that was never checked.
                        trust_env=False,
                        follow_redirects=False,
                        transport=transport,
                    )
                )
                streams = await stack.enter_async_context(
                    streamable_http_client(resolved.connect_url, http_client=client)
                )
            else:
                params = StdioServerParameters(
                    command=config.command or "",
                    args=config.args,
                    env=_stdio_environment(config.env),
                )
                streams = await stack.enter_async_context(stdio_client(params))

            async def on_message(message):
                self._handle_notification(config, message)

            session = await stack.enter_async_context(
                ClientSession(streams[0], streams[1], message_handler=on_message)
            )
            await session.initialize()
            yield session

    def _handle_notification(self, config: MCPServerConfig, message) -> None:
        from mcp.types import ToolListChangedNotification

        if isinstance(message, ToolListChangedNotification):
            runtime = self._runtimes.get((config.user_id, config.id))
            if runtime is not None and runtime.config.revision == config.revision:
                runtime.tools = None
                runtime.catalog_generation += 1

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
                    request.started = True
                    try:
                        if request.operation == "list_tools":
                            value = await session.list_tools(**request.arguments)
                        else:
                            value = await session.call_tool(
                                request.arguments["name"],
                                arguments=request.arguments["arguments"],
                            )
                    except asyncio.CancelledError:
                        raise
                    except BaseException as exc:
                        if not request.future.done():
                            request.future.set_exception(exc)
                        raise
                    else:
                        if not request.future.done():
                            request.future.set_result(value)
                    runtime.last_used = time.monotonic()
                    request = None
        except asyncio.CancelledError:
            runtime.status = "closed"
            if request is not None and not request.future.done():
                request.future.set_exception(
                    MCPConnectionClosed("mcp_connection_closed")
                )
            self._cancel_queued(runtime)
            raise
        except BaseException as exc:
            runtime.status = "failed"
            runtime.last_error = type(exc).__name__
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
                queued.future.set_exception(
                    MCPConnectionClosed("mcp_connection_closed")
                )

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
        from app.usage import runtime as accounting
        from app.usage.external import owned_scope

        runtime = await self._get_runtime(config)
        receipt = None
        if operation != "list_tools":
            with owned_scope(config.user_id):
                receipt = await accounting.begin_async(
                    meter="external_tool",
                    provider=f"mcp:{config.id}",
                    model=str((arguments or {}).get("name") or operation),
                    content={
                        "operation": operation,
                        "arguments": arguments,
                        "revision": config.revision,
                    },
                    units={"requests": 1, "tool_invocations": 1},
                )
        future = asyncio.get_running_loop().create_future()
        request = _Request(operation, arguments or {}, future)
        runtime.pending += 1
        runtime.queue.put_nowait(request)
        try:
            try:
                async with asyncio.timeout(settings.AGENT_TOOL_TIMEOUT_SECONDS):
                    result = await future
            except BaseException as exc:
                # Cancelling a queued request must not abort another caller's
                # currently executing operation on the shared server session.
                try:
                    if request.started:
                        await self._discard(runtime)
                finally:
                    if receipt is not None:
                        await accounting.finish_async(
                            receipt,
                            accounting.failure_outcome(exc)
                            if request.started
                            else "rejected",
                        )
                raise
            # Success at the provider and success at the accounting COMMIT are
            # distinct. Never discard a healthy session or settle again because
            # the local COMMIT acknowledgement was lost.
            if receipt is not None:
                await accounting.finish_async(
                    receipt, "completed", {"requests": 1, "tool_invocations": 1}
                )
            return result
        finally:
            runtime.pending -= 1
            runtime.last_used = time.monotonic()

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
        catalog_generation = runtime.catalog_generation
        remote_tools = []
        cursor = None
        seen_cursors: set[str] = set()
        for _ in range(100):
            response = await self._request(
                config, "list_tools", {"cursor": cursor} if cursor else {}
            )
            remote_tools.extend(response.tools)
            if len(remote_tools) > 10_000:
                raise ValueError("MCP tool catalog exceeds limit")
            cursor = response.next_cursor
            if not cursor:
                break
            if cursor in seen_cursors:
                raise ValueError("MCP tool catalog cursor repeated")
            seen_cursors.add(cursor)
        else:
            raise ValueError("MCP tool catalog page limit exceeded")
        tools = [
            MCPToolDescriptor(
                name=_tool_name(config.name, tool.name),
                server_id=config.id,
                server_name=config.name,
                remote_name=tool.name,
                description=tool.description or tool.title or tool.name,
                input_schema=dict(
                    tool.input_schema or {"type": "object", "properties": {}}
                ),
            )
            for tool in remote_tools
        ]
        if len({tool.name for tool in tools}) != len(tools):
            raise ValueError("MCP tool catalog contains duplicate identities")
        for tool in tools:
            tool_validator(tool.input_schema)
        if runtime.catalog_generation != catalog_generation:
            raise ValueError("MCP tool catalog changed during discovery")
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
                failures[config.id] = type(result).__name__
            else:
                tools.extend(result)
        return tools, failures

    async def call_tool(
        self,
        config: MCPServerConfig,
        tool: MCPToolDescriptor,
        arguments: dict,
    ) -> dict:
        if tool.server_id != config.id or tool.server_name != config.name:
            return {"error": "mcp_tool_identity_mismatch"}
        current = next(
            (item for item in await self.list_tools(config) if item.name == tool.name),
            None,
        )
        if current != tool:
            return {"error": "mcp_tool_schema_changed", "tool_name": tool.name}
        try:
            if not tool_validator(tool.input_schema).is_valid(arguments):
                return {"error": "tool_args_validation_failed", "tool_name": tool.name}
        except Exception:
            return {"error": "tool_schema_invalid", "tool_name": tool.name}
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


class LoopScopedMCPManager:
    """Never share asyncio queues/tasks between API and worker event loops.

    Workers keep a persistent loop per thread. Connection revisions are still
    checked at every call; runtime status is a process-local observation.
    """

    def __init__(self) -> None:
        self._guard = threading.RLock()
        self._managers: dict[asyncio.AbstractEventLoop, MCPManager] = {}

    def _current(self) -> MCPManager:
        loop = asyncio.get_running_loop()
        with self._guard:
            for expired in list(self._managers):
                if expired.is_closed():
                    self._managers.pop(expired)
            return self._managers.setdefault(loop, MCPManager())

    async def discover(self, configs):
        return await self._current().discover(configs)

    async def list_tools(self, config, *, force=False):
        return await self._current().list_tools(config, force=force)

    async def call_tool(self, config, tool, arguments):
        return await self._current().call_tool(config, tool, arguments)

    async def invalidate(self, user_id: int, server_id: int) -> None:
        current_loop = asyncio.get_running_loop()
        with self._guard:
            managers = list(self._managers.items())
        for loop, runtime_manager in managers:
            if loop.is_closed():
                continue
            if loop is current_loop:
                await runtime_manager.invalidate(user_id, server_id)
            else:
                # Do not await an idle worker loop. It drains this callback
                # when it resumes; revision fences also run before dispatch.
                loop.call_soon_threadsafe(
                    lambda manager=runtime_manager: asyncio.create_task(
                        manager.invalidate(user_id, server_id)
                    )
                )

    async def close_all(self) -> None:
        await self._current().close_all()

    def status(self, user_id: int, server_id: int):
        with self._guard:
            managers = list(self._managers.items())
        for loop, runtime_manager in managers:
            if not loop.is_closed():
                status = runtime_manager.status(user_id, server_id)
                if status is not None:
                    return status
        return None


manager = LoopScopedMCPManager()
