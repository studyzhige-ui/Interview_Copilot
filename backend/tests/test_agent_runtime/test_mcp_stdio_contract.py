"""Real MCP SDK client/server handshake, discovery, validation and execution."""

import asyncio
import json
import sys

from app.agent_runtime.mcp.manager import MCPManager
from app.core.config import settings
from app.services.capabilities.mcp_server_service import MCPServerConfig


def test_real_stdio_server_roundtrip_and_error_contract(tmp_path, monkeypatch):
    server = tmp_path / "server.py"
    server.write_text(
        """from mcp.server.fastmcp import FastMCP
mcp = FastMCP("contract")
@mcp.tool()
def add(a: int, b: int) -> dict:
    return {"sum": a + b}
@mcp.tool()
def fail() -> dict:
    raise ValueError("intentional failure")
mcp.run(transport="stdio")
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "APP_EDITION", "community")
    monkeypatch.setattr(settings, "MCP_ALLOW_STDIO", True)
    monkeypatch.setattr(settings, "AGENT_TOOL_TIMEOUT_SECONDS", 20)
    config = MCPServerConfig(
        id=1,
        user_id=1,
        name="contract",
        transport="stdio",
        command=sys.executable,
        args=[str(server)],
        url=None,
        headers={},
        env={},
        revision="1",
    )

    async def run():
        manager = MCPManager()
        try:
            tools = {
                tool.remote_name: tool for tool in await manager.list_tools(config)
            }
            assert set(tools) == {"add", "fail"}
            result = await manager.call_tool(config, tools["add"], {"a": 2, "b": 3})
            assert json.loads(result["result"]["content"][0]["text"]) == {"sum": 5}
            invalid = await manager.call_tool(
                config, tools["add"], {"a": "not an integer", "b": 3}
            )
            assert invalid["error"] == "tool_args_validation_failed"
            failed = await manager.call_tool(config, tools["fail"], {})
            assert failed["error"] == "mcp_tool_error"
            assert failed["result"]["isError"] is True
        finally:
            await manager.close_all()
        assert manager.status(1, 1) is None

    asyncio.run(run())
