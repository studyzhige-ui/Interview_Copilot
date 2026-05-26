"""Core dataclasses for the LiteLLM-driven catalog (P6-L).

``ProviderDefaults`` describes a vendor's connection-level metadata —
what URL we call, what env var holds the key, what label / icon to
show in the UI. Dev-maintained in ``providers.py``.

``ModelEntry`` is one row in the catalog: a single chat model from
one provider, with the metadata LiteLLM publishes (context window,
function-calling support, etc.). Built by the pipeline from LiteLLM
JSON + the matching ProviderDefaults.

Why two types instead of one fat ``ModelProfile``: pre-P6-L the
``ModelProfile`` dataclass mixed identity (id, provider, model),
connection (api_base, api_key_env), and capability (context_window,
supports_function_calling) into one record, with provider-level
fields duplicated across every model entry. Splitting them lets the
provider record be a single source of truth — change ``api_base``
once instead of editing every model row for that provider.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderDefaults:
    """Connection-level defaults for one provider (vendor).

    These describe how the system would call THIS provider's API if
    the user hasn't overridden anything in ``user_provider_settings``.
    """

    # Provider id. MUST match LiteLLM's ``litellm_provider`` field value
    # so the pipeline can join LiteLLM entries to provider defaults
    # without an extra mapping table. Examples: "openai", "anthropic",
    # "deepseek", "gemini" (note: NOT "google" — LiteLLM uses "gemini"),
    # "azure", "bedrock", "cohere", "mistral".
    id: str

    # Human-readable label for the UI vendor card header.
    display_label: str

    # OpenAI-compatible chat completion endpoint. The user can override
    # this per-account via ``user_provider_settings.api_base_override``
    # (P6-M) for subscription-tier endpoints, self-hosted gateways, etc.
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
    # page by default. The 9 main vendors we ship support for are True;
    # everything else LiteLLM covers (Cohere, Together, Fireworks,
    # Replicate, Groq, Azure, Bedrock, Vertex, etc.) defaults to False
    # and shows up in the "show more vendors" picker.
    enabled_by_default: bool = False


@dataclass(frozen=True)
class ModelEntry:
    """One chat model row in the catalog.

    All fields besides ``provider`` / ``model`` are derived from
    LiteLLM JSON; if LiteLLM ships richer metadata in the future we
    just extend this dataclass without touching the pipeline.
    """

    # The provider this model belongs to (LiteLLM's ``litellm_provider``).
    # Joins to ``ProviderDefaults.id``.
    provider: str

    # The model id LiteLLM exposes (also what we pass to the vendor's
    # ``/chat/completions`` endpoint as the ``model`` field). Example:
    # ``"gpt-4o"``, ``"claude-opus-4-7"``, ``"deepseek-chat"``.
    model: str

    # Cleaned-up display name for the UI. The pipeline derives this
    # from the model id by capitalising / inserting spaces — vendors
    # rarely publish a "pretty" name in /v1/models, so we synthesise.
    display_name: str

    # LiteLLM's ``supports_function_calling`` boolean. Used by the
    # "agent" role guard — only function-calling models are valid for
    # tool-use chains.
    supports_function_calling: bool

    # LiteLLM's ``max_input_tokens``. Frontend may surface this so the
    # user picks an appropriately-sized model for long-context tasks.
    context_window: int

    # LiteLLM's ``max_output_tokens``. Used to clamp the generation
    # budget when the role doesn't explicitly set one.
    max_output_tokens: int

    # LiteLLM's ``supports_vision`` boolean. Reserved for future image
    # input UI; not used by chat path yet.
    supports_vision: bool = False
