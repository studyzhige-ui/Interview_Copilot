"""Fault injection at model, schema and MCP transport boundaries."""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace as NS

import pytest
from pydantic import BaseModel, Field
from mcp.types import Tool, ListToolsResult

from app.agent_runtime.mcp.manager import MCPManager, _tool_name
from app.agent_runtime.mcp.schema import tool_validator
from app.agent_runtime.tool_call_streaming import (
    ToolCallAssembler,
    ToolCallProtocolError,
)
from app.agent_runtime.tool_registry import (
    AgentToolContext,
    ToolDefinition,
    ToolRegistry,
    parse_tool_arguments,
)
from app.core.config import settings
from app.services.capabilities.mcp_server_service import MCPServerConfig


def event(*, index=0, call_id="c1", name="lookup", arguments="{}", stop=None):
    return NS(
        stop_reason=stop,
        tool_call_deltas=[
            NS(index=index, call_id=call_id, name=name, arguments_delta=arguments)
        ],
    )


def test_stream_requires_completion_and_preserves_model_order():
    assembler = ToolCallAssembler()
    assembler.feed(event(index=1, call_id="second"))
    assembler.feed(event(index=0, call_id="first"))
    with pytest.raises(ToolCallProtocolError):
        assembler.finish()
    assembler.feed(NS(stop_reason="tool_calls", tool_call_deltas=[]))
    assert [call.id for call in assembler.finish()] == ["first", "second"]
    with pytest.raises(ToolCallProtocolError):
        assembler.feed(event())


@pytest.mark.parametrize(
    "mutation",
    [dict(call_id="other"), dict(name="other"), dict(index=128), dict(index=-1)],
)
def test_stream_rejects_ambiguous_or_unbounded_identity(mutation):
    assembler = ToolCallAssembler()
    assembler.feed(event())
    with pytest.raises(ToolCallProtocolError):
        assembler.feed(event(**mutation))


@pytest.mark.parametrize("stop", [None, "length", "content_filter"])
def test_incomplete_stream_never_publishes_calls(stop):
    assembler = ToolCallAssembler()
    assembler.feed(event(stop=stop))
    with pytest.raises(ToolCallProtocolError):
        assembler.finish()


def test_stream_bounded_before_arguments_are_accumulated(monkeypatch):
    monkeypatch.setattr(settings, "AGENT_MAX_TOOL_ARG_CHARS", 5)
    assembler = ToolCallAssembler()
    assembler.feed(event(arguments="123"))
    with pytest.raises(ToolCallProtocolError):
        assembler.feed(event(arguments="456"))


@pytest.mark.parametrize(
    "payload",
    ['{"x":1,"x":2}', '{"x":{"a":1,"a":2}}', '{"x":NaN}', '{"x":Infinity}', "[]"],
)
def test_argument_parser_rejects_noncanonical_payload(payload):
    with pytest.raises(ValueError):
        parse_tool_arguments(payload)


def test_registration_collision_and_extra_arguments_never_invoke_handler():
    class Args(BaseModel):
        query: str = Field(description="Exact search phrase")

    called = []

    async def handler(args, ctx):
        called.append(args)
        return {}

    registry = ToolRegistry()
    registry._default_tools_loaded = True
    definition = ToolDefinition("lookup", "Find", Args, handler)
    registry.register(definition)
    with pytest.raises(ValueError):
        registry.register(definition)
    result = asyncio.run(
        registry.snapshot().dispatch(
            "lookup", {"query": "a", "secret": "sentinel"}, AgentToolContext("u", "s")
        )
    )
    assert result["error"] == "tool_args_validation_failed"
    assert "sentinel" not in str(result)
    assert not called
    schema = registry.snapshot().get_openai_schemas()[0]
    assert (
        schema["function"]["parameters"]["properties"]["query"]["description"]
        == "Exact search phrase"
    )


def test_remote_schema_resolves_local_definitions_but_never_fetches_urls():
    schema = {
        "type": "object",
        "properties": {"x": {"$ref": "#/$defs/X"}},
        "$defs": {"X": {"type": "integer"}},
    }
    assert tool_validator(schema).is_valid({"x": 1})
    assert not tool_validator(schema).is_valid({"x": "bad"})
    schema["properties"]["x"]["$ref"] = "http://127.0.0.1/private"
    with pytest.raises(Exception):
        tool_validator(schema).is_valid({"x": 1})


def config():
    return MCPServerConfig(
        id=1,
        user_id=1,
        name="server",
        transport="stdio",
        command="unused",
        url=None,
        args=[],
        headers={},
        env={},
        revision="1",
    )


def tool(name):
    return Tool(
        name=name, description="Test", inputSchema={"type": "object", "properties": {}}
    )


def test_mcp_paginates_and_does_not_alias_sanitized_names(monkeypatch):
    async def run():
        manager = MCPManager()
        cursors = []

        async def list_tools(cursor=None):
            cursors.append(cursor)
            return ListToolsResult(
                tools=[tool("a.b" if cursor is None else "a_b")],
                nextCursor="page2" if cursor is None else None,
            )

        @asynccontextmanager
        async def session(_config):
            yield NS(list_tools=list_tools)

        monkeypatch.setattr(manager, "_session", session)
        try:
            tools = await manager.list_tools(config())
            assert cursors == [None, "page2"]
            assert len({item.name for item in tools}) == 2
            assert all(len(item.name) <= 64 for item in tools)
            assert _tool_name("server", "a_b") == "mcp__server__a_b"
        finally:
            await manager.close_all()

    asyncio.run(run())


def test_mcp_repeated_cursor_fails_without_hanging(monkeypatch):
    async def run():
        manager = MCPManager()

        async def list_tools(cursor=None):
            return ListToolsResult(tools=[], nextCursor="same")

        @asynccontextmanager
        async def session(_config):
            yield NS(list_tools=list_tools)

        monkeypatch.setattr(manager, "_session", session)
        try:
            with pytest.raises(ValueError, match="cursor repeated"):
                await manager.list_tools(config())
        finally:
            await manager.close_all()

    asyncio.run(run())


def test_cancelling_queued_mcp_call_preserves_active_call(monkeypatch):
    async def run():
        manager = MCPManager()
        started, release = asyncio.Event(), asyncio.Event()
        calls = []

        async def call_tool(name, arguments):
            calls.append(name)
            started.set()
            await release.wait()
            return {"ok": True}

        @asynccontextmanager
        async def session(_config):
            yield NS(call_tool=call_tool)

        monkeypatch.setattr(manager, "_session", session)
        first = asyncio.create_task(
            manager._request(config(), "call_tool", {"name": "first", "arguments": {}})
        )
        try:
            await asyncio.wait_for(started.wait(), 1)
            second = asyncio.create_task(
                manager._request(
                    config(), "call_tool", {"name": "second", "arguments": {}}
                )
            )
            await asyncio.sleep(0)
            second.cancel()
            with pytest.raises(asyncio.CancelledError):
                await second
            release.set()
            assert await first == {"ok": True}
            assert calls == ["first"]
        finally:
            await manager.close_all()

    asyncio.run(run())


def test_mcp_global_connections_are_isolated_across_live_loops():
    from app.agent_runtime.mcp.manager import LoopScopedMCPManager

    facade = LoopScopedMCPManager()
    first_loop, second_loop = asyncio.new_event_loop(), asyncio.new_event_loop()

    async def current():
        return facade._current()

    try:
        first = first_loop.run_until_complete(current())
        second = second_loop.run_until_complete(current())
        assert first is not second
        assert first_loop.run_until_complete(current()) is first
    finally:
        first_loop.close()
        second_loop.close()


def test_mcp_list_changed_invalidates_cached_contract_before_execution(monkeypatch):
    from mcp.types import ToolListChangedNotification

    async def run():
        manager = MCPManager()
        schema_version = 1
        called = []

        async def list_tools():
            item = tool("read")
            item.description = f"version-{schema_version}"
            return ListToolsResult(tools=[item])

        async def call_tool(name, arguments):
            called.append(name)
            raise AssertionError("Old descriptor must never execute")

        @asynccontextmanager
        async def session(_config):
            yield NS(list_tools=list_tools, call_tool=call_tool)

        monkeypatch.setattr(manager, "_session", session)
        try:
            old = (await manager.list_tools(config()))[0]
            schema_version = 2
            manager._handle_notification(config(), ToolListChangedNotification())
            result = await manager.call_tool(config(), old, {})
            assert result["error"] == "mcp_tool_schema_changed"
            assert called == []
        finally:
            await manager.close_all()

    asyncio.run(run())
