"""Tests for ``app.core.model_registry``.

The registry is populated dynamically from the vendor-adapter pipeline
cache. These tests mock the ``_get_all_profiles`` lookup to plant a
known-good set of profiles, then verify the higher-level behaviour
(selection normalisation, role resolution, function-calling validation,
LLM construction, api-base override).
"""
from __future__ import annotations

import pytest
from llama_index.llms.openai_like import OpenAILike

# P8-10 split: catalog / selection / client-factory now live in their own
# modules. The model_registry shim still re-exports the public surface
# for back-compat, but monkeypatching MUST target the leaf modules where
# the symbols are defined — patching the shim's local binding wouldn't
# affect the real callers that look symbols up through their own module
# namespace.
import app.core.llm_client_factory as llm_client_factory
import app.core.model_catalog as model_catalog
import app.core.user_model_selection as user_model_selection
from app.core.llm_client_factory import (
    _build_llm_instance,
    profile_ready,
    validate_role_update,
)
from app.core.model_catalog import ROLE_DEFAULTS, ModelProfile, get_profile
from app.core.user_model_selection import (
    _normalize_selection,
    get_profile_for_role,
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
    monkeypatch.setattr(model_catalog, "_get_all_profiles", lambda: catalog)
    yield catalog


@pytest.fixture(autouse=True)
def _isolated_user_selection(monkeypatch):
    """In-memory replacement for the DB-backed per-user selection storage.

    The runtime selection lives in the ``user_model_selections`` table
    (one row per role). We replace the load/save helpers so tests don't
    need a real DB session.
    """
    store: dict[str, dict[str, str]] = {}

    def fake_load(user_id: str) -> dict[str, str]:
        return dict(store.get(user_id, ROLE_DEFAULTS))

    def fake_save(user_id: str, selection: dict[str, str]) -> None:
        store[user_id] = dict(selection)

    monkeypatch.setattr(user_model_selection, "_load_user_selection", fake_load)
    monkeypatch.setattr(user_model_selection, "_save_user_selection", fake_save)
    llm_client_factory._llm_cache.clear()
    yield
    llm_client_factory._llm_cache.clear()


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
        user_model_selection, "_load_user_selection",
        lambda uid: {"primary": "openai/gpt-retired"},
    )
    prof = get_profile_for_role("primary", user_id="alice")
    assert prof.id == ROLE_DEFAULTS["primary"]


def test_get_profile_for_role_picks_any_fc_model_when_default_missing(monkeypatch):
    """If ROLE_DEFAULTS itself isn't in the catalog (the vendor's
    /v1/models temporarily dropped that id), agent role still resolves
    to SOME function-calling model rather than 500ing the chat path."""
    # Replant the catalog WITHOUT the default deepseek-chat.
    catalog = {
        "openai/gpt-4o": _mkprofile("openai/gpt-4o", fc=True),
        "nvidia/nemotron-1": _mkprofile("nvidia/nemotron-1", fc=False),
    }
    monkeypatch.setattr(model_catalog, "_get_all_profiles", lambda: catalog)
    prof = get_profile_for_role("agent")
    # Some FC profile must be returned (the only FC in catalog is gpt-4o here).
    assert prof.id == "openai/gpt-4o"
    assert prof.supports_function_calling


def test_get_profile_for_role_raises_when_catalog_empty(monkeypatch):
    """Empty catalog → ValueError so ops sees a clear "run refresh" hint."""
    monkeypatch.setattr(model_catalog, "_get_all_profiles", lambda: {})
    with pytest.raises(ValueError, match="catalog is empty"):
        get_profile_for_role("primary")


# ── Per-user selection storage ───────────────────────────────────────────


def test_runtime_selection_is_per_user_isolated():
    """A's update doesn't leak into B's read (P6-C cross-tenant fix)."""
    sel_a = user_model_selection.update_runtime_selection(
        {"fast": "openai/gpt-4o"}, user_id="alice",
    )
    assert sel_a["fast"] == "openai/gpt-4o"
    assert user_model_selection.get_runtime_selection(user_id="alice")["fast"] == "openai/gpt-4o"
    bob_sel = user_model_selection.get_runtime_selection(user_id="bob")
    assert bob_sel["fast"] == ROLE_DEFAULTS["fast"]
    # Process-default lookup (no user) returns defaults too.
    process_sel = user_model_selection.get_runtime_selection()
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

    SQLAlchemy ``first()`` returns a Row that the registry unpacks as
    a 3-tuple ``(api_base_override, organization_id, extra_headers_json)``,
    so the fake must mimic tuple iteration — using a plain tuple keeps
    the fixture aligned with whatever shape ``_load_user_provider_overrides``
    expects today.
    """
    prof = _stub_profile_cache["openai/gpt-4o"]

    class FakeQuery:
        def join(self, *_a, **_kw): return self
        def filter(self, *_a, **_kw): return self
        def first(self):
            # (api_base_override, organization_id, extra_headers_json)
            return ("https://my-enterprise-gateway.example.com/v1", None, None)
    class FakeSession:
        def __enter__(self): return self
        def __exit__(self, *_a): return None
        def query(self, *_a, **_kw): return FakeQuery()

    monkeypatch.setattr("app.db.database.SessionLocal", lambda: FakeSession())
    assert llm_client_factory._resolve_api_base(prof, user_id="alice") == \
        "https://my-enterprise-gateway.example.com/v1"


def test_resolve_api_base_returns_default_when_no_user(monkeypatch, _stub_profile_cache):
    prof = _stub_profile_cache["openai/gpt-4o"]
    assert llm_client_factory._resolve_api_base(prof, user_id=None) == prof.api_base


def test_resolve_api_base_returns_default_when_db_lookup_fails(monkeypatch, _stub_profile_cache):
    """DB outage shouldn't break chat completion — fall back to default."""
    prof = _stub_profile_cache["openai/gpt-4o"]
    def boom():
        raise RuntimeError("DB down")
    monkeypatch.setattr("app.db.database.SessionLocal", boom)
    assert llm_client_factory._resolve_api_base(prof, user_id="alice") == prof.api_base
