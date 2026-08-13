"""ToolRegistry mechanics: registration, schemas, dispatch, manifest."""

import asyncio

import pytest


def test_tool_registry_has_expected_tools():
    from app.agent_runtime.tool_registry import registry

    expected = {
        "web_search",
        "read_url",
        "read_file",
        "write_file",
        "search_knowledge",
        "read_resume",
        "read_interview_history",
        "search_jobs",
        "task_create",
        "task_update",
        "read_career_context",
        "track_search_job",
        "record_career_event",
        "read_artifacts",
        "save_artifact",
        "start_mock_interview",
    }
    assert expected == set(registry.tool_names)


def test_openai_schemas_generated():
    from app.agent_runtime.tool_registry import registry

    schemas = registry.get_openai_schemas()
    assert len(schemas) == len(registry.tool_names)
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


def test_registry_schemas_are_deterministically_sorted():
    from app.agent_runtime.tool_registry import registry

    names = [schema["function"]["name"] for schema in registry.get_openai_schemas()]
    assert names == sorted(names)


def test_registry_does_not_duplicate_schema_in_prompt_guidance():
    from app.agent_runtime.tool_registry import registry

    guidance = registry.format_guidance()
    assert '"parameters"' not in guidance
    assert '"description"' not in guidance


def test_every_builtin_has_an_explicit_effect():
    from app.agent_runtime.tool_policy import ToolEffect
    from app.agent_runtime.tool_registry import registry

    assert all(
        registry.get(name).effect is not ToolEffect.UNKNOWN
        for name in registry.tool_names
    )
