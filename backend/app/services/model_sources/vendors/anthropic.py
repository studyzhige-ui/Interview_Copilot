"""Anthropic /v1/models adapter (P7-A).

Anthropic is the most well-behaved /v1/models response of any vendor:
ships ``display_name`` + ``created_at`` + ``max_input_tokens`` +
``max_tokens`` + a full ``capabilities`` object on every entry. We
don't need any curated overrides for Claude.

Note the special auth: ``x-api-key`` header (NOT Bearer) plus the
``anthropic-version`` date pin Anthropic requires on EVERY request.
"""
from __future__ import annotations

from .base import VendorAdapterSpec


SPEC = VendorAdapterSpec(
    provider="anthropic",
    models_path="/models",
    auth_style="x-api-key",
    # Anthropic's API contract requires a date-pinned version on
    # every call; see https://docs.anthropic.com/en/api/versioning .
    extra_headers=(("anthropic-version", "2023-06-01"),),
    display_name_field="display_name",
    created_iso_field="created_at",
    context_window_field="max_input_tokens",
    max_output_field="max_tokens",
    # Anthropic's /v1/models returns ONLY chat models — no filter needed.
    chat_filter=None,
    fallback_context_window=200_000,
    fallback_max_output=8_192,
    fallback_supports_function_calling=True,
)
