"""Core dataclasses for the model-catalog pipeline.

``ProviderDefaults`` describes a vendor's connection-level metadata —
what URL we call, what env var holds the key, what label / icon to
show in the UI. Dev-maintained in ``providers.py``.

``ModelEntry`` is one row in the catalog: a single chat model from
one provider, with the metadata the vendor's /v1/models endpoint
publishes (context window, function-calling support, etc.). Built
by ``vendors/base.py::fetch_one_vendor`` and polished by
``curated.py::apply_overrides``.

Why two types instead of one fat ``ModelProfile``: the ``ModelProfile``
the runtime uses mixes identity (id, provider, model), connection
(api_base, api_key_env), and capability (context_window,
supports_function_calling) into one record. Splitting at this layer
lets the provider record be a single source of truth — change
``api_base`` once instead of editing every model row for that vendor.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderDefaults:
    """Connection-level defaults for one provider (vendor).

    These describe how the system would call THIS provider's API if
    the user hasn't overridden anything in ``user_provider_settings``.
    """

    # Provider id. Convention: lowercase, matches what the vendor itself
    # uses where possible. Examples: "openai", "anthropic", "deepseek",
    # "gemini" (Google's free generative-language API; "vertex_ai" for
    # the paid enterprise channel), "zai" (Zhipu's English brand),
    # "nvidia_nim", "moonshot", "qwen", "xiaomi".
    id: str

    # Human-readable label for the UI vendor card header.
    display_label: str

    # OpenAI-compatible chat completion endpoint. The user can override
    # this per-account via ``user_provider_settings.api_base_override``
    # for subscription-tier endpoints, self-hosted gateways, etc.
    default_api_base: str

    # Environment-variable name the system reads as a FALLBACK when the
    # user hasn't saved their key via the UI. Per-user encrypted keys
    # (``user_api_keys`` table) take priority over this env var — see
    # ``resolve_api_key`` in ``model_registry``.
    api_key_env: str

    # simple-icons.org slug for the vendor brand icon. ``None`` falls
    # back to the letter initial in the UI.
    icon_slug: str | None = None

    # Whether this provider card appears in a brand-new user's Models
    # page by default. The 9 vendors with shipped adapters are True;
    # opt-in providers (Cohere / Mistral / Together / Fireworks / Groq /
    # Perplexity / xAI / Novita) default to False and show up in the
    # "显示更多厂商" picker.
    enabled_by_default: bool = False


@dataclass(frozen=True)
class ModelEntry:
    """One chat model row in the catalog.

    All fields besides ``provider`` / ``model`` are derived from the
    vendor's /v1/models response. If a vendor ships richer metadata
    in the future, extend this dataclass and update the adapter base
    to populate the new field.
    """

    # The provider this model belongs to. Joins to ``ProviderDefaults.id``.
    provider: str

    # The model id as the vendor's API exposes it. This is the string
    # we pass back in /chat/completions as the ``model`` field.
    # Examples: ``"gpt-4o"``, ``"claude-opus-4-7"``, ``"deepseek-v4-pro"``.
    model: str

    # Display name for the UI card. Comes from one of three places,
    # in priority order:
    #   1. CURATED override in ``curated.py`` (manual rename)
    #   2. Vendor-supplied display_name field (Anthropic / Gemini only)
    #   3. Auto-derived from the model id (other vendors) — brand
    #      acronym capitalisation + tier-suffix Title Case
    display_name: str

    # Whether the model accepts function-calling / tool-use payloads.
    # Used by the "agent" role guard — only FC models are valid choices
    # for tool-use chains.
    supports_function_calling: bool

    # Vendor's max_input_tokens / inputTokenLimit. Frontend may surface
    # this so the user picks an appropriately-sized model for long
    # context.
    context_window: int

    # Vendor's max_output_tokens / outputTokenLimit. Used to clamp the
    # generation budget when the role doesn't set one explicitly.
    max_output_tokens: int

    # Whether the model accepts image input. Reserved for future
    # multimodal UI; chat path doesn't read this yet.
    supports_vision: bool = False
