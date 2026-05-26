"""Vendor-authoritative model catalog pipeline.

Each vendor's own ``/v1/models`` endpoint is the data source —
authoritative, current, no third-party dependency.

  ``vendors/<provider>.py`` declares one ``VendorAdapterSpec``
    (api path, auth style, response shape, chat-only filter).
  ``providers.py`` declares connection-level defaults (api_base,
    api_key_env, display label, default-enabled flag).
  ``curated.py`` applies the UX layer (display name, tier_rank,
    hide variants). Hand-curated for Anthropic + NVIDIA, fully
    auto-derived for the other 7 vendors.
  ``pipeline.py`` orchestrates fetch → curated → cache with 3
    fallback layers (per-provider Redis → LKG snapshot → shipped
    seed catalog).

Per-user overrides (api_base / organization / extra_headers) live
in ``user_provider_settings`` and apply at chat-completion time —
not in this module.

Public API:
    PROVIDERS                                    — provider defaults dict
    ProviderDefaults, ModelEntry                 — dataclasses
    refresh_catalog() / refresh_catalog_for(provider)
    load_catalog() / load_catalog_for(provider)
    invalidate_all()                             — wipe Redis cache
"""
from .base import ModelEntry, ProviderDefaults
from .providers import PROVIDERS, get_provider_defaults, known_provider_ids
from .pipeline import (
    invalidate_all,
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
    "load_catalog",
    "load_catalog_for",
    "refresh_catalog",
    "refresh_catalog_for",
    "invalidate_all",
]
