"""Per-model display overrides + auto-derivation fallback (P7-F).

The vendor /v1/models endpoints (P7-A) give us authoritative model
EXISTENCE. The UX layer in this file decides:

  1. What to display each model as (friendly name vs raw API id)
  2. Which models float to the top of each vendor's card
  3. Which models get hidden as redundant variants

Two paths produce a (display_name, tier_rank, hidden) decision per
entry:

  HAND-CURATED — for vendors where the auto rule produces wrong order:
    * Anthropic — must respect marketing tier (Opus > Sonnet > Haiku
      regardless of release date)
    * NVIDIA NIM — hosts hundreds of OSS models; need to feature the
      handful users actually want (DeepSeek V4 / Llama 3.3 / Qwen3
      Coder / etc) above the long tail

  AUTO-DERIVED — every other vendor (OpenAI / Gemini / DeepSeek /
  Moonshot / Zhipu / Qwen / Xiaomi). Display name comes from a
  brand-aware capitalisation rule; tier_rank from parsing the version
  number + tier suffix out of the id.

Dated-alias auto-hide (e.g. ``gpt-5.5-2026-04-23`` when ``gpt-5.5``
exists) runs FIRST, before either path — it's pattern-based, not
per-vendor knowledge.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Iterable

from .base import ModelEntry


@dataclass(frozen=True)
class ModelOverride:
    """Hand-curated UX override. All fields optional."""
    display_name: str | None = None      # None → use vendor / auto-derived
    tier_rank: int = 999                  # lower = higher in card; 999 = bottom
    hidden: bool = False                  # drop entirely


# ── Dated-alias auto-suppression ─────────────────────────────────────
# Vendors often ship a rolling alias (``gpt-5.5``) AND a date-pinned
# alias (``gpt-5.5-2026-04-23``) for the same underlying weights.
# Auto-hide the dated one whenever the bare one is in the same response.


_DATE_SUFFIX_PATTERNS: dict[str, re.Pattern[str]] = {
    "openai":    re.compile(r"^(?P<bare>.+)-\d{4}-\d{2}-\d{2}$"),
    "deepseek":  re.compile(r"^(?P<bare>.+)-\d{4}-\d{2}-\d{2}$"),
    "moonshot":  re.compile(r"^(?P<bare>.+)-\d{4}-\d{2}-\d{2}$"),
    "qwen":      re.compile(r"^(?P<bare>.+)-\d{4}-\d{2}-\d{2}$"),
    "anthropic": re.compile(r"^(?P<bare>.+)-\d{8}$"),
    # Gemini / NVIDIA / zai / Xiaomi don't ship dated aliases in
    # current /v1/models responses — no rule means no suppression.
}


# ── Auto display name ────────────────────────────────────────────────
# Maps the lowercase brand / acronym segment to its preferred display
# form. Used by ``_auto_display_name`` for vendors without manual
# curated entries.


_BRAND_DISPLAY: dict[str, str] = {
    "gpt":      "GPT",
    "glm":      "GLM",
    "deepseek": "DeepSeek",
    "mimo":     "MiMo",
    "kimi":     "Kimi",
    "moonshot": "Moonshot",
    "qwen":     "Qwen",
    "qwq":      "QwQ",
    "gemini":   "Gemini",
    "gemma":    "Gemma",
    # Acronyms
    "vl":  "VL",
    "vlm": "VLM",
    "tts": "TTS",
    "asr": "ASR",
    "oss": "OSS",
    "nim": "NIM",
}


_TIER_SUFFIX_DISPLAY: dict[str, str] = {
    "pro":     "Pro",
    "max":     "Max",
    "plus":    "Plus",
    "mini":    "Mini",
    "nano":    "Nano",
    "flash":   "Flash",
    "lite":    "Lite",
    "turbo":   "Turbo",
    "air":     "Air",
    "omni":    "Omni",
    "preview": "Preview",
    "latest":  "Latest",
    "thinking": "Thinking",
}


def _auto_display_name(model_id: str) -> str:
    """Auto-derive a friendly display name from the raw model id.

    Handles:
      * brand acronyms (gpt → GPT, glm → GLM, mimo → MiMo, deepseek
        → DeepSeek) via ``_BRAND_DISPLAY``
      * tier suffix capitalisation (pro → Pro, mini → Mini) via
        ``_TIER_SUFFIX_DISPLAY``
      * version segments (4.7, v2.5, 3-pro) kept as-is
      * unknown tokens get ``Title-Case``

    Examples:
      gpt-5.5-pro         → "GPT 5.5 Pro"
      glm-4.7             → "GLM 4.7"
      mimo-v2.5-pro       → "MiMo v2.5 Pro"
      kimi-k2.6           → "Kimi K2.6"
      deepseek-v4-pro     → "DeepSeek v4 Pro"
      qwen3-coder-plus    → "Qwen3 Coder Plus"
      gemini-3.5-flash    → "Gemini 3.5 Flash"
      gemma-4-31b-it      → "Gemma 4 31b It"
    """
    parts = model_id.split("-")
    out: list[str] = []
    for raw in parts:
        if not raw:
            continue
        low = raw.lower()
        if low in _BRAND_DISPLAY:
            out.append(_BRAND_DISPLAY[low])
            continue
        if low in _TIER_SUFFIX_DISPLAY:
            out.append(_TIER_SUFFIX_DISPLAY[low])
            continue
        # Version segment "v2.5" / "v4" / "k2.6" → preserve case but
        # ensure leading letter is the lowercase ``v`` / ``k`` form
        # vendors actually publish.
        if re.fullmatch(r"v\d+(?:\.\d+)?", low):
            out.append(low)
            continue
        if re.fullmatch(r"[a-z]\d+\.\d+", low):  # k2.6, etc
            out.append(low[0].upper() + low[1:])
            continue
        # Pure number or version (3.5, 4.1, 70b) → keep raw
        if low[0].isdigit():
            out.append(raw)
            continue
        # Fallback: Title case the unknown token
        out.append(raw[0].upper() + raw[1:])
    return " ".join(out) if out else model_id


# ── Auto tier_rank ────────────────────────────────────────────────────


def _parse_version(model_id: str) -> tuple[int, int]:
    """Extract (major, minor) version from an id.

    Two rules — in priority order:

      1. ``X.Y`` decimal anywhere: most modern vendor naming
         (``gpt-5.5``, ``gemini-3.5``, ``glm-4.7``, ``mimo-v2.5``,
         ``kimi-k2.6``).
      2. Single integer after a dash, followed by a letter / dash / end:
         ``gpt-5``, ``gpt-4o``, ``gemini-3-pro``, ``deepseek-v4``.

    The ``X-Y both digits`` pattern is INTENTIONALLY NOT supported in
    the auto path because vendors use ``X-Y`` for parameter sizes too
    (``gemma-4-31b-it`` is a 31 BILLION-parameter Gemma 4, not Gemma
    version 4.31). Anthropic uses ``claude-opus-4-7`` for version 4.7
    but Anthropic is hand-curated in CURATED so it never reaches this
    function. If a future auto-vendor needs this, special-case it.
    """
    # X.Y decimal — covers most modern names (gpt-5.5, gemini-3.5,
    # glm-4.7, mimo-v2.5, kimi-k2.6, qwen3.7).
    m = re.search(r"(\d+)\.(\d+)", model_id)
    if m:
        return int(m.group(1)), int(m.group(2))

    # Letter-attached digit: vendors who fuse the version digit to the
    # brand prefix WITHOUT a dash (``qwen3-max``, ``qwen3-next``).
    # Matches when a letter is followed by digit(s) followed by a
    # delimiter — captures the brand version BEFORE the dash-integer
    # regex below has a chance to misfire on a later ``-80b``
    # parameter-size segment.
    m = re.search(r"[a-z](\d+)(?=[-.]|$)", model_id)
    if m:
        return int(m.group(1)), 0

    # Dash-prefixed SINGLE-DIGIT integer (gpt-5, gpt-4o, gemini-3-pro,
    # moonshot-v1, deepseek-v4).
    #
    # Two guards against param-size false positives:
    #   1. Single digit only — ``-80b`` / ``-128k`` / ``-31b`` never match
    #   2. Negative lookahead skips ``b`` — ``-7b-chat`` is 7 BILLION
    #      params (Qwen-7B), not version 7.
    m = re.search(r"-v?(\d)(?![\db])(?=[a-z]|-|$)", model_id)
    if m:
        return int(m.group(1)), 0

    return 0, 0


_TIER_RANK_OFFSETS: dict[str, int] = {
    # Tier suffix → rank adjustment. Negative = boost (closer to top).
    # Magnitudes are deliberately small (max ±40) so that a tier
    # difference can NEVER flip the order across version families —
    # gpt-5.5 (bare) must always beat gpt-5.4-pro because 5.5 is the
    # newer generation.
    "pro":      -30,
    "max":      -25,
    "plus":     -10,
    "thinking": -15,   # thinking variants often preferred for hard tasks
    "flash":     10,
    "mini":      20,
    "nano":      30,
    "lite":      35,
    "turbo":     40,
    "air":       40,
    "preview":    5,   # preview demoted slightly vs stable
}


def _auto_tier_rank(provider: str, model_id: str) -> int:
    """Derive a tier_rank for a model without a hand-curated entry.

    Returns values in 100-9999 so curated tiers (1-99) ALWAYS win.

    Heuristic (lower = higher in card):
      base 10000
      − major*1000 − minor*100   (version dominates: 5.5 always above 5.4)
      + sum of tier offsets       (pro / mini / etc. fine-grain rank
                                   WITHIN the same version family)
      + brand demotion            (Google's Gemma sinks below Gemini)

    The major gap (1000) and minor gap (100) are both larger than the
    max tier spread (±40), so cross-version ordering can never be
    inverted by a tier suffix. Within a version family the suffixes
    cluster correctly: pro > bare > mini > nano > lite > turbo.
    """
    rank = 10000

    # Brand demotion: vendor's secondary line goes below their primary.
    # Currently just Google — Gemma (open-source) sinks below Gemini.
    lower = model_id.lower()
    if provider == "gemini" and lower.startswith("gemma"):
        rank += 2000   # Gemma well below any Gemini entry

    major, minor = _parse_version(model_id)
    rank -= major * 1000 + minor * 100

    # Tier suffix detection — ACCUMULATE all matches so e.g.
    # ``-pro-preview`` sums pro(-30) + preview(+5) = -25, slightly
    # less boosted than bare ``-pro``. Match on ``-suffix`` plus
    # end-of-string to avoid false positives (``-promax`` matches
    # neither ``pro`` nor ``max`` on its own).
    for suffix, offset in _TIER_RANK_OFFSETS.items():
        if f"-{suffix}" in lower or lower.endswith(f"-{suffix}"):
            rank += offset

    return max(rank, 100)


# ── Hand-curated overrides ───────────────────────────────────────────
#
# ONLY for vendors where auto-derivation produces wrong order:
#   * Anthropic — must respect Opus > Sonnet > Haiku marketing tier
#     (vendor's release date ordering doesn't capture this)
#   * NVIDIA NIM — needs hot models featured above the long tail
#
# Everything else flows through auto-derivation.


CURATED: dict[tuple[str, str], ModelOverride] = {

    # ── Anthropic — marketing tier (Opus > Sonnet > Haiku) ──────────
    # Vendor ships display_name natively so we don't override that;
    # only set tier_rank to enforce the product hierarchy.
    ("anthropic", "claude-opus-4-7"):              ModelOverride(tier_rank=1),
    ("anthropic", "claude-sonnet-4-6"):            ModelOverride(tier_rank=2),
    ("anthropic", "claude-opus-4-6"):              ModelOverride(tier_rank=3),
    ("anthropic", "claude-haiku-4-5-20251001"):    ModelOverride(tier_rank=4),
    ("anthropic", "claude-opus-4-5-20251101"):     ModelOverride(tier_rank=5),
    ("anthropic", "claude-sonnet-4-5-20250929"):   ModelOverride(tier_rank=6),
    ("anthropic", "claude-opus-4-1-20250805"):     ModelOverride(tier_rank=10),

    # ── NVIDIA NIM — hot models featured; long tail at default 999 ──
    # NIM hosts hundreds of third-party OSS models; only the
    # most-used ones get a rank, everything else auto-sinks.
    ("nvidia_nim", "deepseek-ai/deepseek-v4-pro"):       ModelOverride("DeepSeek V4 Pro (NIM)",   tier_rank=1),
    ("nvidia_nim", "deepseek-ai/deepseek-v4-flash"):     ModelOverride("DeepSeek V4 Flash (NIM)", tier_rank=2),
    ("nvidia_nim", "meta/llama-3.3-70b-instruct"):       ModelOverride("Llama 3.3 70B",           tier_rank=5),
    ("nvidia_nim", "meta/llama-3.1-70b-instruct"):       ModelOverride("Llama 3.1 70B",           tier_rank=6),
    ("nvidia_nim", "meta/llama-4-maverick-17b-128e-instruct"): ModelOverride("Llama 4 Maverick",  tier_rank=7),
    ("nvidia_nim", "qwen/qwen3-coder-480b-a35b-instruct"):     ModelOverride("Qwen3 Coder 480B",  tier_rank=10),
    ("nvidia_nim", "qwen/qwen3-next-80b-a3b-instruct"):        ModelOverride("Qwen3 Next 80B",    tier_rank=11),
    ("nvidia_nim", "mistralai/mistral-large-3-675b-instruct-2512"): ModelOverride("Mistral Large 3 675B", tier_rank=15),
    ("nvidia_nim", "openai/gpt-oss-120b"):               ModelOverride("GPT OSS 120B",            tier_rank=20),
    ("nvidia_nim", "moonshotai/kimi-k2.6"):              ModelOverride("Kimi K2.6 (NIM)",         tier_rank=25),
    ("nvidia_nim", "z-ai/glm-5.1"):                      ModelOverride("GLM-5.1 (NIM)",           tier_rank=26),
}


# ── Public entry point ──────────────────────────────────────────────


def apply_overrides(
    provider: str, entries: Iterable[ModelEntry],
) -> list[ModelEntry]:
    """Apply the full UX layer to one vendor's adapter output.

    Order of operations:
      1. Drop dated aliases whose bare equivalent is in the same response
      2. Drop entries marked ``hidden=True`` in CURATED
      3. Apply display_name: CURATED.display_name → vendor-supplied
         display name → ``_auto_display_name(model_id)``
      4. Sort by tier_rank ascending (CURATED → auto-derived → 999).
         Stable sort preserves the adapter's recency order within
         entries of equal rank.
    """
    entries = list(entries)
    bare_ids = {e.model for e in entries}
    date_pattern = _DATE_SUFFIX_PATTERNS.get(provider)

    out: list[ModelEntry] = []
    for entry in entries:
        # (1) auto-hide dated alias if its bare twin is also present
        if date_pattern:
            m = date_pattern.match(entry.model)
            if m and m.group("bare") in bare_ids:
                continue
        # (2) explicit hidden in CURATED
        override = CURATED.get((provider, entry.model))
        if override and override.hidden:
            continue
        # (3) display name: CURATED wins; otherwise if the entry has
        # a vendor-supplied display_name that's NOT just the bare id,
        # keep it; otherwise auto-derive from the id.
        if override and override.display_name:
            entry = replace(entry, display_name=override.display_name)
        elif entry.display_name == entry.model:
            # Vendor didn't ship display_name (adapter fell back to bare
            # id). Replace with our auto-derived friendly form.
            entry = replace(entry, display_name=_auto_display_name(entry.model))
        out.append(entry)

    # (4) tier_rank sort: explicit CURATED first, then auto-derived
    # for the rest. Stable so the adapter's recency tiebreak holds.
    def _rank(e: ModelEntry) -> int:
        ov = CURATED.get((e.provider, e.model))
        if ov is not None:
            return ov.tier_rank
        return _auto_tier_rank(e.provider, e.model)

    out.sort(key=_rank)
    return out


__all__ = ["ModelOverride", "CURATED", "apply_overrides"]
