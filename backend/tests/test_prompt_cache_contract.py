"""Stable wire prefixes and cache accounting, independent of a provider hit."""

from types import SimpleNamespace

import pytest

from app.core.model_provider_adapter import (
    ModelProviderAdapter,
    build_provider_request,
    build_anthropic_payload,
    normalize_openai_chunk,
)
from app.core.config import settings


def test_cache_prefix_stays_stable_when_current_memory_changes(monkeypatch):
    monkeypatch.setattr(settings, "ANTHROPIC_PROMPT_CACHE_ENABLED", True)
    tools = [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": "read",
                "parameters": {"type": "object", "properties": {}},
            },
        }
        for name in ["z", "a"]
    ]
    payloads = []
    for memory in ["old-memory", "new-memory"]:
        request = build_provider_request(
            messages=[
                {"role": "system", "content": "stable rules"},
                {"role": "user", "content": memory},
                {"role": "user", "content": "task"},
            ],
            tools=tools,
            max_tokens=100,
            temperature=0.2,
        )
        payloads.append(build_anthropic_payload(request))
        tools.reverse()
    assert payloads[0]["system"] == payloads[1]["system"]
    assert payloads[0]["tools"] == payloads[1]["tools"]
    assert payloads[0]["messages"] != payloads[1]["messages"]
    assert "cache_control" not in str(payloads[0]["messages"])
    monkeypatch.setattr(settings, "ANTHROPIC_PROMPT_CACHE_ENABLED", False)
    uncached = build_anthropic_payload(request)
    assert "cache_control" not in str(uncached)
    assert uncached["messages"] == payloads[1]["messages"]


@pytest.mark.parametrize(
    "usage",
    [
        {"prompt_tokens_details": {"cached_tokens": 800}},
        {"prompt_cache_hit_tokens": 800, "prompt_cache_miss_tokens": 200},
    ],
)
def test_cache_hits_do_not_reduce_logical_context_pressure(usage):
    event = normalize_openai_chunk(
        {
            "choices": [],
            "usage": {"prompt_tokens": 1000, "completion_tokens": 20, **usage},
        }
    )
    assert event.usage.prompt_tokens == 1000
    assert event.usage.cache_read_tokens == 800
    assert event.usage.cache_creation_tokens == 0


@pytest.mark.parametrize(
    "provider, supported",
    [("openai", True), ("deepseek", True), ("anthropic", True), ("custom", False)],
)
def test_cache_capability_is_not_inferred_from_openai_wire_compatibility(
    monkeypatch, provider, supported
):
    monkeypatch.setattr(settings, "ANTHROPIC_PROMPT_CACHE_ENABLED", True)
    adapter = ModelProviderAdapter(
        client=None, profile=SimpleNamespace(provider=provider)
    )
    assert adapter.prompt_cache_supported is supported
    assert adapter.prompt_cache_enabled is supported


@pytest.mark.parametrize("effort", ["none", "low", "high", "max"])
def test_deepseek_reasoning_policy_is_explicit_and_provider_specific(
    monkeypatch, effort
):
    from app.core.model_provider_adapter import _openai_payload, ProviderRequest

    monkeypatch.setattr(settings, "DEEPSEEK_REASONING_EFFORT", effort)
    request = ProviderRequest(
        system="rules", messages=[{"role": "user", "content": "task"}]
    )
    payload = _openai_payload(
        SimpleNamespace(provider="deepseek", model="test"), request
    )
    assert payload["extra_body"]["thinking"]["type"] == (
        "disabled" if effort == "none" else "enabled"
    )
    if effort != "none":
        assert payload["reasoning_effort"] == effort and "temperature" not in payload
    assert "extra_body" not in _openai_payload(
        SimpleNamespace(provider="custom", model="test"), request
    )
