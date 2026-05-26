"""Vendor-authoritative model catalog pipeline (P7-A).

Pre-P6-L: hardcoded ``MODEL_PROFILES`` dict (450 lines, needed code
edits every time a vendor released a model).

P6-L: LiteLLM JSON as single data source. Worked but had real lag —
DeepSeek released V4 a month before LiteLLM's PR merged.

Post-P7-A: each vendor's OWN ``/v1/models`` endpoint is the data
source — vendor-authoritative, current, no third-party dependency.
``vendors/`` package holds one declarative ``VendorAdapterSpec`` per
vendor (~30-50 lines each). Pipeline iterates them. Per-user
overrides (api_base, organization, headers) from P6-M still apply.

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
