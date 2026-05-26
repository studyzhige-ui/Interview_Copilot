"""Per-model display overrides (P7-B).

The vendor /v1/models endpoints (P7-A) give us authoritative model
**existence** — but the raw ids are often:
  * machine-named (``gpt-5.5-2026-04-23``, ``mimo-v2.5-pro``)
  * duplicated as version-pinned dated aliases of a rolling alias
    (OpenAI ships both ``gpt-5.5`` AND ``gpt-5.5-2026-04-23``)
  * sorted by chronology rather than tier (Gemma > Gemini in raw,
    but Gemini should rank above its open-source Gemma cousin)

This module is the thin UX-polish layer that sits on top of the
adapter output. Two mechanisms:

  1. ``CURATED[(provider, model_id)] = ModelOverride(...)`` — explicit
     per-model display_name / tier_rank / hidden override.
  2. Per-vendor "variant hide" regex — auto-suppress dated aliases
     when their bare equivalent is already in the list.

Entries WITHOUT an override:
  * keep their vendor-supplied display_name (Anthropic's
    ``"Claude Opus 4.7"``, Gemini's ``"Gemini 3.5 Flash"``) or fall
    back to the bare id
  * get ``tier_rank=999`` (sorted to the bottom of their vendor card)
  * stay visible — never auto-hidden

Adding a new model: if the vendor's display_name + auto-recency sort
are good enough, do nothing. If you want it featured higher up or
renamed, add a row to CURATED.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Iterable

from .base import ModelEntry


@dataclass(frozen=True)
class ModelOverride:
    """UX-layer override for one vendor-emitted model id.

    Every field is optional — set only the ones you want to change.
    Missing fields keep whatever the vendor reported / the default sort.
    """
    display_name: str | None = None      # None → keep vendor's / bare id
    tier_rank: int = 999                  # lower = higher in vendor card; 999 = bottom
    hidden: bool = False                  # drop from catalog entirely


# Per-vendor regex of ids to auto-hide IF their bare equivalent is
# present in the same response. This kills the "two entries for the
# same model" noise (vendor's rolling alias + dated pin) without
# requiring an explicit hidden=True row per dated variant.
_DATE_SUFFIX_PATTERNS: dict[str, re.Pattern[str]] = {
    # OpenAI / DeepSeek / Moonshot use "-YYYY-MM-DD"
    "openai":   re.compile(r"^(?P<bare>.+)-\d{4}-\d{2}-\d{2}$"),
    "deepseek": re.compile(r"^(?P<bare>.+)-\d{4}-\d{2}-\d{2}$"),
    "moonshot": re.compile(r"^(?P<bare>.+)-\d{4}-\d{2}-\d{2}$"),
    # Anthropic uses "-YYYYMMDD" (compact)
    "anthropic": re.compile(r"^(?P<bare>.+)-\d{8}$"),
    # Qwen DashScope uses "-YYYY-MM-DD" too
    "qwen":     re.compile(r"^(?P<bare>.+)-\d{4}-\d{2}-\d{2}$"),
    # Gemini / NVIDIA / zai / Xiaomi don't ship dated aliases in their
    # current /v1/models output — no entry means no auto-suppression.
}


# ── Hand-curated per-model overrides ─────────────────────────────────────
#
# Format: CURATED[(provider, model_id)] = ModelOverride(...)
#
# Tier rank ranges per vendor (lower = higher in UI card):
#    1-10 :  "hero" / latest / flagship models — top of card
#   20-50 :  recent stable models — middle
#   60-100:  legacy / specialty — bottom of curated section
#   (no entry, default 999) : pushed below all curated entries


CURATED: dict[tuple[str, str], ModelOverride] = {

    # ── OpenAI ────────────────────────────────────────────────────────────
    ("openai", "gpt-5.5-pro"):      ModelOverride("GPT-5.5 Pro",      tier_rank=1),
    ("openai", "gpt-5.5"):          ModelOverride("GPT-5.5",          tier_rank=2),
    ("openai", "gpt-5.5-codex"):    ModelOverride("GPT-5.5 Codex",    tier_rank=3),
    ("openai", "gpt-5.4-pro"):      ModelOverride("GPT-5.4 Pro",      tier_rank=4),
    ("openai", "gpt-5.4"):          ModelOverride("GPT-5.4",          tier_rank=5),
    ("openai", "gpt-5.4-mini"):     ModelOverride("GPT-5.4 Mini",     tier_rank=6),
    ("openai", "gpt-5.4-nano"):     ModelOverride("GPT-5.4 Nano",     tier_rank=7),
    ("openai", "gpt-5.3-codex"):    ModelOverride("GPT-5.3 Codex",    tier_rank=8),
    ("openai", "gpt-5.2-pro"):      ModelOverride("GPT-5.2 Pro",      tier_rank=9),
    ("openai", "gpt-5.2"):          ModelOverride("GPT-5.2",          tier_rank=10),
    ("openai", "gpt-5.2-codex"):    ModelOverride("GPT-5.2 Codex",    tier_rank=11),
    ("openai", "gpt-5.1"):          ModelOverride("GPT-5.1",          tier_rank=12),
    ("openai", "gpt-5.1-codex"):    ModelOverride("GPT-5.1 Codex",    tier_rank=13),
    ("openai", "gpt-5"):            ModelOverride("GPT-5",            tier_rank=14),
    ("openai", "gpt-5-pro"):        ModelOverride("GPT-5 Pro",        tier_rank=15),
    ("openai", "gpt-5-mini"):       ModelOverride("GPT-5 Mini",       tier_rank=16),
    ("openai", "gpt-5-nano"):       ModelOverride("GPT-5 Nano",       tier_rank=17),
    ("openai", "gpt-4.1"):          ModelOverride("GPT-4.1",          tier_rank=30),
    ("openai", "gpt-4.1-mini"):     ModelOverride("GPT-4.1 Mini",     tier_rank=31),
    ("openai", "gpt-4o"):           ModelOverride("GPT-4o",           tier_rank=40),
    ("openai", "gpt-4o-mini"):      ModelOverride("GPT-4o Mini",      tier_rank=41),
    ("openai", "o4-mini"):          ModelOverride("o4 Mini",          tier_rank=50),
    ("openai", "o3-pro"):           ModelOverride("o3 Pro",           tier_rank=51),
    ("openai", "o3"):               ModelOverride("o3",               tier_rank=52),
    # Hide the rolling "chat-latest" sibling — pure alias of the
    # latest GPT-5.x, no value showing both.
    ("openai", "gpt-5.5-chat-latest"): ModelOverride(hidden=True),
    ("openai", "gpt-5.4-chat-latest"): ModelOverride(hidden=True),
    ("openai", "gpt-5.3-chat-latest"): ModelOverride(hidden=True),
    ("openai", "gpt-5.2-chat-latest"): ModelOverride(hidden=True),
    ("openai", "gpt-5.1-chat-latest"): ModelOverride(hidden=True),
    ("openai", "gpt-5-chat"):          ModelOverride(hidden=True),
    ("openai", "gpt-5-chat-latest"):   ModelOverride(hidden=True),
    # codex-mini-latest / codex-max — agent-oriented variants, hide by default
    ("openai", "codex-mini-latest"):   ModelOverride(hidden=True),
    ("openai", "gpt-5.1-codex-mini"):  ModelOverride(hidden=True),
    ("openai", "gpt-5.1-codex-max"):   ModelOverride(hidden=True),

    # ── Anthropic ─────────────────────────────────────────────────────────
    # Anthropic's response already includes display_name — we don't
    # override those. We DO add tier_rank so the family stack ordering
    # matches Anthropic's marketing hierarchy (Opus > Sonnet > Haiku).
    ("anthropic", "claude-opus-4-7"):              ModelOverride(tier_rank=1),
    ("anthropic", "claude-sonnet-4-6"):            ModelOverride(tier_rank=2),
    ("anthropic", "claude-opus-4-6"):              ModelOverride(tier_rank=3),
    ("anthropic", "claude-haiku-4-5-20251001"):    ModelOverride(tier_rank=4),
    ("anthropic", "claude-opus-4-5-20251101"):     ModelOverride(tier_rank=5),
    ("anthropic", "claude-sonnet-4-5-20250929"):   ModelOverride(tier_rank=6),
    ("anthropic", "claude-opus-4-1-20250805"):     ModelOverride(tier_rank=10),

    # ── Google Gemini ─────────────────────────────────────────────────────
    # Gemini's response includes displayName — we keep them. tier_rank
    # only, to bring Gemini-branded above Gemma (open-source line).
    ("gemini", "gemini-3-pro-preview"):       ModelOverride(tier_rank=1),
    ("gemini", "gemini-3.5-flash"):           ModelOverride(tier_rank=2),
    ("gemini", "gemini-3-flash-preview"):     ModelOverride(tier_rank=3),
    ("gemini", "gemini-3.1-pro-preview"):     ModelOverride(tier_rank=4),
    ("gemini", "gemini-3.1-flash-lite"):      ModelOverride(tier_rank=5),
    ("gemini", "gemini-pro-latest"):          ModelOverride(tier_rank=6),
    ("gemini", "gemini-flash-latest"):        ModelOverride(tier_rank=7),
    ("gemini", "gemini-flash-lite-latest"):   ModelOverride(tier_rank=8),
    ("gemini", "gemini-2.5-pro"):             ModelOverride(tier_rank=10),
    ("gemini", "gemini-2.5-flash"):           ModelOverride(tier_rank=11),
    ("gemini", "gemini-2.5-flash-lite"):      ModelOverride(tier_rank=12),
    ("gemini", "gemini-2.0-flash"):           ModelOverride(tier_rank=20),
    ("gemini", "gemini-2.0-flash-lite"):      ModelOverride(tier_rank=21),
    # Gemma (Google's open-source family) — show below Gemini-branded
    ("gemini", "gemma-4-31b-it"):             ModelOverride("Gemma 4 31B", tier_rank=50),
    ("gemini", "gemma-4-26b-a4b-it"):         ModelOverride("Gemma 4 26B MoE", tier_rank=51),
    # Hide the experimental / preview-only / sub-1B variants
    ("gemini", "gemini-3.1-pro-preview-customtools"): ModelOverride(hidden=True),
    ("gemini", "gemini-3.1-flash-lite-preview"):      ModelOverride(hidden=True),

    # ── DeepSeek ──────────────────────────────────────────────────────────
    ("deepseek", "deepseek-v4-pro"):      ModelOverride("DeepSeek V4 Pro",   tier_rank=1),
    ("deepseek", "deepseek-v4-flash"):    ModelOverride("DeepSeek V4 Flash", tier_rank=2),

    # ── NVIDIA NIM ────────────────────────────────────────────────────────
    # NIM is a HOSTED catalog of third-party OSS models. Hero ranks
    # for the most commonly useful ones; everything else stays in the
    # uncurated 999 tier (visible but at bottom of card).
    ("nvidia_nim", "deepseek-ai/deepseek-v4-pro"):       ModelOverride("DeepSeek V4 Pro (NIM)",   tier_rank=1),
    ("nvidia_nim", "deepseek-ai/deepseek-v4-flash"):     ModelOverride("DeepSeek V4 Flash (NIM)", tier_rank=2),
    ("nvidia_nim", "meta/llama-3.3-70b-instruct"):       ModelOverride("Llama 3.3 70B",            tier_rank=5),
    ("nvidia_nim", "meta/llama-3.1-70b-instruct"):       ModelOverride("Llama 3.1 70B",            tier_rank=6),
    ("nvidia_nim", "meta/llama-4-maverick-17b-128e-instruct"): ModelOverride("Llama 4 Maverick",   tier_rank=7),
    ("nvidia_nim", "qwen/qwen3-coder-480b-a35b-instruct"):     ModelOverride("Qwen3 Coder 480B",   tier_rank=10),
    ("nvidia_nim", "qwen/qwen3-next-80b-a3b-instruct"):        ModelOverride("Qwen3 Next 80B",     tier_rank=11),
    ("nvidia_nim", "mistralai/mistral-large-3-675b-instruct-2512"): ModelOverride("Mistral Large 3 675B", tier_rank=15),
    ("nvidia_nim", "openai/gpt-oss-120b"):               ModelOverride("GPT OSS 120B",             tier_rank=20),
    ("nvidia_nim", "moonshotai/kimi-k2.6"):              ModelOverride("Kimi K2.6 (NIM)",          tier_rank=25),
    ("nvidia_nim", "z-ai/glm-5.1"):                       ModelOverride("GLM-5.1 (NIM)",            tier_rank=26),

    # ── Xiaomi MiMo ───────────────────────────────────────────────────────
    ("xiaomi", "mimo-v2.5-pro"):     ModelOverride("MiMo v2.5 Pro",   tier_rank=1),
    ("xiaomi", "mimo-v2.5"):         ModelOverride("MiMo v2.5",       tier_rank=2),
    ("xiaomi", "mimo-v2-pro"):       ModelOverride("MiMo v2 Pro",     tier_rank=10),
    ("xiaomi", "mimo-v2-flash"):     ModelOverride("MiMo v2 Flash",   tier_rank=11),
    ("xiaomi", "mimo-v2-omni"):      ModelOverride("MiMo v2 Omni",    tier_rank=12),

    # ── Moonshot Kimi ─────────────────────────────────────────────────────
    ("moonshot", "kimi-k2.6"):                       ModelOverride("Kimi K2.6",         tier_rank=1),
    ("moonshot", "moonshot-v1-128k-vision-preview"): ModelOverride("Moonshot v1 128K Vision", tier_rank=5),
    ("moonshot", "moonshot-v1-32k-vision-preview"):  ModelOverride("Moonshot v1 32K Vision",  tier_rank=6),
    ("moonshot", "moonshot-v1-8k-vision-preview"):   ModelOverride("Moonshot v1 8K Vision",   tier_rank=7),
    ("moonshot", "moonshot-v1-128k"):                ModelOverride("Moonshot v1 128K",  tier_rank=10),
    ("moonshot", "moonshot-v1-32k"):                 ModelOverride("Moonshot v1 32K",   tier_rank=11),
    ("moonshot", "moonshot-v1-8k"):                  ModelOverride("Moonshot v1 8K",    tier_rank=12),
    ("moonshot", "moonshot-v1-auto"):                ModelOverride("Moonshot v1 Auto",  tier_rank=20),

    # ── zai (Zhipu GLM) ───────────────────────────────────────────────────
    ("zai", "glm-5.1"):       ModelOverride("GLM-5.1",        tier_rank=1),
    ("zai", "glm-5"):         ModelOverride("GLM-5",          tier_rank=2),
    ("zai", "glm-5-turbo"):   ModelOverride("GLM-5 Turbo",    tier_rank=3),
    ("zai", "glm-4.7"):       ModelOverride("GLM-4.7",        tier_rank=10),
    ("zai", "glm-4.6"):       ModelOverride("GLM-4.6",        tier_rank=11),
    ("zai", "glm-4.5"):       ModelOverride("GLM-4.5",        tier_rank=12),
    ("zai", "glm-4.5-air"):   ModelOverride("GLM-4.5 Air",    tier_rank=13),

    # ── Qwen ──────────────────────────────────────────────────────────────
    ("qwen", "qwen3.7-max-preview"):  ModelOverride("Qwen3.7 Max Preview", tier_rank=1),
    ("qwen", "qwen3-max"):            ModelOverride("Qwen3 Max",           tier_rank=2),
    ("qwen", "qwen3-coder-plus"):     ModelOverride("Qwen3 Coder",         tier_rank=5),
    ("qwen", "qwen3-vl-plus"):        ModelOverride("Qwen3 VL",            tier_rank=10),
    ("qwen", "qwen3-next-80b-a3b-thinking"): ModelOverride("Qwen3 Next 80B Thinking", tier_rank=15),
    ("qwen", "qwen-plus"):            ModelOverride("Qwen Plus",           tier_rank=20),
    ("qwen", "qwen-plus-latest"):     ModelOverride("Qwen Plus Latest",    tier_rank=21),
    ("qwen", "qwen-turbo"):           ModelOverride("Qwen Turbo",          tier_rank=22),
    ("qwen", "qwen-turbo-latest"):    ModelOverride("Qwen Turbo Latest",   tier_rank=23),
    ("qwen", "qwen-max"):             ModelOverride("Qwen Max",            tier_rank=24),
}


def apply_overrides(
    provider: str, entries: Iterable[ModelEntry],
) -> list[ModelEntry]:
    """Apply curated overrides to a vendor's entry list.

    Pipeline:
      1. Auto-hide dated aliases when the bare id is present (most
         vendors ship both ``gpt-5.5`` AND ``gpt-5.5-2026-04-23`` —
         the latter is just a version-pinned alias, no extra info).
      2. Apply per-entry CURATED override: drop if hidden=True,
         replace display_name if set.
      3. Sort by tier_rank ascending. Entries with no override keep
         tier_rank=999 → sorted to the bottom but still visible (the
         vendor's freshness sort from the adapter still applies within
         that uncurated tail).
    """
    entries = list(entries)
    bare_ids = {e.model for e in entries}
    date_pattern = _DATE_SUFFIX_PATTERNS.get(provider)

    out: list[ModelEntry] = []
    for entry in entries:
        # (1) auto-hide dated alias if bare version exists in same response
        if date_pattern:
            m = date_pattern.match(entry.model)
            if m and m.group("bare") in bare_ids:
                continue
        # (2) per-entry override
        override = CURATED.get((provider, entry.model))
        if override and override.hidden:
            continue
        if override and override.display_name:
            entry = replace(entry, display_name=override.display_name)
        out.append(entry)

    # (3) tier_rank sort. Stable sort — entries with the same rank
    # keep the adapter's recency order.
    out.sort(key=lambda e: CURATED.get((e.provider, e.model), ModelOverride()).tier_rank)
    return out


__all__ = ["ModelOverride", "CURATED", "apply_overrides"]
