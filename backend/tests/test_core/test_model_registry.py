"""Tests for app.core.model_registry — profiles, role resolution, LLM build, ready check."""
from __future__ import annotations

import os

import pytest
from llama_index.llms.openai_like import OpenAILike

import app.core.model_registry as model_registry
from app.core.model_registry import (
    MODEL_PROFILES,
    ROLE_DEFAULTS,
    ModelProfile,
    _build_llm_instance,
    _normalize_selection,
    get_profile,
    get_profile_for_role,
    profile_ready,
    validate_role_update,
)


@pytest.fixture(autouse=True)
def _isolated_selection_file(tmp_path, monkeypatch):
    """Point MODEL_SELECTION_FILE at a fresh path so tests can't leak state."""
    monkeypatch.setenv("MODEL_SELECTION_FILE", str(tmp_path / "model_selection.json"))
    # Defensive: clear LLM cache so cached instances don't bleed across tests.
    model_registry._llm_cache.clear()
    yield
    model_registry._llm_cache.clear()


# ── MODEL_PROFILES structural sanity ─────────────────────────────────────
def test_model_profiles_role_defaults_all_resolve():
    for role, profile_id in ROLE_DEFAULTS.items():
        assert profile_id in MODEL_PROFILES, \
            f"ROLE_DEFAULTS[{role}]={profile_id!r} missing from MODEL_PROFILES"


def test_model_profiles_ids_match_dict_keys():
    for key, prof in MODEL_PROFILES.items():
        assert key == prof.id, f"key {key!r} != profile.id {prof.id!r}"


def test_agent_default_supports_function_calling():
    agent_pid = ROLE_DEFAULTS["agent"]
    assert MODEL_PROFILES[agent_pid].supports_function_calling, \
        "agent default profile must support function calling"


def test_every_profile_has_required_fields():
    for pid, prof in MODEL_PROFILES.items():
        assert prof.model.strip(), f"{pid} has empty model"
        assert prof.api_base.startswith("http"), f"{pid} has bad api_base {prof.api_base!r}"
        assert prof.api_key_env.endswith("_API_KEY"), \
            f"{pid} api_key_env {prof.api_key_env!r} doesn't end with _API_KEY"
        assert prof.provider, f"{pid} has empty provider"


# ── _build_llm_instance: every profile builds a real OpenAILike ──────────
def test_build_llm_instance_returns_openai_like_for_every_profile(monkeypatch):
    """The collapsed _build_llm_instance must produce OpenAILike for *every* profile."""
    # Provide a dummy key for every api_key_env so resolve_api_key returns non-empty.
    envs = {p.api_key_env for p in MODEL_PROFILES.values()}
    for env_name in envs:
        monkeypatch.setenv(env_name, f"sk-test-{env_name}")

    for pid, prof in MODEL_PROFILES.items():
        instance = _build_llm_instance(prof)
        assert isinstance(instance, OpenAILike), f"{pid} did not build an OpenAILike"
        # OpenAILike stores the model id and api_base as attributes.
        assert instance.model == prof.model, f"{pid} model mismatch"
        # api_base is exposed as `api_base` attribute on OpenAILike.
        assert getattr(instance, "api_base", None) == prof.api_base, \
            f"{pid} api_base mismatch"
        assert instance.is_chat_model is True
        assert instance.is_function_calling_model == prof.supports_function_calling


def test_build_llm_instance_uses_resolved_api_key(monkeypatch):
    prof = MODEL_PROFILES["deepseek-v4-flash"]
    monkeypatch.setenv(prof.api_key_env, "sk-resolved-via-env")
    instance = _build_llm_instance(prof)
    # OpenAILike stores the key on `api_key`.
    assert getattr(instance, "api_key", None) == "sk-resolved-via-env"


# ── Role resolution + normalization ──────────────────────────────────────
def test_normalize_selection_drops_retired_deepseek_aliases():
    normalized = _normalize_selection({
        "primary": "deepseek-reasoner",
        "fast": "deepseek-chat",
        "agent": "deepseek-chat",
        "mock_interview": "deepseek-chat",
    })
    assert normalized == dict(ROLE_DEFAULTS)


def test_normalize_selection_preserves_valid_choices():
    normalized = _normalize_selection({
        "primary": "openai-gpt-4o",
        "fast": "deepseek-v4-flash",
        "agent": "deepseek-v4-pro",
        "mock_interview": "openai-gpt-4o-mini",
    })
    assert normalized["primary"] == "openai-gpt-4o"
    assert normalized["fast"] == "deepseek-v4-flash"
    assert normalized["agent"] == "deepseek-v4-pro"
    assert normalized["mock_interview"] == "openai-gpt-4o-mini"


def test_normalize_selection_forces_function_calling_agent():
    """A non-function-calling profile must not stick to the agent role."""
    # deepseek-reasoner has supports_function_calling=False, but is also one of
    # the explicitly-stripped aliases. Pick another non-FC profile instead.
    non_fc = next(
        pid for pid, prof in MODEL_PROFILES.items()
        if not prof.supports_function_calling and pid not in {"deepseek-chat", "deepseek-reasoner"}
    )
    normalized = _normalize_selection({"agent": non_fc})
    assert normalized["agent"] == ROLE_DEFAULTS["agent"]


def test_get_profile_unknown_raises():
    with pytest.raises(ValueError):
        get_profile("does-not-exist-xyz")


def test_get_profile_for_role_defaults_when_selection_missing():
    # No selection file written → returns ROLE_DEFAULTS.
    for role, pid in ROLE_DEFAULTS.items():
        assert get_profile_for_role(role).id == pid


def test_runtime_selection_persists_and_reloads():
    selection = model_registry.update_runtime_selection({"fast": "deepseek-v4-flash"})
    assert selection["fast"] == "deepseek-v4-flash"
    assert model_registry.get_runtime_selection()["fast"] == "deepseek-v4-flash"


def test_validate_role_update_rejects_non_function_calling_for_agent(monkeypatch):
    # Provide a key so profile_ready passes, but pick a non-FC profile.
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    with pytest.raises(ValueError, match="function calling"):
        validate_role_update("agent", "deepseek-reasoner")


def test_validate_role_update_rejects_profile_without_key(monkeypatch):
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    with pytest.raises(ValueError, match="not ready"):
        validate_role_update("primary", "nvidia-meta-llama-3.1-8b")


def test_validate_role_update_returns_profile_on_success(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    prof = validate_role_update("primary", "deepseek-v4-flash")
    assert isinstance(prof, ModelProfile)
    assert prof.id == "deepseek-v4-flash"


# ── profile_ready ────────────────────────────────────────────────────────
def test_profile_ready_true_when_env_key_set(monkeypatch):
    prof = MODEL_PROFILES["deepseek-v4-flash"]
    monkeypatch.setenv(prof.api_key_env, "sk-yes")
    assert profile_ready(prof) is True


def test_profile_ready_false_when_env_key_missing(monkeypatch):
    prof = MODEL_PROFILES["nvidia-meta-llama-3.1-8b"]
    monkeypatch.delenv(prof.api_key_env, raising=False)
    assert profile_ready(prof) is False
