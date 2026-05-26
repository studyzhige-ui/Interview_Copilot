"""Tests for ``app.services.model_sources.litellm_loader`` (P6-L).

What's locked in here:

  - LiteLLM JSON parsing extracts the right fields and drops the right rows
  - Chat-only filter handles ``mode == chat``, missing mode (name heuristic),
    and unrecognised modes
  - Unknown ``litellm_provider`` rows get dropped (not surfaced as ghosts)
  - HTTP retry semantics: one retry on transient, immediate fail on 4xx
  - Schema validation rejects pathological input BEFORE the cache writes
  - Dedupe on (provider, model) pair
"""
from __future__ import annotations

import httpx
import pytest

from app.services.model_sources import litellm_loader
from app.services.model_sources.base import ProviderDefaults
from app.services.model_sources.litellm_loader import (
    LiteLLMFetchFailed,
    _is_chat_entry,
    _looks_like_model_id,
    _validate_and_extract,
    fetch_litellm_catalog,
)


# ── Schema validation / extraction ───────────────────────────────────────


def _stub_providers(monkeypatch, providers):
    """Replace PROVIDERS lookup so we don't depend on the live registry."""
    def lookup(pid):
        return providers.get(pid)
    monkeypatch.setattr(litellm_loader, "get_provider_defaults", lookup)


def _pd(pid):
    return ProviderDefaults(
        id=pid, display_label=pid.title(), default_api_base="https://x",
        api_key_env=f"{pid.upper()}_API_KEY",
    )


def test_validate_rejects_non_dict_top_level():
    with pytest.raises(LiteLLMFetchFailed, match="must be a dict"):
        _validate_and_extract([1, 2, 3])


def test_validate_rejects_empty_dict():
    with pytest.raises(LiteLLMFetchFailed, match="empty"):
        _validate_and_extract({})


def test_validate_rejects_input_that_yields_zero_after_filtering(monkeypatch):
    """All-non-chat input → fail, NOT silent empty (would nuke the cache)."""
    _stub_providers(monkeypatch, {"openai": _pd("openai")})
    with pytest.raises(LiteLLMFetchFailed, match="no entries matched"):
        _validate_and_extract({
            "text-embedding-3-small": {
                "litellm_provider": "openai", "mode": "embedding",
                "max_input_tokens": 8192, "max_output_tokens": 0,
            },
        })


def test_validate_extracts_chat_models(monkeypatch):
    _stub_providers(monkeypatch, {"openai": _pd("openai"), "anthropic": _pd("anthropic")})
    grouped = _validate_and_extract({
        "sample_spec": {"foo": "bar"},  # LiteLLM's schema-doc row — ignored
        "gpt-4o": {
            "litellm_provider": "openai", "mode": "chat",
            "max_input_tokens": 128_000, "max_output_tokens": 16_384,
            "supports_function_calling": True, "supports_vision": True,
        },
        "claude-opus-4-7": {
            "litellm_provider": "anthropic", "mode": "chat",
            "max_input_tokens": 200_000, "max_output_tokens": 8_192,
            "supports_function_calling": True,
        },
    })
    assert set(grouped.keys()) == {"openai", "anthropic"}
    openai_models = {e.model: e for e in grouped["openai"]}
    assert "gpt-4o" in openai_models
    assert openai_models["gpt-4o"].supports_function_calling is True
    assert openai_models["gpt-4o"].context_window == 128_000
    assert openai_models["gpt-4o"].max_output_tokens == 16_384
    assert openai_models["gpt-4o"].supports_vision is True
    # Display name should be capitalised
    assert openai_models["gpt-4o"].display_name == "GPT-4o"


def test_validate_drops_unknown_providers(monkeypatch):
    """A LiteLLM provider we don't ship support for gets skipped."""
    _stub_providers(monkeypatch, {"openai": _pd("openai")})
    grouped = _validate_and_extract({
        "gpt-4o": {"litellm_provider": "openai", "mode": "chat"},
        "claude-3": {"litellm_provider": "anthropic", "mode": "chat"},  # provider not registered
        "magic-llm": {"litellm_provider": "exotic_vendor", "mode": "chat"},  # ditto
    })
    assert set(grouped.keys()) == {"openai"}
    assert [e.model for e in grouped["openai"]] == ["gpt-4o"]


def test_validate_filters_non_chat_modes(monkeypatch):
    _stub_providers(monkeypatch, {"openai": _pd("openai")})
    grouped = _validate_and_extract({
        "gpt-4o": {"litellm_provider": "openai", "mode": "chat"},
        "text-embedding-3-small": {"litellm_provider": "openai", "mode": "embedding"},
        "whisper-1": {"litellm_provider": "openai", "mode": "audio_transcription"},
        "dall-e-3": {"litellm_provider": "openai", "mode": "image_generation"},
    })
    ids = [e.model for e in grouped["openai"]]
    assert ids == ["gpt-4o"]


def test_validate_keeps_entries_with_missing_mode_by_name_heuristic(monkeypatch):
    """``mode`` absent → fall back to the name heuristic so genuine chat
    models whose PR forgot the mode field still surface."""
    _stub_providers(monkeypatch, {"openai": _pd("openai")})
    grouped = _validate_and_extract({
        "gpt-4o-newest": {"litellm_provider": "openai"},          # no mode → kept
        "text-embedding-99": {"litellm_provider": "openai"},      # 'embedding' substring → dropped
    })
    ids = [e.model for e in grouped["openai"]]
    assert "gpt-4o-newest" in ids
    assert "text-embedding-99" not in ids


def test_validate_dedupes_same_pair(monkeypatch):
    _stub_providers(monkeypatch, {"openai": _pd("openai")})
    grouped = _validate_and_extract({
        "gpt-4o": {"litellm_provider": "openai", "mode": "chat"},
        "openai/gpt-4o": {"litellm_provider": "openai", "mode": "chat"},  # same bare model
    })
    # Only one entry survives the (provider, bare_model) dedupe.
    ids = [e.model for e in grouped["openai"]]
    assert ids.count("gpt-4o") == 1


def test_validate_robust_int_coercion(monkeypatch):
    _stub_providers(monkeypatch, {"openai": _pd("openai")})
    grouped = _validate_and_extract({
        "gpt-4o-str": {
            "litellm_provider": "openai", "mode": "chat",
            "max_input_tokens": "200000",
            "max_output_tokens": 8_192.5,
        },
    })
    entry = grouped["openai"][0]
    assert entry.context_window == 200_000  # string coerced
    assert entry.max_output_tokens == 8_192  # float coerced


def test_looks_like_model_id_rejects_garbage():
    assert not _looks_like_model_id("")
    assert not _looks_like_model_id("sample_spec")
    assert not _looks_like_model_id("foo bar")          # space
    assert not _looks_like_model_id('foo"bar')          # quote
    assert not _looks_like_model_id("a" * 201)          # too long
    assert _looks_like_model_id("openai/gpt-4o")
    assert _looks_like_model_id("claude-3-7-sonnet-20250219")
    assert _looks_like_model_id("ft:gpt-4@v1")


def test_is_chat_entry_handles_responses_mode():
    """OpenAI's newer 'responses' mode should pass the chat filter."""
    assert _is_chat_entry({"mode": "responses"}, "any-id") is True


def test_is_chat_entry_drops_unrecognised_mode():
    assert _is_chat_entry({"mode": "wildtype"}, "gpt-mystery") is False


# ── Live HTTP via MockTransport ──────────────────────────────────────────


def _install_transport(monkeypatch, handler):
    """Replace ``httpx.AsyncClient`` with one whose transport runs ``handler``."""
    transport = httpx.MockTransport(handler)
    real_cls = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = transport
        return real_cls(*args, **kwargs)

    monkeypatch.setattr(litellm_loader.httpx, "AsyncClient", factory)


@pytest.mark.asyncio
async def test_fetch_happy_path(monkeypatch):
    _stub_providers(monkeypatch, {"openai": _pd("openai")})
    payload = {
        "gpt-4o": {"litellm_provider": "openai", "mode": "chat", "max_input_tokens": 128000},
    }
    _install_transport(monkeypatch, lambda req: httpx.Response(200, json=payload))
    result = await fetch_litellm_catalog()
    assert set(result.keys()) == {"openai"}
    assert result["openai"][0].model == "gpt-4o"


@pytest.mark.asyncio
async def test_fetch_4xx_fails_immediately_no_retry(monkeypatch):
    """4xx is a config bug — retrying would just burn time."""
    attempt_count = {"n": 0}

    def handler(request):
        attempt_count["n"] += 1
        return httpx.Response(404, text="not found")

    _install_transport(monkeypatch, handler)
    with pytest.raises(LiteLLMFetchFailed, match="non-retryable HTTP 404"):
        await fetch_litellm_catalog()
    assert attempt_count["n"] == 1, "404 must not trigger a retry"


@pytest.mark.asyncio
async def test_fetch_5xx_retries_once(monkeypatch):
    _stub_providers(monkeypatch, {"openai": _pd("openai")})
    attempt_count = {"n": 0}
    payload = {"gpt-4o": {"litellm_provider": "openai", "mode": "chat"}}

    def handler(request):
        attempt_count["n"] += 1
        if attempt_count["n"] == 1:
            return httpx.Response(503, text="service down")
        return httpx.Response(200, json=payload)

    _install_transport(monkeypatch, handler)
    result = await fetch_litellm_catalog()
    assert attempt_count["n"] == 2, "should retry once after transient 5xx"
    assert "openai" in result


@pytest.mark.asyncio
async def test_fetch_exhausts_retries_and_raises(monkeypatch):
    def handler(request):
        return httpx.Response(503, text="still down")

    _install_transport(monkeypatch, handler)
    with pytest.raises(LiteLLMFetchFailed, match="fetch failed after"):
        await fetch_litellm_catalog()


@pytest.mark.asyncio
async def test_fetch_validates_schema_and_raises_on_garbage(monkeypatch):
    """Layer 2 protection: malformed JSON content must not poison cache."""
    _install_transport(
        monkeypatch, lambda req: httpx.Response(200, json={"not": "a model registry"}),
    )
    # The single-item dict doesn't pass the schema, so we expect failure.
    _stub_providers(monkeypatch, {"openai": _pd("openai")})
    with pytest.raises(LiteLLMFetchFailed):
        await fetch_litellm_catalog()
