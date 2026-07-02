"""Tests for the vendor adapter base (P7-A).

Locked behaviours:
  - 9 vendor spec files are all importable + registered in ALL_SPECS
  - Each spec's chat_filter correctly drops the non-chat hints we saw
    in the live verification responses
  - fetch_one_vendor:
      * No api_key → empty list, no HTTP call
      * Bearer / x-api-key / url-key auth styles all produce the right
        request shape (header vs query param)
      * 4xx is non-retryable (no retry burned)
      * 5xx triggers one retry
      * Schema-invalid response raises VendorFetchFailed
      * Per-vendor strip_id_prefix (Gemini's "models/") works
      * Recency sort: timestamp desc primary, reverse-alpha secondary
      * NVIDIA NIM's sentinel timestamp (735790403) gets ignored
"""
from __future__ import annotations

import httpx
import pytest

from app.services.model_sources.vendors import ALL_SPECS, get_spec
from app.services.model_sources.vendors import base as base_mod
from app.services.model_sources.vendors.base import (
    VendorAdapterSpec,
    VendorFetchFailed,
    fetch_one_vendor,
)


# ── Registry sanity ─────────────────────────────────────────────────


def test_all_nine_specs_registered():
    """Adding/removing a vendor MUST go through the central registry."""
    ids = sorted(s.provider for s in ALL_SPECS)
    assert ids == sorted([
        "openai", "anthropic", "gemini", "deepseek", "nvidia_nim",
        "xiaomi", "moonshot", "zai", "qwen",
    ])


def test_get_spec_returns_none_for_unknown():
    assert get_spec("nope") is None
    assert get_spec("openai") is not None


# ── Per-vendor chat_filter regressions ──────────────────────────────


@pytest.mark.parametrize("vendor,bare_id,kept", [
    # OpenAI — drop non-chat families
    ("openai", "gpt-5.5",                  True),
    ("openai", "gpt-5.5-pro",              True),
    ("openai", "gpt-4o-mini",              True),
    ("openai", "text-embedding-3-small",   False),
    ("openai", "whisper-1",                False),
    ("openai", "dall-e-3",                 False),
    ("openai", "gpt-realtime-2",           False),
    ("openai", "gpt-5.5-search-api",       False),
    ("openai", "gpt-image-2",              False),
    ("openai", "tts-1",                    False),
    ("openai", "chat-latest",              False),

    # NVIDIA NIM — drop embed/safety/translate/parse/retriever
    ("nvidia_nim", "meta/llama-3.1-70b-instruct",         True),
    ("nvidia_nim", "deepseek-ai/deepseek-v4-pro",         True),
    ("nvidia_nim", "nvidia/nv-embedqa-mistral-7b-v2",     False),
    ("nvidia_nim", "nvidia/llama-3.1-nemoguard-8b-content-safety", False),
    ("nvidia_nim", "nvidia/nemotron-content-safety-reasoning-4b", False),
    ("nvidia_nim", "nvidia/riva-translate-4b-instruct",   False),
    ("nvidia_nim", "nvidia/nemotron-parse",               False),
    ("nvidia_nim", "nvidia/nemoretriever-parse",          False),
    ("nvidia_nim", "nvidia/nvclip",                       False),

    # Qwen — keep only qwen* brand, drop third-party + non-chat variants
    ("qwen", "qwen3-max",                  True),
    ("qwen", "qwen3-coder-plus",           True),
    ("qwen", "qwq-32b-preview",            True),
    ("qwen", "ZHIPU/GLM-5",                False),   # third-party gateway
    ("qwen", "deepseek-v3.1",              False),   # third-party gateway
    ("qwen", "qwen3-vl-image-plus",        False),   # image variant
    ("qwen", "qwen-asr-realtime",          False),
    ("qwen", "text-embedding-v3",          False),
])
def test_chat_filter(vendor, bare_id, kept):
    spec = get_spec(vendor)
    if spec.chat_filter is None:
        # Vendors without a filter keep everything.
        assert kept is True, f"{vendor} has no filter — test row should expect kept=True"
    else:
        # Pass an entry shape sufficient for the filter (some inspect
        # ``supportedGenerationMethods``).
        entry = {"id": bare_id, "supportedGenerationMethods": ["generateContent"]}
        assert spec.chat_filter(entry, bare_id) is kept, \
            f"{vendor} chat_filter({bare_id!r}) expected kept={kept}"


def test_gemini_filter_uses_supported_generation_methods():
    """The single cleanest filter signal: only models with
    'generateContent' in supportedGenerationMethods are chat."""
    spec = get_spec("gemini")
    chat_row = {"name": "models/gemini-2.5-flash",
                "supportedGenerationMethods": ["generateContent", "countTokens"]}
    embed_row = {"name": "models/gemini-embedding-001",
                 "supportedGenerationMethods": ["embedContent"]}
    assert spec.chat_filter(chat_row, "gemini-2.5-flash") is True
    assert spec.chat_filter(embed_row, "gemini-embedding-001") is False


# ── fetch_one_vendor via httpx MockTransport ─────────────────────────


def _install_transport(monkeypatch, handler):
    transport = httpx.MockTransport(handler)
    real_cls = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = transport
        return real_cls(*args, **kwargs)

    monkeypatch.setattr(base_mod.httpx, "AsyncClient", factory)


@pytest.mark.asyncio
async def test_fetch_returns_empty_when_no_key(monkeypatch):
    """No api_key → no HTTP call, empty list (not an exception)."""
    spec = get_spec("openai")
    called = {"n": 0}
    def handler(request):
        called["n"] += 1
        return httpx.Response(200, json={"data": []})
    _install_transport(monkeypatch, handler)
    out = await fetch_one_vendor(spec, "https://api.openai.com/v1", "")
    assert out == []
    assert called["n"] == 0, "must NOT hit HTTP when api_key empty"


@pytest.mark.asyncio
async def test_fetch_bearer_auth_header(monkeypatch):
    """OpenAI-style ``Authorization: Bearer`` is sent."""
    captured = {}
    def handler(request):
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        return httpx.Response(200, json={"data": []})
    _install_transport(monkeypatch, handler)
    await fetch_one_vendor(get_spec("openai"), "https://api.openai.com/v1", "sk-test")
    assert captured["headers"].get("authorization") == "Bearer sk-test"
    assert captured["url"].endswith("/models")


@pytest.mark.asyncio
async def test_fetch_anthropic_uses_xapi_and_version(monkeypatch):
    """Anthropic auth: x-api-key + anthropic-version header. Bearer must NOT appear."""
    captured = {}
    def handler(request):
        captured["headers"] = dict(request.headers)
        return httpx.Response(200, json={"data": []})
    _install_transport(monkeypatch, handler)
    await fetch_one_vendor(get_spec("anthropic"), "https://api.anthropic.com/v1", "sk-ant-x")
    assert captured["headers"].get("x-api-key") == "sk-ant-x"
    assert captured["headers"].get("anthropic-version") == "2023-06-01"
    assert "authorization" not in captured["headers"]


@pytest.mark.asyncio
async def test_fetch_gemini_url_key(monkeypatch):
    """Gemini sends key as URL query param, NOT auth header."""
    captured = {}
    def handler(request):
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        return httpx.Response(200, json={"models": []})
    _install_transport(monkeypatch, handler)
    await fetch_one_vendor(
        get_spec("gemini"),
        "https://generativelanguage.googleapis.com/v1beta",
        "AIza-test",
    )
    assert "key=AIza-test" in captured["url"]
    assert "authorization" not in captured["headers"]
    assert "x-api-key" not in captured["headers"]


@pytest.mark.asyncio
async def test_fetch_4xx_no_retry(monkeypatch):
    """4xx is non-retryable — bad key / wrong URL / API gate."""
    attempts = {"n": 0}
    def handler(request):
        attempts["n"] += 1
        return httpx.Response(401, text="Invalid auth")
    _install_transport(monkeypatch, handler)
    with pytest.raises(VendorFetchFailed, match="HTTP 401"):
        await fetch_one_vendor(get_spec("openai"), "https://x", "sk-bad")
    assert attempts["n"] == 1, "401 must not trigger a retry"


@pytest.mark.asyncio
async def test_fetch_5xx_retries_once(monkeypatch):
    """5xx triggers one retry — covers the transient-failure case."""
    attempts = {"n": 0}
    def handler(request):
        attempts["n"] += 1
        if attempts["n"] == 1:
            return httpx.Response(503, text="upstream down")
        return httpx.Response(200, json={"data": [{"id": "x"}]})
    _install_transport(monkeypatch, handler)
    out = await fetch_one_vendor(get_spec("deepseek"), "https://x", "sk-test")
    assert attempts["n"] == 2
    assert len(out) == 1


@pytest.mark.asyncio
async def test_fetch_gemini_strips_models_prefix(monkeypatch):
    payload = {"models": [
        {"name": "models/gemini-2.5-flash",
         "displayName": "Gemini 2.5 Flash",
         "supportedGenerationMethods": ["generateContent"]},
    ]}
    _install_transport(monkeypatch, lambda r: httpx.Response(200, json=payload))
    out = await fetch_one_vendor(get_spec("gemini"), "https://x", "k")
    assert out[0].model == "gemini-2.5-flash"          # stripped
    assert out[0].display_name == "Gemini 2.5 Flash"   # from displayName field


@pytest.mark.asyncio
async def test_fetch_anthropic_uses_display_name_field(monkeypatch):
    payload = {"data": [
        {"id": "claude-opus-4-7", "display_name": "Claude Opus 4.7",
         "created_at": "2026-04-14T00:00:00Z",
         "max_input_tokens": 1_000_000, "max_tokens": 128_000},
    ]}
    _install_transport(monkeypatch, lambda r: httpx.Response(200, json=payload))
    out = await fetch_one_vendor(get_spec("anthropic"), "https://x", "sk-ant-x")
    assert out[0].display_name == "Claude Opus 4.7"
    assert out[0].context_window == 1_000_000
    assert out[0].max_output_tokens == 128_000


@pytest.mark.asyncio
async def test_fetch_sorts_newest_first_by_timestamp(monkeypatch):
    """Sort: timestamp desc primary, reverse-alpha secondary."""
    payload = {"data": [
        {"id": "gpt-4o",      "created": 1_700_000_000},
        {"id": "gpt-5.5",     "created": 1_900_000_000},   # newest
        {"id": "gpt-5.2",     "created": 1_850_000_000},
        {"id": "gpt-4.1",     "created": 1_750_000_000},
    ]}
    _install_transport(monkeypatch, lambda r: httpx.Response(200, json=payload))
    out = await fetch_one_vendor(get_spec("openai"), "https://x", "sk-x")
    # Pure timestamp-desc sort: 1.9B > 1.85B > 1.75B > 1.7B
    assert [e.model for e in out] == ["gpt-5.5", "gpt-5.2", "gpt-4.1", "gpt-4o"]


@pytest.mark.asyncio
async def test_fetch_nvidia_ignores_sentinel_timestamp(monkeypatch):
    """NVIDIA ships ``created=735790403`` for every entry — a 1993
    sentinel. Sort must fall through to reverse-alpha for these."""
    payload = {"data": [
        {"id": "meta/llama-3.1-70b-instruct", "created": 735790403},
        {"id": "deepseek-ai/deepseek-v4-pro", "created": 735790403},
        {"id": "meta/llama-3.3-70b-instruct", "created": 735790403},
    ]}
    _install_transport(monkeypatch, lambda r: httpx.Response(200, json=payload))
    out = await fetch_one_vendor(get_spec("nvidia_nim"), "https://x", "nv-x")
    # Reverse-alpha: 'meta/llama-3.3' > 'meta/llama-3.1' > 'deepseek-ai/...'
    ids = [e.model for e in out]
    assert ids[0] == "meta/llama-3.3-70b-instruct"
    assert ids[-1] == "deepseek-ai/deepseek-v4-pro"


@pytest.mark.asyncio
async def test_fetch_dedupes_repeated_ids(monkeypatch):
    """NVIDIA ships some ids twice — keep the first occurrence."""
    payload = {"data": [
        {"id": "openai/gpt-oss-120b", "created": 735790403},
        {"id": "openai/gpt-oss-120b", "created": 735790403},
        {"id": "openai/gpt-oss-20b",  "created": 735790403},
    ]}
    _install_transport(monkeypatch, lambda r: httpx.Response(200, json=payload))
    out = await fetch_one_vendor(get_spec("nvidia_nim"), "https://x", "nv-x")
    ids = [e.model for e in out]
    assert ids.count("openai/gpt-oss-120b") == 1


@pytest.mark.asyncio
async def test_fetch_rejects_top_level_non_dict(monkeypatch):
    _install_transport(monkeypatch, lambda r: httpx.Response(200, json=["not", "a", "dict"]))
    with pytest.raises(VendorFetchFailed, match="not a dict"):
        await fetch_one_vendor(get_spec("openai"), "https://x", "k")


@pytest.mark.asyncio
async def test_fetch_rejects_missing_response_key(monkeypatch):
    _install_transport(monkeypatch, lambda r: httpx.Response(200, json={"wrong_key": []}))
    with pytest.raises(VendorFetchFailed, match="data"):
        await fetch_one_vendor(get_spec("openai"), "https://x", "k")
