"""Tests for ``app.services.model_sources.pipeline`` (P6-L).

Locked behaviours:

  - refresh_catalog → persists per-provider Redis entries + LKG snapshot
  - On fetch failure, returns the LKG snapshot (cache stays put)
  - load_catalog falls back to LKG when per-provider TTL expired
  - Schema-drift entries get silently dropped on deserialize
"""
from __future__ import annotations

import json

import pytest

from app.services.model_sources import pipeline as pipeline_mod
from app.services.model_sources.base import ModelEntry


class _FakeRedis:
    """Async stand-in. Tracks gets/sets/deletes; serves stored data."""
    def __init__(self):
        self.store: dict[str, str] = {}
        self.set_calls: list[tuple[str, str, int | None]] = []

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, ex=None):
        self.store[key] = value
        self.set_calls.append((key, value, ex))
        return True

    async def delete(self, key):
        return 1 if self.store.pop(key, None) is not None else 0


def _entry(provider: str, model: str, **overrides) -> ModelEntry:
    base = {
        "provider": provider, "model": model, "display_name": model,
        "supports_function_calling": True,
        "context_window": 128_000,
        "max_output_tokens": 4_096,
        "supports_vision": False,
    }
    base.update(overrides)
    return ModelEntry(**base)


@pytest.fixture
def fake_redis(monkeypatch):
    fr = _FakeRedis()
    monkeypatch.setattr(pipeline_mod, "redis_client", fr)
    return fr


# ── refresh_catalog ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_refresh_catalog_writes_per_provider_and_lkg(monkeypatch, fake_redis):
    """A successful fetch writes one Redis key per provider AND the LKG sentinel."""
    async def fake_fetch():
        return {
            "openai": [_entry("openai", "gpt-4o")],
            "anthropic": [_entry("anthropic", "claude-opus-4-7")],
        }
    monkeypatch.setattr(pipeline_mod, "fetch_litellm_catalog", fake_fetch)

    out = await pipeline_mod.refresh_catalog()
    assert set(out.keys()) == {"openai", "anthropic"}

    # Per-provider keys with TTL.
    keys_with_ttl = {k for (k, _v, ttl) in fake_redis.set_calls if ttl is not None}
    assert "model_catalog:v4:openai" in keys_with_ttl
    assert "model_catalog:v4:anthropic" in keys_with_ttl

    # LKG sentinel without TTL.
    lkg_writes = [(k, v, ttl) for (k, v, ttl) in fake_redis.set_calls if ttl is None]
    assert len(lkg_writes) == 1
    lkg_key, lkg_value, _ = lkg_writes[0]
    assert lkg_key == "model_catalog:v4:_last_known_good"
    snapshot = json.loads(lkg_value)
    assert set(snapshot.keys()) == {"openai", "anthropic"}


@pytest.mark.asyncio
async def test_refresh_catalog_falls_back_to_lkg_on_fetch_failure(
    monkeypatch, fake_redis,
):
    """Layer 3 protection — fetch failure MUST NOT touch the existing cache."""
    # Seed the LKG with prior good data.
    seeded = {"openai": json.dumps([
        {"provider": "openai", "model": "gpt-old",
         "display_name": "GPT Old", "supports_function_calling": True,
         "context_window": 128_000, "max_output_tokens": 4_096, "supports_vision": False},
    ])}
    fake_redis.store["model_catalog:v4:_last_known_good"] = json.dumps(seeded)

    from app.services.model_sources.litellm_loader import LiteLLMFetchFailed
    async def fake_fetch_fail():
        raise LiteLLMFetchFailed("network down")
    monkeypatch.setattr(pipeline_mod, "fetch_litellm_catalog", fake_fetch_fail)

    out = await pipeline_mod.refresh_catalog()
    # We get the LKG snapshot back...
    assert "openai" in out
    assert out["openai"][0].model == "gpt-old"
    # ...and the cache wasn't touched by this refresh (no new writes).
    assert fake_redis.set_calls == []


@pytest.mark.asyncio
async def test_refresh_catalog_failure_returns_empty_when_no_lkg(
    monkeypatch, fake_redis,
):
    """Cold start + fetch fails → empty dict, no exception."""
    from app.services.model_sources.litellm_loader import LiteLLMFetchFailed
    async def fake_fetch_fail():
        raise LiteLLMFetchFailed("network down")
    monkeypatch.setattr(pipeline_mod, "fetch_litellm_catalog", fake_fetch_fail)

    out = await pipeline_mod.refresh_catalog()
    assert out == {}


@pytest.mark.asyncio
async def test_refresh_catalog_for_persists_all_not_just_one(monkeypatch, fake_redis):
    """Refresh-for-one-provider still writes the full payload — the JSON is in
    hand anyway, and sharing benefits everyone (P6-J property)."""
    async def fake_fetch():
        return {
            "openai": [_entry("openai", "gpt-4o")],
            "anthropic": [_entry("anthropic", "claude-opus-4-7")],
        }
    monkeypatch.setattr(pipeline_mod, "fetch_litellm_catalog", fake_fetch)

    ret = await pipeline_mod.refresh_catalog_for("openai")
    assert [e.model for e in ret] == ["gpt-4o"]
    # Both per-provider keys got written
    written_keys = {k for (k, _v, _ttl) in fake_redis.set_calls}
    assert "model_catalog:v4:openai" in written_keys
    assert "model_catalog:v4:anthropic" in written_keys


# ── load_catalog ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_load_catalog_reads_per_provider_entries(monkeypatch, fake_redis):
    fake_redis.store["model_catalog:v4:openai"] = json.dumps([
        {"provider": "openai", "model": "gpt-4o",
         "display_name": "GPT-4o", "supports_function_calling": True,
         "context_window": 128_000, "max_output_tokens": 4_096, "supports_vision": False},
    ])
    # Pin known_provider_ids to a small set so load_catalog only checks openai.
    monkeypatch.setattr(
        pipeline_mod,
        "known_provider_ids" if False else "providers",  # we monkey the imported function below
        None,
    ) if False else None
    # Easier: directly patch the import name used inside load_catalog.
    import app.services.model_sources.providers as providers_mod
    monkeypatch.setattr(providers_mod, "known_provider_ids", lambda: {"openai"})

    out = await pipeline_mod.load_catalog()
    assert set(out.keys()) == {"openai"}
    assert out["openai"][0].model == "gpt-4o"


@pytest.mark.asyncio
async def test_load_catalog_for_falls_back_to_lkg_when_per_provider_expired(
    monkeypatch, fake_redis,
):
    """Per-provider keys have a TTL; LKG doesn't. When the TTL expires,
    load_catalog_for should serve LKG until the next refresh repopulates."""
    fake_redis.store["model_catalog:v4:_last_known_good"] = json.dumps({
        "openai": json.dumps([
            {"provider": "openai", "model": "gpt-from-lkg",
             "display_name": "GPT From LKG", "supports_function_calling": True,
             "context_window": 128_000, "max_output_tokens": 4_096, "supports_vision": False},
        ]),
    })
    entries = await pipeline_mod.load_catalog_for("openai")
    assert [e.model for e in entries] == ["gpt-from-lkg"]


@pytest.mark.asyncio
async def test_load_catalog_returns_empty_on_total_cache_miss(monkeypatch, fake_redis):
    """First deploy / Redis wiped / no LKG → empty dict, no exception."""
    out = await pipeline_mod.load_catalog()
    assert out == {}


# ── Deserialization robustness ──────────────────────────────────────────


def test_deserialize_drops_rows_with_missing_required_fields():
    """A future schema change must not 500 the catalog."""
    raw = json.dumps([
        {"provider": "openai", "model": "gpt-4o",
         "display_name": "GPT-4o", "supports_function_calling": True,
         "context_window": 128_000, "max_output_tokens": 4_096, "supports_vision": False},
        # Missing required `model`:
        {"provider": "openai", "display_name": "Broken"},
        # Not even a dict:
        "garbage",
    ])
    entries = pipeline_mod._deserialize_entries(raw)
    assert len(entries) == 1
    assert entries[0].model == "gpt-4o"


def test_deserialize_returns_empty_on_malformed_json():
    assert pipeline_mod._deserialize_entries("not json") == []
    assert pipeline_mod._deserialize_entries('{"obj": "not list"}') == []
