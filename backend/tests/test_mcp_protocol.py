"""Exercise the actual MCP stdio protocol against a disposable local server."""

import asyncio
import json
import socket
import sys
import threading
import time
from dataclasses import replace

from app.agent_runtime.mcp.manager import MCPManager
from app.capabilities.application.mcp_server_service import MCPServerConfig
from app.core.config import settings


def test_mcp_discovery_execution_and_user_isolation(tmp_path, monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.db.database import Base
    from app.models.user import User
    from app.usage import runtime

    engine = create_engine(f"sqlite:///{tmp_path / 'mcp.sqlite'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions() as db:
        owners = [
            User(username=name, hashed_password="unused")
            for name in ("first", "second")
        ]
        db.add_all(owners)
        db.commit()
    monkeypatch.setattr(runtime, "SessionLocal", sessions)
    server = tmp_path / "server.py"
    server.write_text(
        "from mcp.server.mcpserver import MCPServer\n"
        "import os\n"
        "server = MCPServer('acceptance')\n"
        "@server.tool()\n"
        "def identify(value: str) -> dict:\n"
        "    return {'value': value, 'owner': os.environ['TEST_OWNER'], "
        "'secret_inherited': 'IC_TEST_PRIVATE_SECRET' in os.environ}\n"
        "server.run(transport='stdio')\n",
        encoding="utf-8",
    )
    # Enable the deployment's opt-in transport only inside this test process.
    monkeypatch.setattr(settings, "MCP_ALLOW_STDIO", True)
    monkeypatch.setenv("IC_TEST_PRIVATE_SECRET", "must-not-reach-subprocess")
    config = MCPServerConfig(
        id=1,
        user_id=owners[0].id,
        name="acceptance",
        transport="stdio",
        url=None,
        command=sys.executable,
        args=[str(server)],
        headers={},
        env={"TEST_OWNER": "first"},
        revision="1",
    )
    other = replace(config, user_id=owners[1].id, env={"TEST_OWNER": "second"})

    async def exercise():
        manager = MCPManager()
        try:
            tools = await manager.list_tools(config)
            assert len(tools) == 1
            assert tools[0].remote_name == "identify"
            first = await manager.call_tool(config, tools[0], {"value": "probe"})
            first_payload = json.loads(first["result"]["content"][0]["text"])
            assert first_payload == {
                "value": "probe",
                "owner": "first",
                "secret_inherited": False,
            }
            second = await manager.call_tool(other, tools[0], {"value": "probe"})
            assert (
                json.loads(second["result"]["content"][0]["text"])["owner"] == "second"
            )
            invalid = await manager.call_tool(config, tools[0], {"value": 42})
            assert invalid["error"] == "tool_args_validation_failed"
            await manager.invalidate(config.user_id, config.id)
            assert manager.status(config.user_id, config.id) is None
            assert manager.status(other.user_id, other.id) is not None
            assert await manager.list_tools(config) == tools
        finally:
            await manager.close_all()

    try:
        asyncio.run(exercise())
    finally:
        engine.dispose()


def test_streamable_http_uses_the_validated_origin_without_environment_proxy(
    monkeypatch,
):
    import uvicorn
    from mcp.server.mcpserver import MCPServer

    server = MCPServer("http-acceptance")

    @server.tool()
    def echo(value: str) -> str:
        return value

    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    application = server.streamable_http_app()
    runtime = uvicorn.Server(
        uvicorn.Config(application, log_level="error", lifespan="on")
    )
    thread = threading.Thread(
        target=runtime.run, kwargs={"sockets": [listener]}, daemon=True
    )
    monkeypatch.setattr(settings, "MCP_ALLOW_PRIVATE_NETWORKS", True)
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("ALL_PROXY", "http://127.0.0.1:1")
    monkeypatch.delenv("NO_PROXY", raising=False)
    config = MCPServerConfig(
        id=1,
        user_id=1,
        name="http-acceptance",
        transport="streamable_http",
        url=f"http://127.0.0.1:{port}/mcp",
        command=None,
        args=[],
        headers={},
        env={},
        revision="1",
    )

    async def exercise():
        manager = MCPManager()
        async with manager._session(config) as session:
            tools = await session.list_tools()
            assert [tool.name for tool in tools.tools] == ["echo"]
            result = await session.call_tool("echo", {"value": "sdk-upgrade-probe"})
            assert not result.is_error
            assert result.content[0].text == "sdk-upgrade-probe"

    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not runtime.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert runtime.started
        asyncio.run(exercise())
    finally:
        runtime.should_exit = True
        thread.join(timeout=10)
        listener.close()
    assert not thread.is_alive()
