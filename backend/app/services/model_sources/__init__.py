"""LiteLLM-driven model catalog pipeline (P6-L).

Pre-P6-L: ``MODEL_PROFILES`` was a static ~400-line dict in
``model_registry.py``. Every new vendor release required a code edit.

Post-P6-L: the universe of available models is sourced live from
LiteLLM's community-maintained ``model_prices_and_context_window.json``.
Per-vendor connection metadata (api_base, api_key_env, display label)
lives in ``providers.py`` as a small Python dict that dev maintains.
The pipeline merges the two into the ``ModelEntry`` records the rest
of the system consumes.

Public API (what callers should import):

    PROVIDERS                                       — provider defaults dict
    ProviderDefaults, ModelEntry                    — dataclasses
    refresh_catalog() / refresh_catalog_for(provider) — pipeline triggers
    load_catalog() / load_catalog_for(provider)     — read from cache
"""
from .base import ModelEntry, ProviderDefaults
from .providers import PROVIDERS, get_provider_defaults, known_provider_ids
from .litellm_loader import LITELLM_CATALOG_URL, fetch_litellm_catalog
from .pipeline import (
    load_catalog,
    load_catalog_for,
    refresh_catalog,
    refresh_catalog_for,
)

__all__ = [
    "PROVIDERS",
    "ProviderDefaults",
    "ModelEntry",
    "get_provider_defaults",
    "known_provider_ids",
    "LITELLM_CATALOG_URL",
    "fetch_litellm_catalog",
    "load_catalog",
    "load_catalog_for",
    "refresh_catalog",
    "refresh_catalog_for",
]
