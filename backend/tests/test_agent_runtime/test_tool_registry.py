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
        "recall_memory",
        "save_memory",
        "search_knowledge",
        "read_resume",
        "read_interview_history",
        "search_jobs",
        "task_create",
        "task_update",
        "task_get",
        "task_list",
        "task_verify",
        "task_checkpoint",
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


def test_registry_exclude_hides_tools_symmetrically():
    """``exclude`` must drop a tool from BOTH the manifest AND the
    OpenAI schemas — otherwise the LLM sees a tool in one place but
    not the other and gets confused. The agent strategy relies on
    this symmetry to gate memory tools when the global-memory
    toggle is off (Claude Code's ``isAutoMemoryEnabled=false``
    semantics).
    """
    from app.agent_runtime.tool_registry import registry

    memory_tools = {"recall_memory", "save_memory"}

    schemas = registry.get_openai_schemas(exclude=memory_tools)
    schema_names = {s["function"]["name"] for s in schemas}
    assert "recall_memory" not in schema_names
    assert "save_memory" not in schema_names
    # Non-memory tools still present.
    assert "read_resume" in schema_names
    assert "search_jobs" in schema_names

    manifest = registry.format_manifest(exclude=memory_tools)
    assert "recall_memory" not in manifest
    assert "save_memory" not in manifest
    assert "read_resume" in manifest


def test_result_summary_detects_disabled_payload():
    """``recall_memory`` returning ``{"disabled": true, "reason": ...}``
    must NOT fall through to the byte-counter "完成 (N chars)" fallback.

    Pre-fix screenshot evidence: user toggled global memory OFF, the
    LLM called recall_memory anyway, got back the 273-char
    ``{"disabled": true, "reason": "用户已关闭..."}`` payload, and
    the UI rendered "✅ 完成 (273 chars)" — looked like a successful
    call to a casual user. We surface the disabled signal explicitly
    so the summary is honest.
    """
    from app.agent_runtime.react_agent import _result_summary

    s = _result_summary(
        {
            "disabled": True,
            "reason": "用户已关闭全局记忆开关",
            "user_profile": "",
        }
    )
    assert s.startswith("⊘")
    assert "已关闭" in s
    assert "完成" not in s  # MUST NOT use the success template

    # Sanity check the existing branches still fire.
    assert _result_summary({"error": "boom"}).startswith("❌")
    assert _result_summary({"count": 0}) == "返回 0 条结果"
    assert _result_summary({"count": 5}) == "返回 5 条结果"
