import asyncio

import pytest
from pydantic import ValidationError


def test_tool_permission_blocks_unknown_site():
    from app.agent_runtime.tools import AgentToolContext, build_default_tool_registry

    registry = build_default_tool_registry()
    tool = registry["search_jobs"]
    ctx = AgentToolContext(user_id="alice", session_id="s1")

    result = asyncio.run(
        tool.execute(
            {
                "keywords": "python backend",
                "sites": ["unauthorized-site"],
            },
            ctx,
        )
    )
    assert result["error"] == "unauthorized site requested"


def test_tool_args_validation_error():
    from app.agent_runtime.tools import AgentToolContext, build_default_tool_registry

    registry = build_default_tool_registry()
    tool = registry["search_interview_qa"]
    ctx = AgentToolContext(user_id="alice", session_id="s1")

    with pytest.raises(ValidationError):
        asyncio.run(tool.execute({"query": ""}, ctx))


def test_openai_schema_contains_strict_flag():
    from app.agent_runtime.tools import build_default_tool_registry
    from app.core.config import settings

    registry = build_default_tool_registry()
    schema = registry["search_jobs"].to_openai_tool()

    if settings.AGENT_TOOL_SCHEMA_STRICT:
        assert schema["function"]["strict"] is True
