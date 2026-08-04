import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from types import MappingProxyType
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.agent_runtime.mcp.manager import MCPManager, MCPToolDescriptor
from app.agent_runtime.tool_registry import (
    AgentToolContext,
    ToolEntry,
    ToolRegistry,
    registry,
)
from pydantic import BaseModel
from app.agent_runtime.turn_tool_catalog import TurnToolCatalog
from app.models.user import User
from app.models.user_skill import UserSkill
from app.services.capabilities.mcp_server_service import MCPServerConfig
from tests.conftest import patch_session_locals


CONFIG = MCPServerConfig(
    id=7,
    name="demo",
    transport="streamable_http",
    url="https://example.com/mcp",
    command=None,
    args=[],
    headers={},
    env={},
    revision="1",
)
TOOL = MCPToolDescriptor(
    name="mcp__demo__add",
    server_id=7,
    server_name="demo",
    remote_name="add",
    description="Add two values",
    input_schema={
        "type": "object",
        "properties": {"a": {"type": "number"}, "b": {"type": "number"}},
        "required": ["a", "b"],
    },
)


class _Args(BaseModel):
    value: int


async def _handler(args, _ctx):
    return {"value": args.value}


def test_builtin_turn_view_is_immutable():
    local = ToolRegistry()
    local._default_tools_loaded = True
    local.register(ToolEntry("first", "First", _Args, _handler))
    view = local.snapshot()
    local.register(ToolEntry("second", "Second", _Args, _handler))
    assert "first" in view
    assert "second" not in view


def test_tool_search_loads_schema_and_dispatches(monkeypatch):
    catalog = TurnToolCatalog(
        builtins=registry.snapshot(user_id="alice"),
        excluded=frozenset(),
        user_id="alice",
        user_pk=1,
        session_id="",
        turn_id=None,
        skills=(),
        mcp_tools=(TOOL,),
        mcp_configs=MappingProxyType({7: CONFIG}),
        permissions=MappingProxyType({}),
        tool_history=(),
    )
    monkeypatch.setattr(
        "app.agent_runtime.turn_tool_catalog.manager.call_tool",
        AsyncMock(return_value={"result": 3}),
    )

    async def run():
        ctx = AgentToolContext(user_id="alice", session_id="s1")
        loaded = await catalog.dispatch("tool_search", {"query": "add"}, ctx)
        assert loaded["loaded_tools"][0]["name"] == TOOL.name
        assert TOOL.name in {
            item["function"]["name"] for item in catalog.get_openai_schemas()
        }
        return await catalog.dispatch(TOOL.name, {"a": 1, "b": 2}, ctx)

    assert asyncio.run(run()) == {"result": 3}


def test_skill_content_is_progressively_loaded(monkeypatch):
    catalog = TurnToolCatalog(
        builtins=registry.snapshot(user_id="alice"),
        excluded=frozenset(),
        user_id="alice",
        user_pk=1,
        session_id="",
        turn_id=None,
        skills=(
            {
                "id": 1,
                "name": "plan",
                "description": "Create a plan",
                "updated_at": "1",
            },
        ),
        mcp_tools=(),
        mcp_configs=MappingProxyType({}),
        permissions=MappingProxyType({}),
        tool_history=(),
    )
    monkeypatch.setattr(
        TurnToolCatalog,
        "_load_skill",
        AsyncMock(
            return_value={
                "name": "plan",
                "description": "Create a plan",
                "content": "---\nname: plan\ndescription: Create a plan\n---\nDo the work.",
            }
        ),
    )

    async def run():
        ctx = AgentToolContext(user_id="alice", session_id="s1")
        found = await catalog.dispatch("skill_search", {"query": "plan"}, ctx)
        loaded = await catalog.dispatch("skill_load", {"name": "plan"}, ctx)
        return found, loaded

    found, loaded = asyncio.run(run())
    assert "content" not in found["skills"][0]
    assert "Do the work" in loaded["instructions"]


def test_denied_discovery_tool_cannot_be_dispatched():
    catalog = TurnToolCatalog(
        builtins=registry.snapshot(user_id="alice"),
        excluded=frozenset(),
        user_id="alice",
        user_pk=1,
        session_id="",
        turn_id=None,
        skills=(
            {
                "id": 1,
                "name": "plan",
                "description": "Create a plan",
                "updated_at": "1",
            },
        ),
        mcp_tools=(),
        mcp_configs=MappingProxyType({}),
        permissions=MappingProxyType({"skill_search": "deny"}),
        tool_history=(),
    )

    async def run():
        return await catalog.dispatch(
            "skill_search",
            {"query": "plan"},
            AgentToolContext(user_id="alice", session_id="s1"),
        )

    assert asyncio.run(run()) == {
        "error": "permission_denied",
        "capability": "skill_search",
    }


def test_lazy_skill_load_rejects_mid_turn_revision_change(db_session, monkeypatch):
    import app.agent_runtime.turn_tool_catalog as catalog_module

    user = User(username="skill-owner", hashed_password="x")
    db_session.add(user)
    db_session.flush()
    skill = UserSkill(
        user_id=user.id,
        name="plan",
        description="Create a plan",
        content="---\nname: plan\ndescription: Create a plan\n---\nOld instructions.",
        enabled=True,
    )
    db_session.add(skill)
    db_session.commit()
    patch_session_locals(monkeypatch, db_session, catalog_module)
    revision = skill.updated_at.isoformat()
    catalog = TurnToolCatalog(
        builtins=registry.snapshot(user_id=user.username),
        excluded=frozenset(),
        user_id=user.username,
        user_pk=user.id,
        session_id="",
        turn_id=None,
        skills=(
            {
                "id": skill.id,
                "name": skill.name,
                "description": skill.description,
                "updated_at": revision,
            },
        ),
        mcp_tools=(),
        mcp_configs=MappingProxyType({}),
        permissions=MappingProxyType({}),
        tool_history=(),
    )
    skill.content = (
        "---\nname: plan\ndescription: Create a plan\n---\nNew instructions."
    )
    skill.updated_at = datetime.fromisoformat(revision) + timedelta(seconds=1)
    db_session.commit()

    async def run():
        return await catalog.dispatch(
            "skill_load",
            {"name": "plan"},
            AgentToolContext(user_id=user.username, session_id="s1"),
        )

    assert asyncio.run(run()) == {
        "error": "skill_revision_changed",
        "name": "plan",
    }


def test_mcp_manager_maps_remote_tools(monkeypatch):
    instance = MCPManager()
    session = SimpleNamespace(
        list_tools=AsyncMock(
            return_value=SimpleNamespace(
                tools=[
                    SimpleNamespace(
                        name="add",
                        title=None,
                        description="Add",
                        inputSchema={"type": "object", "properties": {}},
                    )
                ]
            )
        )
    )

    @asynccontextmanager
    async def fake_session(_config):
        yield session

    monkeypatch.setattr(instance, "_session", fake_session)

    async def run():
        tools = await instance.list_tools(CONFIG)
        await instance.close_all()
        return tools

    tools = asyncio.run(run())
    assert tools[0].name == "mcp__demo__add"
    assert session.list_tools.await_count == 1


def test_mcp_runtime_reuses_connection_and_tool_cache(monkeypatch):
    instance = MCPManager()
    opened = 0
    session = SimpleNamespace(
        list_tools=AsyncMock(
            return_value=SimpleNamespace(
                tools=[
                    SimpleNamespace(
                        name="add",
                        title=None,
                        description="Add",
                        inputSchema={"type": "object", "properties": {}},
                    )
                ]
            )
        ),
        call_tool=AsyncMock(
            return_value=SimpleNamespace(
                model_dump=lambda **_kwargs: {
                    "content": [{"type": "text", "text": "3"}]
                },
            )
        ),
    )

    @asynccontextmanager
    async def fake_session(_config):
        nonlocal opened
        opened += 1
        yield session

    monkeypatch.setattr(instance, "_session", fake_session)

    async def run():
        first = await instance.list_tools(CONFIG)
        second = await instance.list_tools(CONFIG)
        result = await instance.call_tool(CONFIG, first[0], {"a": 1, "b": 2})
        await instance.close_all()
        return first, second, result

    first, second, result = asyncio.run(run())
    assert first == second
    assert result["tool"] == "add"
    assert opened == 1
    assert session.list_tools.await_count == 1


def test_mcp_runtime_isolated_by_user_and_revision(monkeypatch):
    instance = MCPManager()
    opened = 0
    session = SimpleNamespace(
        list_tools=AsyncMock(return_value=SimpleNamespace(tools=[]))
    )

    @asynccontextmanager
    async def fake_session(_config):
        nonlocal opened
        opened += 1
        yield session

    monkeypatch.setattr(instance, "_session", fake_session)

    async def run():
        await instance.list_tools(CONFIG)
        await instance.list_tools(MCPServerConfig(**{**CONFIG.__dict__, "user_id": 2}))
        await instance.list_tools(
            MCPServerConfig(**{**CONFIG.__dict__, "revision": "2"})
        )
        await instance.close_all()

    asyncio.run(run())
    assert opened == 3


def test_mcp_runtime_close_releases_running_and_queued_callers(monkeypatch):
    instance = MCPManager()
    entered = asyncio.Event()
    release = asyncio.Event()
    session = SimpleNamespace()

    async def slow_list_tools():
        entered.set()
        await release.wait()

    session.list_tools = slow_list_tools

    @asynccontextmanager
    async def fake_session(_config):
        yield session

    monkeypatch.setattr(instance, "_session", fake_session)

    async def run():
        first = asyncio.create_task(instance._request(CONFIG, "list_tools"))
        await entered.wait()
        second = asyncio.create_task(instance._request(CONFIG, "list_tools"))
        await asyncio.sleep(0)

        await instance.invalidate(CONFIG.user_id, CONFIG.id)
        outcomes = await asyncio.gather(first, second, return_exceptions=True)
        await instance.close_all()
        return outcomes

    outcomes = asyncio.run(run())
    assert all(isinstance(item, asyncio.CancelledError) for item in outcomes)
