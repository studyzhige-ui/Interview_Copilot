"""Tests for ``app.core.model_registry`` after the P6-L pipeline refactor.

Pre-P6-L this file asserted heavily against the static ``MODEL_PROFILES``
dict. That dict is gone now — the registry is populated dynamically from
the LiteLLM-driven pipeline cache. These tests therefore mock the
``_get_all_profiles`` lookup to plant a known-good set of profiles, then
verify the higher-level behaviour (selection normalisation, role
resolution, FC validation, LLM construction, api-base override).
"""
from __future__ import annotations

import pytest
from llama_index.llms.openai_like import OpenAILike

import app.core.model_registry as model_registry
from app.core.model_registry import (
    ROLE_DEFAULTS,
    ModelProfile,
    _build_llm_instance,
    _normalize_selection,
    get_profile,
    get_profile_for_role,
    profile_ready,
    validate_role_update,
)


def _mkprofile(pid: str, *, provider: str | None = None, fc: bool = True) -> ModelProfile:
    """Build a ModelProfile with sane defaults for testing."""
    if provider is None:
        provider = pid.split("/", 1)[0]
    bare = pid.split("/", 1)[1] if "/" in pid else pid
    return ModelProfile(
        id=pid, provider=provider, display_name=bare, model=bare,
        api_base="https://api.example.com/v1",
        api_key_env=f"{provider.upper()}_API_KEY",
        supports_function_calling=fc,
        description="", context_window=128_000, max_output_tokens=4_096,
    )


@pytest.fixture(autouse=True)
def _stub_profile_cache(monkeypatch):
    """Plant a small known catalog into the registry for every test.

    Replaces ``_get_all_profiles`` (the lookup the registry uses
    everywhere) so tests don't need a live Redis. The set covers
    every ROLE_DEFAULTS entry plus a non-FC profile and a known
    fallback for the fallback-chain tests.
    """
    catalog = {
        "deepseek/deepseek-chat": _mkprofile("deepseek/deepseek-chat", fc=True),
        "deepseek/deepseek-reasoner": _mkprofile("deepseek/deepseek-reasoner", fc=False),
        "openai/gpt-4o": _mkprofile("openai/gpt-4o", fc=True),
        "openai/gpt-4o-mini": _mkprofile("openai/gpt-4o-mini", fc=True),
        "nvidia/nemotron-1": _mkprofile("nvidia/nemotron-1", fc=False),
    }
    monkeypatch.setattr(model_registry, "_get_all_profiles", lambda: catalog)
    yield catalog


@pytest.fixture(autouse=True)
def _isolated_user_selection(monkeypatch):
    """In-memory replacement for the DB-backed per-user selection storage.

    Pre-P6-C the runtime selection lived in a single shared file;
    post-P6-C it lives in ``users.model_selection_json``. We replace
    the load/save helpers so tests don't need a real DB session.
    """
    store: dict[str, dict[str, str]] = {}

    def fake_load(user_id: str) -> dict[str, str]:
        return dict(store.get(user_id, ROLE_DEFAULTS))

    def fake_save(user_id: str, selection: dict[str, str]) -> None:
        store[user_id] = dict(selection)

    monkeypatch.setattr(model_registry, "_load_user_selection", fake_load)
    monkeypatch.setattr(model_registry, "_save_user_selection", fake_save)
    model_registry._llm_cache.clear()
    yield
    model_registry._llm_cache.clear()


# ── ROLE_DEFAULTS resolve through the cache ─────────────────────────────


def test_role_defaults_all_resolve_in_test_catalog():
    """Every role default must point at a profile present in the planted catalog."""
    for role, pid in ROLE_DEFAULTS.items():
        get_profile(pid)  # raises if missing


def test_agent_default_supports_function_calling(_stub_profile_cache):
    agent_pid = ROLE_DEFAULTS["agent"]
    assert _stub_profile_cache[agent_pid].supports_function_calling, \
        "agent role default must support function calling"


# ── _normalize_selection ─────────────────────────────────────────────────


def test_normalize_selection_drops_pre_p6l_bare_ids():
    """Pre-P6-L profile ids ('deepseek-v4-flash', no slash) must not stick."""
    normalized = _normalize_selection({
        "primary": "deepseek-v4-flash",
        "fast": "deepseek-chat",
        "agent": "deepseek-chat",
        "mock_interview": "deepseek-reasoner",
    })
    # Every bare id was rejected → ROLE_DEFAULTS applies for every role.
    assert normalized == dict(ROLE_DEFAULTS)


def test_normalize_selection_preserves_valid_provider_slash_ids():
    normalized = _normalize_selection({
        "primary": "openai/gpt-4o",
        "fast": "deepseek/deepseek-chat",
        "agent": "openai/gpt-4o",
        "mock_interview": "openai/gpt-4o-mini",
    })
    assert normalized["primary"] == "openai/gpt-4o"
    assert normalized["fast"] == "deepseek/deepseek-chat"
    assert normalized["agent"] == "openai/gpt-4o"
    assert normalized["mock_interview"] == "openai/gpt-4o-mini"


def test_normalize_selection_unknown_id_falls_back_to_default():
    normalized = _normalize_selection({"primary": "openai/gpt-xyz-imaginary"})
    assert normalized["primary"] == ROLE_DEFAULTS["primary"]


def test_normalize_selection_forces_function_calling_agent():
    """A non-FC profile for the agent role must be replaced by the role default."""
    normalized = _normalize_selection({"agent": "nvidia/nemotron-1"})  # FC=False in fixture
    assert normalized["agent"] == ROLE_DEFAULTS["agent"]


# ── get_profile / get_profile_for_role ──────────────────────────────────


def test_get_profile_unknown_raises():
    with pytest.raises(ValueError, match="Unknown model profile"):
        get_profile("does-not-exist-xyz")


def test_get_profile_for_role_defaults_when_no_user(monkeypatch):
    """No user_id → ROLE_DEFAULTS applies."""
    for role in ROLE_DEFAULTS:
        prof = get_profile_for_role(role)
        assert prof.id == ROLE_DEFAULTS[role]


def test_get_profile_for_role_falls_back_when_selection_stale(monkeypatch, _stub_profile_cache):
    """User selection points at a now-missing profile → fall back to default."""
    # Patch the in-memory store to return a stale selection.
    monkeypatch.setattr(
        model_registry, "_load_user_selection",
        lambda uid: {"primary": "openai/gpt-retired"},
    )
    prof = get_profile_for_role("primary", user_id="alice")
    assert prof.id == ROLE_DEFAULTS["primary"]


def test_get_profile_for_role_picks_any_fc_model_when_default_missing(monkeypatch):
    """If ROLE_DEFAULTS itself isn't in the catalog (LiteLLM dropped DeepSeek
    temporarily), agent role still resolves to SOME function-calling model
    rather than 500ing the chat path."""
    # Replant the catalog WITHOUT the default deepseek-chat.
    catalog = {
        "openai/gpt-4o": _mkprofile("openai/gpt-4o", fc=True),
        "nvidia/nemotron-1": _mkprofile("nvidia/nemotron-1", fc=False),
    }
    monkeypatch.setattr(model_registry, "_get_all_profiles", lambda: catalog)
    prof = get_profile_for_role("agent")
    # Some FC profile must be returned (the only FC in catalog is gpt-4o here).
    assert prof.id == "openai/gpt-4o"
    assert prof.supports_function_calling


def test_get_profile_for_role_raises_when_catalog_empty(monkeypatch):
    """Empty catalog → ValueError so ops sees a clear "run refresh" hint."""
    monkeypatch.setattr(model_registry, "_get_all_profiles", lambda: {})
    with pytest.raises(ValueError, match="catalog is empty"):
        get_profile_for_role("primary")


# ── Per-user selection storage ───────────────────────────────────────────


def test_runtime_selection_is_per_user_isolated():
    """A's update doesn't leak into B's read (P6-C cross-tenant fix)."""
    sel_a = model_registry.update_runtime_selection(
        {"fast": "openai/gpt-4o"}, user_id="alice",
    )
    assert sel_a["fast"] == "openai/gpt-4o"
    assert model_registry.get_runtime_selection(user_id="alice")["fast"] == "openai/gpt-4o"
    bob_sel = model_registry.get_runtime_selection(user_id="bob")
    assert bob_sel["fast"] == ROLE_DEFAULTS["fast"]
    # Process-default lookup (no user) returns defaults too.
    process_sel = model_registry.get_runtime_selection()
    assert process_sel["fast"] == ROLE_DEFAULTS["fast"]


# ── validate_role_update ─────────────────────────────────────────────────


def test_validate_role_update_rejects_non_function_calling_for_agent(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "sk-test")
    with pytest.raises(ValueError, match="function calling"):
        validate_role_update("agent", "nvidia/nemotron-1")


def test_validate_role_update_rejects_profile_without_key(monkeypatch):
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    with pytest.raises(ValueError, match="not ready"):
        validate_role_update("primary", "nvidia/nemotron-1")


def test_validate_role_update_returns_profile_on_success(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    prof = validate_role_update("primary", "deepseek/deepseek-chat")
    assert isinstance(prof, ModelProfile)
    assert prof.id == "deepseek/deepseek-chat"


# ── profile_ready ────────────────────────────────────────────────────────


def test_profile_ready_true_when_env_key_set(monkeypatch, _stub_profile_cache):
    prof = _stub_profile_cache["deepseek/deepseek-chat"]
    monkeypatch.setenv(prof.api_key_env, "sk-yes")
    assert profile_ready(prof) is True


def test_profile_ready_false_when_env_key_missing(monkeypatch, _stub_profile_cache):
    prof = _stub_profile_cache["nvidia/nemotron-1"]
    monkeypatch.delenv(prof.api_key_env, raising=False)
    assert profile_ready(prof) is False


# ── _build_llm_instance: every profile builds an OpenAILike ──────────────


def test_build_llm_instance_returns_openai_like(monkeypatch, _stub_profile_cache):
    for prof in _stub_profile_cache.values():
        monkeypatch.setenv(prof.api_key_env, f"sk-test-{prof.api_key_env}")
        instance = _build_llm_instance(prof)
        assert isinstance(instance, OpenAILike)
        assert instance.model == prof.model
        assert getattr(instance, "api_base", None) == prof.api_base
        assert instance.is_chat_model is True
        assert instance.is_function_calling_model == prof.supports_function_calling


def test_build_llm_instance_uses_resolved_api_key(monkeypatch, _stub_profile_cache):
    prof = _stub_profile_cache["deepseek/deepseek-chat"]
    monkeypatch.setenv(prof.api_key_env, "sk-resolved-via-env")
    instance = _build_llm_instance(prof)
    assert getattr(instance, "api_key", None) == "sk-resolved-via-env"


# ── api_base override (P6-L plumbing for P6-M) ───────────────────────────


def test_resolve_api_base_uses_user_override_when_present(monkeypatch, _stub_profile_cache):
    """If the user has saved an ``api_base_override``, ``_resolve_api_base``
    returns THAT instead of the profile default. This is what P6-M's
    subscription-endpoint UI writes to.
    """
    prof = _stub_profile_cache["openai/gpt-4o"]

    class FakeRow:
        def __getitem__(self, idx):
            return "https://my-enterprise-gateway.example.com/v1"

    class FakeQuery:
        def filter(self, *_a, **_kw): return self
        def first(self): return FakeRow()
    class FakeSession:
        def __enter__(self): return self
        def __exit__(self, *_a): return None
        def query(self, *_a, **_kw): return FakeQuery()

    monkeypatch.setattr("app.db.database.SessionLocal", lambda: FakeSession())
    assert model_registry._resolve_api_base(prof, user_id="alice") == \
        "https://my-enterprise-gateway.example.com/v1"


def test_resolve_api_base_returns_default_when_no_user(monkeypatch, _stub_profile_cache):
    prof = _stub_profile_cache["openai/gpt-4o"]
    assert model_registry._resolve_api_base(prof, user_id=None) == prof.api_base


def test_resolve_api_base_returns_default_when_db_lookup_fails(monkeypatch, _stub_profile_cache):
    """DB outage shouldn't break chat completion — fall back to default."""
    prof = _stub_profile_cache["openai/gpt-4o"]
    def boom():
        raise RuntimeError("DB down")
    monkeypatch.setattr("app.db.database.SessionLocal", boom)
    assert model_registry._resolve_api_base(prof, user_id="alice") == prof.api_base
