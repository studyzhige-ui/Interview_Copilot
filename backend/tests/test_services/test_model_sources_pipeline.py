"""Tests for the vendor-driven catalog pipeline (P7-A).

Locks in:
  - refresh_catalog parallelises across all vendor adapters
  - A vendor with no key returns empty without raising
  - A vendor that fails terminally falls back to its LKG slice
  - Per-provider Redis entries + LKG sentinel both get written on success
  - When ALL vendors fail, the cache is NOT touched (we serve LKG)
  - load_catalog falls back from per-provider key to LKG when expired
"""
from __future__ import annotations

import json

import pytest

from app.services.model_sources import pipeline as pipeline_mod
from app.services.model_sources.base import ModelEntry
from app.services.model_sources.vendors.base import VendorFetchFailed


class _FakeRedis:
    """Async stand-in for the Redis client. Tracks every set/delete."""
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


def _entry(provider: str, model: str) -> ModelEntry:
    return ModelEntry(
        provider=provider, model=model, display_name=model,
        supports_function_calling=True,
        context_window=128_000, max_output_tokens=4_096, supports_vision=False,
    )


@pytest.fixture
def fake_redis(monkeypatch):
    fr = _FakeRedis()
    monkeypatch.setattr(pipeline_mod, "redis_client", fr)
    return fr


@pytest.fixture
def stubbed_specs(monkeypatch):
    """Pin the spec list to a small set so tests don't depend on real
    vendor lineup. Each stub spec just carries a provider id."""
    from app.services.model_sources.vendors import VendorAdapterSpec
    stubs = [
        VendorAdapterSpec(provider="alpha", models_path="/models", auth_style="bearer"),
        VendorAdapterSpec(provider="beta",  models_path="/models", auth_style="bearer"),
    ]
    monkeypatch.setattr(pipeline_mod, "ALL_SPECS", stubs)
    # Pretend both providers exist in PROVIDERS so resolve_key works.
    from app.services.model_sources.base import ProviderDefaults
    fake_defaults = {
        "alpha": ProviderDefaults(
            id="alpha", display_label="Alpha", default_api_base="https://a",
            api_key_env="ALPHA_API_KEY", enabled_by_default=True,
        ),
        "beta": ProviderDefaults(
            id="beta", display_label="Beta", default_api_base="https://b",
            api_key_env="BETA_API_KEY", enabled_by_default=True,
        ),
    }
    monkeypatch.setattr(
        pipeline_mod, "get_provider_defaults", lambda pid: fake_defaults.get(pid),
    )
    return stubs


# ── refresh_catalog ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_refresh_writes_per_provider_and_lkg(monkeypatch, fake_redis, stubbed_specs):
    """Successful fetch writes one TTL'd key per provider + one no-TTL LKG."""
    monkeypatch.setenv("ALPHA_API_KEY", "sk-a")
    monkeypatch.setenv("BETA_API_KEY", "sk-b")

    async def fake_fetch(spec, api_base, api_key):
        return [_entry(spec.provider, f"{spec.provider}-model")]

    monkeypatch.setattr(pipeline_mod, "fetch_one_vendor", fake_fetch)

    out = await pipeline_mod.refresh_catalog()
    assert set(out.keys()) == {"alpha", "beta"}

    keys_with_ttl = {k for (k, _v, ttl) in fake_redis.set_calls if ttl is not None}
    assert "model_catalog:v5:alpha" in keys_with_ttl
    assert "model_catalog:v5:beta" in keys_with_ttl

    lkg_writes = [(k, v, ttl) for (k, v, ttl) in fake_redis.set_calls if ttl is None]
    assert len(lkg_writes) == 1
    assert lkg_writes[0][0] == "model_catalog:v5:_last_known_good"


@pytest.mark.asyncio
async def test_refresh_skips_vendor_without_key(monkeypatch, fake_redis, stubbed_specs):
    """No env key for a vendor → its slice is empty, OTHER vendors still
    refresh. This is the "user hasn't configured Anthropic yet but
    OpenAI works fine" case."""
    monkeypatch.setenv("ALPHA_API_KEY", "sk-a")
    monkeypatch.delenv("BETA_API_KEY", raising=False)

    fetched = {"count": 0}
    async def fake_fetch(spec, api_base, api_key):
        fetched["count"] += 1
        return [_entry(spec.provider, "x")]

    monkeypatch.setattr(pipeline_mod, "fetch_one_vendor", fake_fetch)

    out = await pipeline_mod.refresh_catalog()
    assert fetched["count"] == 1, "vendor without key must NOT call fetch_one_vendor"
    assert out["alpha"], "alpha has key → must have entries"
    assert out["beta"] == [], "beta has no key → empty"


@pytest.mark.asyncio
async def test_refresh_one_vendor_failure_falls_back_to_lkg(
    monkeypatch, fake_redis, stubbed_specs,
):
    """When one vendor's /v1/models fails, that vendor's slice comes
    from LKG; other vendors are unaffected."""
    monkeypatch.setenv("ALPHA_API_KEY", "sk-a")
    monkeypatch.setenv("BETA_API_KEY", "sk-b")
    # Seed LKG with prior good data for both.
    fake_redis.store["model_catalog:v5:_last_known_good"] = json.dumps({
        "alpha": json.dumps([_entry_dict("alpha", "alpha-old")]),
        "beta":  json.dumps([_entry_dict("beta",  "beta-old")]),
    })

    async def fake_fetch(spec, api_base, api_key):
        if spec.provider == "beta":
            raise VendorFetchFailed("beta down")
        return [_entry(spec.provider, f"{spec.provider}-new")]

    monkeypatch.setattr(pipeline_mod, "fetch_one_vendor", fake_fetch)

    out = await pipeline_mod.refresh_catalog()
    # alpha got fresh data
    assert [e.model for e in out["alpha"]] == ["alpha-new"]
    # beta fell back to its LKG slice — old data still served
    assert [e.model for e in out["beta"]] == ["beta-old"]


@pytest.mark.asyncio
async def test_refresh_all_failures_keeps_cache_untouched(
    monkeypatch, fake_redis, stubbed_specs,
):
    """Global outage (all vendors fail with no keys / no LKG) → cache
    NOT written. Caller receives LKG payload."""
    monkeypatch.delenv("ALPHA_API_KEY", raising=False)
    monkeypatch.delenv("BETA_API_KEY", raising=False)

    out = await pipeline_mod.refresh_catalog()
    # No writes happened because no vendor returned a non-empty list.
    assert fake_redis.set_calls == []
    assert out == {}


# ── load_catalog ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_load_catalog_reads_per_provider(monkeypatch, fake_redis):
    fake_redis.store["model_catalog:v5:openai"] = json.dumps([
        _entry_dict("openai", "gpt-5.5"),
    ])
    # Pin known_provider_ids so load_catalog only checks openai.
    import app.services.model_sources.providers as p_mod
    monkeypatch.setattr(p_mod, "PROVIDERS", {"openai": object()})
    # pipeline_mod imports PROVIDERS at top-level too:
    monkeypatch.setattr(pipeline_mod, "PROVIDERS", {"openai": object()})

    out = await pipeline_mod.load_catalog()
    assert set(out.keys()) == {"openai"}
    assert out["openai"][0].model == "gpt-5.5"


@pytest.mark.asyncio
async def test_load_catalog_for_falls_back_to_lkg(monkeypatch, fake_redis):
    """Per-provider key expired (TTL) → fall back to LKG snapshot."""
    fake_redis.store["model_catalog:v5:_last_known_good"] = json.dumps({
        "openai": json.dumps([_entry_dict("openai", "gpt-from-lkg")]),
    })
    entries = await pipeline_mod.load_catalog_for("openai")
    assert [e.model for e in entries] == ["gpt-from-lkg"]


@pytest.mark.asyncio
async def test_load_catalog_empty_when_redis_cold(monkeypatch, fake_redis):
    """First deploy / Redis wiped / no LKG → empty dict, no exception."""
    import app.services.model_sources.providers as p_mod
    monkeypatch.setattr(p_mod, "PROVIDERS", {"openai": object()})
    monkeypatch.setattr(pipeline_mod, "PROVIDERS", {"openai": object()})
    out = await pipeline_mod.load_catalog()
    assert out == {}


# ── deserialize robustness ─────────────────────────────────────────


def test_deserialize_drops_rows_with_missing_fields():
    raw = json.dumps([
        _entry_dict("openai", "gpt-5.5"),
        {"provider": "openai", "display_name": "Broken"},  # missing 'model'
        "garbage",
    ])
    entries = pipeline_mod._deserialize_entries(raw)
    assert len(entries) == 1
    assert entries[0].model == "gpt-5.5"


def test_deserialize_returns_empty_on_malformed():
    assert pipeline_mod._deserialize_entries("not json") == []
    assert pipeline_mod._deserialize_entries('{"obj": "not list"}') == []


# ── helpers ─────────────────────────────────────────────────────────


def _entry_dict(provider: str, model: str) -> dict:
    return {
        "provider": provider, "model": model, "display_name": model,
        "supports_function_calling": True,
        "context_window": 128_000, "max_output_tokens": 4_096,
        "supports_vision": False,
    }
