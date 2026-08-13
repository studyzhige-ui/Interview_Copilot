from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from importlib import import_module
from types import SimpleNamespace

import pytest

from app.agent_runtime.mcp.manager import (
    MCPManager,
    _STDIO_INHERITED_ENV_KEYS,
    _validated_stdio_config_env,
)
from app.core.config import settings
from app.services.capabilities.mcp_server_service import MCPServerConfig

manager_module = import_module("app.agent_runtime.mcp.manager")


def _config(transport: str, **overrides) -> MCPServerConfig:
    values = {
        "id": 1,
        "user_id": 7,
        "name": "test-server",
        "transport": transport,
        "url": "https://example.com/mcp" if transport == "streamable_http" else None,
        "command": "test-mcp" if transport == "stdio" else None,
        "args": ["--serve"] if transport == "stdio" else [],
        "headers": {},
        "env": {},
        "revision": "1",
    }
    values.update(overrides)
    return MCPServerConfig(**values)


class _FakeClientSession:
    def __init__(self, *_streams) -> None:
        self.initialized = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc_info) -> None:
        return None

    async def initialize(self) -> None:
        self.initialized = True


def test_stdio_child_env_excludes_unconfigured_parent_secret(monkeypatch):
    """A process-level secret must not reach StdioServerParameters.env."""

    parent_secret = "MCP_PARENT_SECRET_SENTINEL"
    monkeypatch.setenv(parent_secret, "must-not-leak")
    monkeypatch.setenv("PATH", "safe-test-path")
    monkeypatch.setattr(settings, "APP_EDITION", "community")
    monkeypatch.setattr(settings, "MCP_ALLOW_STDIO", True)

    captured: dict[str, object] = {}

    class _FakeStdioServerParameters:
        def __init__(self, *, command, args, env) -> None:
            captured["command"] = command
            captured["args"] = args
            captured["env"] = env

    @asynccontextmanager
    async def fake_stdio_client(_params):
        yield (object(), object())

    import mcp
    import mcp.client.stdio

    monkeypatch.setattr(mcp, "ClientSession", _FakeClientSession)
    monkeypatch.setattr(mcp, "StdioServerParameters", _FakeStdioServerParameters)
    monkeypatch.setattr(mcp.client.stdio, "stdio_client", fake_stdio_client)

    config = _config("stdio", env={"MCP_CONFIGURED_TOKEN": "explicit-secret"})

    async def run() -> None:
        async with MCPManager()._session(config) as session:
            assert session.initialized is True

    asyncio.run(run())

    child_env = captured["env"]
    assert isinstance(child_env, dict)
    assert parent_secret not in child_env
    assert child_env["PATH"] == "safe-test-path"
    assert child_env["MCP_CONFIGURED_TOKEN"] == "explicit-secret"
    assert set(child_env) <= set(_STDIO_INHERITED_ENV_KEYS) | {"MCP_CONFIGURED_TOKEN"}


@pytest.mark.parametrize(
    "configured",
    [
        {"BAD=NAME": "value"},
        {"GOOD_NAME": "bad\x00value"},
        {"MixedCase": "one", "MIXEDCASE": "two"},
    ],
)
def test_stdio_config_env_rejects_ambiguous_or_invalid_entries(configured):
    with pytest.raises(ValueError):
        _validated_stdio_config_env(configured)


def test_cloud_hard_denies_stdio_even_when_deployment_flag_is_true(monkeypatch):
    monkeypatch.setattr(settings, "APP_EDITION", "cloud")
    monkeypatch.setattr(settings, "MCP_ALLOW_STDIO", True)

    with pytest.raises(ValueError, match="stdio MCP is not available"):
        asyncio.run(MCPManager()._validate(_config("stdio")))


def test_remote_mcp_runs_through_safe_url_validation(monkeypatch):
    checked: list[str] = []
    monkeypatch.setattr(settings, "APP_EDITION", "community")
    monkeypatch.setattr(settings, "MCP_ALLOW_PRIVATE_NETWORKS", False)
    monkeypatch.setattr(
        manager_module,
        "validate_safe_url",
        lambda url: checked.append(url),
    )

    asyncio.run(MCPManager()._validate(_config("streamable_http")))

    assert checked == ["https://example.com/mcp"]


def test_remote_mcp_http_client_ignores_process_proxy_and_redirects(monkeypatch):
    monkeypatch.setattr(settings, "APP_EDITION", "community")
    monkeypatch.setattr(settings, "MCP_ALLOW_PRIVATE_NETWORKS", True)
    monkeypatch.setattr(
        manager_module,
        "resolve_safe_url",
        lambda _url, **_kwargs: SimpleNamespace(
            connect_url="https://8.8.8.8/mcp",
            hostname="example.com",
            host_header="example.com",
        ),
    )
    captured: dict[str, object] = {}

    class _FakeAsyncClient:
        def __init__(self, **kwargs) -> None:
            captured["client_kwargs"] = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc_info) -> None:
            return None

    @asynccontextmanager
    async def fake_streamable_http_client(url, *, http_client):
        captured["url"] = url
        captured["http_client"] = http_client
        yield (object(), object(), lambda: None)

    import mcp
    import mcp.client.streamable_http

    monkeypatch.setattr(manager_module.httpx, "AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(mcp, "ClientSession", _FakeClientSession)
    monkeypatch.setattr(
        mcp.client.streamable_http,
        "streamable_http_client",
        fake_streamable_http_client,
    )

    config = _config(
        "streamable_http",
        headers={"Authorization": "Bearer configured"},
    )

    async def run() -> None:
        async with MCPManager()._session(config) as session:
            assert session.initialized is True

    asyncio.run(run())

    assert captured["url"] == "https://8.8.8.8/mcp"
    kwargs = captured["client_kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs["headers"] == {
        "Authorization": "Bearer configured",
        "Host": "example.com",
    }
    assert kwargs["trust_env"] is False
    assert kwargs["follow_redirects"] is False
    assert isinstance(kwargs["transport"], manager_module._PinnedAsyncTransport)


def test_pinned_mcp_transport_dials_validated_ip_and_rejects_other_origin():
    captured: dict[str, object] = {}

    class _Inner:
        async def handle_async_request(self, request):
            captured["url"] = str(request.url)
            captured["host"] = request.headers["host"]
            captured["sni"] = request.extensions["sni_hostname"]
            return object()

        async def aclose(self):
            return None

    transport = manager_module._PinnedAsyncTransport(
        hostname="example.com",
        connect_host="8.8.8.8",
        host_header="example.com",
    )
    transport._inner = _Inner()

    async def run() -> None:
        await transport.handle_async_request(
            manager_module.httpx.Request("GET", "https://example.com/mcp")
        )
        with pytest.raises(manager_module.httpx.ConnectError):
            await transport.handle_async_request(
                manager_module.httpx.Request("GET", "https://other.example/mcp")
            )

    asyncio.run(run())
    assert captured == {
        "url": "https://8.8.8.8/mcp",
        "host": "example.com",
        "sni": "example.com",
    }
