"""Back-compat facade — re-exports the model-registry public surface.

The implementation was split in P8-10 into three focused modules:

  ``app.core.model_catalog``        — vendor-driven catalog + cache,
                                      ``ModelProfile``, ``ROLE_DEFAULTS``,
                                      ``get_profile``
  ``app.core.user_model_selection`` — per-user role→profile selection,
                                      ``get_runtime_selection``,
                                      ``persist_runtime_selection``,
                                      ``update_runtime_selection``,
                                      ``get_profile_for_role``
  ``app.core.llm_client_factory``   — LlamaIndex + AsyncOpenAI client
                                      construction and per-user caching,
                                      api-key + override resolution,
                                      ``RuntimeLLMProxy``

This shim keeps the historical ``from app.core.model_registry import X``
imports working while consumers migrate. Prefer importing from the
new module that actually owns the symbol.
"""
from app.core.llm_client_factory import (
    RuntimeLLMProxy,
    _serialize_profile,
    build_async_openai_client_for_role,
    clear_llm_cache_for_provider,
    get_async_openai_client,
    get_llm_for_role,
    list_profiles,
    profile_ready,
    resolve_api_key,
    validate_role_update,
)
from app.core.model_catalog import (
    ROLE_DEFAULTS,
    ModelProfile,
    _get_all_profiles,
    get_profile,
    repopulate_profile_cache,
)
from app.core.user_model_selection import (
    get_profile_for_role,
    get_runtime_selection,
    persist_runtime_selection,
    update_runtime_selection,
)

__all__ = [
    # Catalog
    "ModelProfile",
    "ROLE_DEFAULTS",
    "repopulate_profile_cache",
    "_get_all_profiles",
    "get_profile",
    # Selection
    "get_runtime_selection",
    "persist_runtime_selection",
    "update_runtime_selection",
    "get_profile_for_role",
    # LLM client factory
    "resolve_api_key",
    "get_async_openai_client",
    "clear_llm_cache_for_provider",
    "profile_ready",
    "list_profiles",
    "validate_role_update",
    "get_llm_for_role",
    "build_async_openai_client_for_role",
    "RuntimeLLMProxy",
    "_serialize_profile",
]
