"""Provider defaults registry (dev-maintained).

Post-P7-A: this file declares the connection-level metadata for each
vendor — what api_base to hit, what env var holds the deployment-level
key, what to label / icon on the Models page card, whether to
default-show or hide-until-user-enables.

The actual MODEL LIST for each vendor comes from that vendor's own
``/v1/models`` endpoint, fetched live by an adapter spec in
``vendors/<provider>.py``. The pipeline pairs (this dict's defaults)
with (that adapter's fetched entries) to build the user-facing
catalog.

Adding a new vendor:
  1. Add a row below with id = the canonical provider name
  2. Drop a ``vendors/<id>.py`` adapter spec
  3. Append the spec into ``vendors/__init__.py::ALL_SPECS``
No edits to pipeline / API / FE needed.

``enabled_by_default``: 9 vendors with adapters are True (shown on
every new user's Models page). Everything else is False (must opt-in
via "显示更多厂商" picker).
"""
from __future__ import annotations

import os

from .base import ProviderDefaults


# Default-enabled providers — the 9 vendors that ship with a working
# adapter and a card on the new-user Models page:
#
# DeepSeek / OpenAI / Anthropic / Google Gemini / Alibaba Qwen /
# Moonshot Kimi / Zhipu GLM / Xiaomi MiMo / NVIDIA NIM.
#
# Opt-in providers (Cohere / Mistral / Together / etc.) come AFTER
# this block and stay hidden until the user enables them via the
# "显示更多厂商" picker in the UI.
#
# Each ``default_api_base`` is overridable via env var so a deployment
# can redirect at an internal mirror without code edits.
PROVIDERS: dict[str, ProviderDefaults] = {
    "deepseek": ProviderDefaults(
        id="deepseek",
        display_label="DeepSeek",
        default_api_base=os.getenv("DEEPSEEK_API_BASE", "https://api.deepseek.com"),
        api_key_env="DEEPSEEK_API_KEY",
        icon_slug="deepseek",
        enabled_by_default=True,
    ),
    "openai": ProviderDefaults(
        id="openai",
        display_label="OpenAI",
        default_api_base=os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1"),
        api_key_env="OPENAI_API_KEY",
        icon_slug="openai",
        enabled_by_default=True,
    ),
    "anthropic": ProviderDefaults(
        id="anthropic",
        display_label="Anthropic",
        default_api_base=os.getenv("ANTHROPIC_API_BASE", "https://api.anthropic.com/v1"),
        api_key_env="ANTHROPIC_API_KEY",
        icon_slug="anthropic",
        enabled_by_default=True,
    ),
    "gemini": ProviderDefaults(
        id="gemini",
        display_label="Google Gemini",
        default_api_base=os.getenv(
            "GOOGLE_API_BASE",
            "https://generativelanguage.googleapis.com/v1beta/openai",
        ),
        api_key_env="GOOGLE_API_KEY",
        icon_slug="googlegemini",
        enabled_by_default=True,
    ),
    # Qwen models come from Alibaba's DashScope OpenAI-compatible
    # endpoint. The vendor's /v1/models returns 200+ ids including
    # third-party gateway models (ZHIPU/GLM, deepseek-*, llama-*);
    # the qwen adapter's chat_filter keeps only qwen*/qwq* brand ids
    # so other vendors' models stay in THEIR own cards.
    "qwen": ProviderDefaults(
        id="qwen",
        display_label="通义 Qwen",
        default_api_base=os.getenv(
            "DASHSCOPE_API_BASE",
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
        ),
        api_key_env="DASHSCOPE_API_KEY",
        icon_slug="alibabacloud",
        enabled_by_default=True,
    ),
    "moonshot": ProviderDefaults(
        id="moonshot",
        display_label="Moonshot Kimi",
        default_api_base=os.getenv("MOONSHOT_API_BASE", "https://api.moonshot.cn/v1"),
        api_key_env="MOONSHOT_API_KEY",
        icon_slug=None,
        enabled_by_default=True,
    ),
    # Zhipu BigModel internationally markets as "z.ai" — the provider
    # id matches the brand. Display label / env var stay Chinese-facing
    # so existing ZHIPU_API_KEY env values keep working.
    "zai": ProviderDefaults(
        id="zai",
        display_label="智谱 GLM",
        default_api_base=os.getenv(
            "ZHIPU_API_BASE", "https://open.bigmodel.cn/api/paas/v4",
        ),
        api_key_env="ZHIPU_API_KEY",
        icon_slug=None,
        enabled_by_default=True,
    ),
    # Xiaomi's official OpenAI-compatible API base is
    # ``api.xiaomimimo.com/v1`` (per platform.xiaomimimo.com docs).
    # The earlier ``token-plan-cn.xiaomimimo.com`` was a separate token
    # plan gateway that returns 401 on /v1/models — wrong host.
    "xiaomi": ProviderDefaults(
        id="xiaomi",
        display_label="小米 MiMo",
        default_api_base=os.getenv(
            "MIMO_API_BASE", "https://api.xiaomimimo.com/v1",
        ),
        api_key_env="MIMO_API_KEY",
        icon_slug="xiaomi",
        enabled_by_default=True,
    ),
    # NVIDIA NIM is NVIDIA's hosted-inference catalog (build.nvidia.com).
    # Provider id intentionally ``nvidia_nim`` (with underscore) to
    # disambiguate from a hypothetical future ``nvidia`` direct GPU
    # binding.
    "nvidia_nim": ProviderDefaults(
        id="nvidia_nim",
        display_label="NVIDIA",
        default_api_base=os.getenv(
            "NVIDIA_API_BASE", "https://integrate.api.nvidia.com/v1",
        ),
        api_key_env="NVIDIA_API_KEY",
        icon_slug="nvidia",
        enabled_by_default=True,
    ),

    # ── Opt-in providers (hidden until user enables via UI) ─────────────
    # All of these expose an OpenAI-compatible /v1/models endpoint —
    # once the user toggles them on AND configures a key, models
    # surface automatically via the vendor adapter pipeline.
    "mistral": ProviderDefaults(
        id="mistral",
        display_label="Mistral",
        default_api_base=os.getenv("MISTRAL_API_BASE", "https://api.mistral.ai/v1"),
        api_key_env="MISTRAL_API_KEY",
        icon_slug="mistralai",
        enabled_by_default=False,
    ),
    "cohere": ProviderDefaults(
        id="cohere",
        display_label="Cohere",
        default_api_base=os.getenv("COHERE_API_BASE", "https://api.cohere.ai/compatibility/v1"),
        api_key_env="COHERE_API_KEY",
        icon_slug="cohere",
        enabled_by_default=False,
    ),
    "groq": ProviderDefaults(
        id="groq",
        display_label="Groq",
        default_api_base=os.getenv("GROQ_API_BASE", "https://api.groq.com/openai/v1"),
        api_key_env="GROQ_API_KEY",
        icon_slug=None,
        enabled_by_default=False,
    ),
    "together_ai": ProviderDefaults(
        id="together_ai",
        display_label="Together AI",
        default_api_base=os.getenv(
            "TOGETHER_API_BASE", "https://api.together.xyz/v1",
        ),
        api_key_env="TOGETHER_API_KEY",
        icon_slug=None,
        enabled_by_default=False,
    ),
    "fireworks_ai": ProviderDefaults(
        id="fireworks_ai",
        display_label="Fireworks AI",
        default_api_base=os.getenv(
            "FIREWORKS_API_BASE", "https://api.fireworks.ai/inference/v1",
        ),
        api_key_env="FIREWORKS_API_KEY",
        icon_slug=None,
        enabled_by_default=False,
    ),
    "perplexity": ProviderDefaults(
        id="perplexity",
        display_label="Perplexity",
        default_api_base=os.getenv("PERPLEXITY_API_BASE", "https://api.perplexity.ai"),
        api_key_env="PERPLEXITY_API_KEY",
        icon_slug="perplexity",
        enabled_by_default=False,
    ),
    "xai": ProviderDefaults(
        id="xai",
        display_label="xAI",
        default_api_base=os.getenv("XAI_API_BASE", "https://api.x.ai/v1"),
        api_key_env="XAI_API_KEY",
        icon_slug="x",
        enabled_by_default=False,
    ),
    # Novita — a third-party gateway that resells Qwen / Xiaomi MiMo /
    # Zhipu GLM / Meta Llama / many other open-source models behind one
    # OpenAI-compatible endpoint. Opt-in; useful when a user wants
    # access without configuring each direct vendor key.
    "novita": ProviderDefaults(
        id="novita",
        display_label="Novita AI (聚合)",
        default_api_base=os.getenv("NOVITA_API_BASE", "https://api.novita.ai/v3/openai"),
        api_key_env="NOVITA_API_KEY",
        icon_slug=None,
        enabled_by_default=False,
    ),
}


def get_provider_defaults(provider_id: str) -> ProviderDefaults | None:
    """Return ``ProviderDefaults`` for ``provider_id``, or ``None`` if unknown.

    Returning ``None`` (not raising) is deliberate: callers that process
    a vendor response can silently drop entries for providers we don't
    ship support for (e.g., a vendor's /v1/models endpoint returning
    third-party models tagged with a provider id we don't recognise).
    The catalog still works; ops just
    add a row above when they want to surface that vendor.
    """
    return PROVIDERS.get(provider_id)


def known_provider_ids() -> set[str]:
    """Set of provider ids the system supports right now."""
    return set(PROVIDERS.keys())
