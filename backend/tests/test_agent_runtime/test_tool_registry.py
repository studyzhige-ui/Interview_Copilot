"""ToolRegistry mechanics: registration, schemas, dispatch, manifest."""

import asyncio

import pytest
from pydantic import BaseModel


def test_tool_registry_has_expected_tools():
    from app.agent_runtime.tool_registry import registry

    expected = {
        "web_search",
        "read_url",
        "read_file",
        "inspect_attachment_pages",
        "write_file",
        "search_knowledge",
        "read_resume",
        "read_interview_history",
        "search_jobs",
        "task_create",
        "task_update",
        "read_career_context",
        "capture_job_description",
        "track_search_job",
        "record_career_event",
        "read_artifacts",
        "save_artifact",
        "start_mock_interview",
        "prepare_resume_profile_candidates",
        "resolve_resume_profile_candidates",
        "read_gmail_observations",
        "review_gmail_observation",
        "manage_personalization_guidance",
        "search_interaction_history",
        "read_interaction_history",
        "read_career_domain_state",
        "confirm_career_profile_change",
        "review_ability_signals",
        "manage_next_action",
        "start_interview_debrief",
        "analyze_offers",
        "manage_persistent_task",
        "record_artifact_submission",
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


def test_plan_call_validates_typed_args_and_preflights_without_dispatch():
    from app.agent_runtime.tool_policy import ToolEffect
    from app.agent_runtime.tool_registry import (
        AgentToolContext,
        ToolDefinition,
        ToolPreflightResult,
        ToolRegistry,
    )

    class Args(BaseModel):
        value: int

    dispatched = 0
    preflighted = 0

    async def handler(_args, _ctx):
        nonlocal dispatched
        dispatched += 1
        return {"ok": True}

    def preflight(args, _ctx):
        nonlocal preflighted
        preflighted += 1
        return ToolPreflightResult(
            connection_ready=False,
            resource_identities=(f"object:{args.value}",),
        )

    local = ToolRegistry()
    local._default_tools_loaded = True
    local.register(
        ToolDefinition(
            "typed",
            "typed",
            Args,
            handler,
            effect=ToolEffect.READ,
            concurrency_safe=True,
            preflight=preflight,
        )
    )
    ctx = AgentToolContext(user_id="alice", session_id="s1")
    invalid = asyncio.run(local.plan_call("typed", {"value": "no"}, ctx))
    valid = asyncio.run(local.plan_call("typed", {"value": 7}, ctx))

    assert invalid.error["error"] == "tool_args_validation_failed"
    assert valid.arguments == {"value": 7}
    assert valid.connection_ready is False
    assert valid.resource_identities == frozenset({"object:7"})
    assert preflighted == 1
    assert dispatched == 0
