from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.core.model_catalog import ModelProfile
from app.core.model_provider_adapter import (
    ModelProviderAdapter,
    ProviderRequest,
    build_anthropic_payload,
    build_provider_request,
)


def _profile(provider: str) -> ModelProfile:
    return ModelProfile(
        id=f"{provider}/test-model",
        provider=provider,
        display_name="Test",
        model="test-model",
        api_base="https://provider.example/v1",
        api_key_env="TEST_API_KEY",
        supports_function_calling=True,
    )


def _schemas() -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": "z_tool",
                "description": "Z",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "a_tool",
                "description": "A",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                },
            },
        },
    ]


def test_provider_request_keeps_three_partitions_and_sorts_tools():
    request = build_provider_request(
        messages=[
            {"role": "system", "content": "runtime rules"},
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "second"},
            {"role": "user", "content": "current"},
        ],
        tools=_schemas(),
        max_tokens=123,
        temperature=0.1,
    )

    assert request.system == "runtime rules"
    assert [message["role"] for message in request.messages] == [
        "user",
        "assistant",
        "user",
    ]
    assert [schema["function"]["name"] for schema in request.tools] == [
        "a_tool",
        "z_tool",
    ]
    assert request.tools == sorted(
        request.tools, key=lambda schema: schema["function"]["name"]
    )


def test_anthropic_payload_caches_only_non_private_tools_and_system(monkeypatch):
    monkeypatch.setattr(
        "app.core.model_provider_adapter.settings.ANTHROPIC_PROMPT_CACHE_ENABLED",
        True,
    )
    monkeypatch.setattr(
        "app.core.model_provider_adapter.settings.ANTHROPIC_PROMPT_CACHE_TTL",
        "5m",
    )
    request = ProviderRequest(
        system="stable system",
        tools=_schemas(),
        messages=[
            {"role": "user", "content": "start"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_7",
                        "type": "function",
                        "function": {
                            "name": "a_tool",
                            "arguments": '{"query":"jobs"}',
                        },
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call_7", "content": '{"ok":true}'},
            {"role": "user", "content": "finish"},
        ],
    )

    payload = build_anthropic_payload(request)
    marker = {"type": "ephemeral", "ttl": "5m"}
    assert payload["tools"][-1]["cache_control"] == marker
    assert payload["system"][-1]["cache_control"] == marker
    assert "cache_control" not in str(payload["messages"])

    # Schemas occur exactly once and the native order remains deterministic.
    assert [tool["name"] for tool in payload["tools"]] == ["z_tool", "a_tool"]
    assert "a_tool" not in str(payload["system"])

    assistant = payload["messages"][1]
    assert assistant["content"][0] == {
        "type": "tool_use",
        "id": "call_7",
        "name": "a_tool",
        "input": {"query": "jobs"},
    }
    assert payload["messages"][2]["content"][0]["tool_use_id"] == "call_7"


def test_disabling_anthropic_cache_keeps_identical_semantic_request(monkeypatch):
    request = ProviderRequest(
        system="rules",
        tools=_schemas(),
        messages=[{"role": "user", "content": "question"}],
    )
    monkeypatch.setattr(
        "app.core.model_provider_adapter.settings.ANTHROPIC_PROMPT_CACHE_ENABLED",
        True,
    )
    cached = build_anthropic_payload(request)
    monkeypatch.setattr(
        "app.core.model_provider_adapter.settings.ANTHROPIC_PROMPT_CACHE_ENABLED",
        False,
    )
    uncached = build_anthropic_payload(request)

    def strip_markers(value):
        if isinstance(value, dict):
            return {
                key: strip_markers(item)
                for key, item in value.items()
                if key != "cache_control"
            }
        if isinstance(value, list):
            return [strip_markers(item) for item in value]
        return value

    assert strip_markers(cached) == uncached


def test_anthropic_translation_drops_semantically_empty_messages(monkeypatch):
    monkeypatch.setattr(
        "app.core.model_provider_adapter.settings.ANTHROPIC_PROMPT_CACHE_ENABLED",
        True,
    )
    payload = build_anthropic_payload(
        ProviderRequest(
            system="rules",
            messages=[
                {"role": "user", "content": ""},
                {"role": "user", "content": "question"},
                {"role": "assistant", "content": ""},
            ],
        )
    )

    assert len(payload["messages"]) == 1
    assert payload["messages"][0]["role"] == "user"
    block = payload["messages"][0]["content"][0]
    assert block["text"] == "question"
    assert "cache_control" not in block
    assert not any(
        content.get("type") == "text" and content.get("text") == ""
        for message in payload["messages"]
        for content in message["content"]
    )


def test_anthropic_translation_rejects_request_without_semantic_messages():
    with pytest.raises(ValueError, match="semantic message"):
        build_anthropic_payload(
            ProviderRequest(system="rules", messages=[{"role": "user", "content": ""}])
        )


def test_native_anthropic_stream_normalizes_tool_and_cache_usage(monkeypatch):
    captured: dict = {}

    async def events():
        yield SimpleNamespace(
            type="message_start",
            message=SimpleNamespace(
                usage=SimpleNamespace(
                    input_tokens=11,
                    cache_read_input_tokens=50,
                    cache_creation_input_tokens=7,
                )
            ),
        )
        yield SimpleNamespace(
            type="content_block_start",
            index=2,
            content_block=SimpleNamespace(
                type="tool_use", id="call_1", name="a_tool", input={}
            ),
        )
        yield SimpleNamespace(
            type="content_block_delta",
            index=2,
            delta=SimpleNamespace(
                type="input_json_delta", partial_json='{"query":"jobs"}'
            ),
        )
        yield SimpleNamespace(
            type="message_delta",
            delta=SimpleNamespace(stop_reason="tool_use"),
            usage=SimpleNamespace(output_tokens=9),
        )

    class Messages:
        async def create(self, **kwargs):
            captured.update(kwargs)
            return events()

    adapter = ModelProviderAdapter(
        client=SimpleNamespace(messages=Messages()),
        profile=_profile("anthropic"),
    )

    async def drain():
        stream = await adapter.start_stream(
            ProviderRequest(
                system="rules",
                messages=[{"role": "user", "content": "question"}],
                tools=_schemas(),
            )
        )
        return [event async for event in stream]

    normalized = asyncio.run(drain())
    assert captured["model"] == "test-model"
    assert "stream_options" not in captured
    assert "temperature" not in captured
    usage = normalized[0].usage
    assert usage is not None
    assert usage.prompt_tokens == 68
    assert usage.cache_read_tokens == 50
    assert usage.cache_creation_tokens == 7
    assert normalized[1].tool_call_deltas[0].call_id == "call_1"
    assert normalized[2].tool_call_deltas[0].arguments_delta == '{"query":"jobs"}'
    assert normalized[3].usage.completion_tokens == 9
    assert normalized[3].stop_reason == "tool_use"


def test_unsupported_provider_sends_full_request_without_cache_fields():
    captured: dict = {}

    async def events():
        yield SimpleNamespace(
            usage=SimpleNamespace(prompt_tokens=4, completion_tokens=2),
            choices=[],
        )

    class Completions:
        async def create(self, **kwargs):
            captured.update(kwargs)
            return events()

    adapter = ModelProviderAdapter(
        client=SimpleNamespace(
            chat=SimpleNamespace(completions=Completions()),
        ),
        profile=_profile("openai"),
    )

    async def drain():
        stream = await adapter.start_stream(
            ProviderRequest(
                system="rules",
                messages=[{"role": "user", "content": "question"}],
                tools=_schemas(),
            )
        )
        return [event async for event in stream]

    normalized = asyncio.run(drain())
    assert adapter.prompt_cache_supported is False
    assert captured["messages"][0] == {"role": "system", "content": "rules"}
    assert captured["messages"][-1]["content"] == "question"
    assert [tool["function"]["name"] for tool in captured["tools"]] == [
        "z_tool",
        "a_tool",
    ]
    assert "cache_control" not in str(captured)
    assert normalized[0].usage.prompt_tokens == 4
