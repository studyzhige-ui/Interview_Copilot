"""Tests for the new ToolRegistry-based agent tools."""

import asyncio

import pytest


def test_tool_registry_has_expected_tools():
    from app.agent_runtime.tool_registry import registry

    expected = {
        "web_search", "read_url", "read_file", "write_file",
        "recall_memory", "save_memory", "search_knowledge",
        "read_resume", "read_interview_history", "search_jobs",
    }
    assert expected == set(registry.tool_names)


def test_openai_schemas_generated():
    from app.agent_runtime.tool_registry import registry

    schemas = registry.get_openai_schemas()
    assert len(schemas) >= 9  # web_search excluded when TAVILY_API_KEY is not set
    for schema in schemas:
        assert schema["type"] == "function"
        assert "name" in schema["function"]
        assert "parameters" in schema["function"]


def test_dispatch_unknown_tool():
    from app.agent_runtime.tool_registry import AgentToolContext, registry

    ctx = AgentToolContext(user_id="alice", session_id="s1")
    result = asyncio.run(registry.dispatch("nonexistent_tool", {}, ctx))
    assert result["error"] == "unknown_tool"


def test_parse_tool_arguments_valid():
    from app.agent_runtime.tool_registry import parse_tool_arguments

    result = parse_tool_arguments('{"query": "test"}')
    assert result == {"query": "test"}


def test_parse_tool_arguments_invalid():
    from app.agent_runtime.tool_registry import parse_tool_arguments

    with pytest.raises(ValueError):
        parse_tool_arguments("not json")


def test_format_manifest():
    from app.agent_runtime.tool_registry import registry

    manifest = registry.format_manifest()
    assert "web_search" in manifest
    assert "read_resume" in manifest
