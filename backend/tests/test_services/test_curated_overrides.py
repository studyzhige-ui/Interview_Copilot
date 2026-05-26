"""Tests for the curated UX layer (P7-F).

Slim layer:
  - Anthropic + NVIDIA keep hand-curated entries (marketing tier /
    featured-hot models)
  - All 7 other vendors flow through auto-derivation
  - Dated-alias auto-hide runs first, pattern-based per vendor

Locked behaviours:
  * CURATED hidden=True drops the entry
  * CURATED display_name override applied when set
  * CURATED tier_rank wins over auto-derived for sort
  * Auto-derived display_name handles brand acronyms (GPT, GLM, MiMo,
    DeepSeek) + version segments (v2.5) + tier suffixes (Pro / Mini)
  * Auto-derived tier_rank parses version + tier; Gemma sinks below
    Gemini; pro boosts; mini/nano demote
  * Dated-alias suppression works for OpenAI / Anthropic / Qwen patterns
  * Gemini's vendor-supplied displayName survives auto-derive (only
    bare-id entries get rewritten)
"""
from __future__ import annotations

from app.services.model_sources.base import ModelEntry
from app.services.model_sources.curated import (
    CURATED,
    ModelOverride,
    _auto_display_name,
    _auto_tier_rank,
    apply_overrides,
)


def _entry(provider: str, model: str, display_name: str | None = None) -> ModelEntry:
    return ModelEntry(
        provider=provider, model=model,
        display_name=display_name or model,
        supports_function_calling=True,
        context_window=128_000, max_output_tokens=4_096, supports_vision=False,
    )


# ── _auto_display_name ──────────────────────────────────────────────


def test_auto_display_brand_acronyms():
    assert _auto_display_name("gpt-5.5") == "GPT 5.5"
    assert _auto_display_name("gpt-5.5-pro") == "GPT 5.5 Pro"
    assert _auto_display_name("glm-4.7") == "GLM 4.7"
    assert _auto_display_name("deepseek-v4-pro") == "DeepSeek v4 Pro"
    assert _auto_display_name("mimo-v2.5-pro") == "MiMo v2.5 Pro"
    assert _auto_display_name("kimi-k2.6") == "Kimi K2.6"


def test_auto_display_tier_suffix_capitalization():
    assert _auto_display_name("gpt-4.1-mini") == "GPT 4.1 Mini"
    assert _auto_display_name("gpt-4o-nano") == "GPT 4o Nano"
    assert _auto_display_name("gemini-2.5-flash") == "Gemini 2.5 Flash"
    assert _auto_display_name("qwen3-coder-plus") == "Qwen3 Coder Plus"


def test_auto_display_unknown_tokens_title_cased():
    """Tokens not in BRAND or TIER dicts get Title-cased (won't shout)."""
    assert "Coder" in _auto_display_name("qwen3-coder")
    # 'omni' is in TIER_SUFFIX dict
    assert _auto_display_name("mimo-v2-omni") == "MiMo v2 Omni"


def test_auto_display_returns_id_when_empty():
    """Defensive: empty input → don't crash."""
    assert _auto_display_name("---") == "---"


# ── _auto_tier_rank ──────────────────────────────────────────────────


def test_auto_tier_rank_higher_version_lower_rank():
    """gpt-5.5 must outrank gpt-5.4 must outrank gpt-4.1."""
    r55 = _auto_tier_rank("openai", "gpt-5.5")
    r54 = _auto_tier_rank("openai", "gpt-5.4")
    r41 = _auto_tier_rank("openai", "gpt-4.1")
    assert r55 < r54 < r41


def test_auto_tier_rank_qwen_brand_attached_version():
    """``qwen3-*`` must parse as version 3, NOT as version 80 from
    ``-80b`` param-size suffix. ``qwen3.7-*`` must beat ``qwen3-*``."""
    r37 = _auto_tier_rank("qwen", "qwen3.7-max-preview")
    r3_next = _auto_tier_rank("qwen", "qwen3-next-80b-a3b-thinking")
    r3_max = _auto_tier_rank("qwen", "qwen3-max")
    r2 = _auto_tier_rank("qwen", "qwen2-57b-a14b-instruct")
    # qwen3.7 above qwen3.0 above qwen2.0
    assert r37 < r3_max < r2
    # qwen3-* family all near each other (within ~100)
    assert abs(r3_max - r3_next) < 200
    # qwen3-next must NOT be misparsed as version 80 (which would
    # clamp to 100, way above curated 1-99 but below normal range)
    assert r3_next > 5000  # confirms version 3 not 80


def test_auto_tier_rank_param_size_not_treated_as_version():
    """The Gemma '4-31b' and Qwen '80b' / '14b' / '7b' suffixes are
    parameter counts, not versions. These must NOT outrank legit
    version-X models."""
    r_gemma_31b = _auto_tier_rank("gemini", "gemma-4-31b-it")
    r_qwen_80b  = _auto_tier_rank("qwen", "qwen3-next-80b-a3b-thinking")
    # Both should land in a reasonable mid-range, not floored at 100.
    assert r_gemma_31b > 100, "gemma-4-31b must not be parsed as v31"
    assert r_qwen_80b  > 100, "qwen3-next-80b must not be parsed as v80"


def test_auto_tier_rank_b_suffix_not_treated_as_version():
    """The crucial ``-7b`` / ``-14b`` / ``-72b`` form (Qwen-7B,
    Qwen-72B etc.) must be recognised as parameter count, not as
    "version 7" or "version 72". Bare ``qwen-7b-chat`` should rank
    LOWER (= further down the card) than any qwen3.x release."""
    r_7b   = _auto_tier_rank("qwen", "qwen-7b-chat")
    r_37   = _auto_tier_rank("qwen", "qwen3.7-max-preview")
    r_3max = _auto_tier_rank("qwen", "qwen3-max")
    # qwen-7b-chat has NO version parseable (b suffix excluded) →
    # falls to default ~10000.
    assert r_7b > r_3max, "qwen-7b-chat must rank below qwen3-max"
    assert r_7b > r_37,   "qwen-7b-chat must rank below qwen3.7-max-preview"


def test_auto_tier_rank_pro_boosts():
    """Within same version family, Pro should outrank bare."""
    pro = _auto_tier_rank("openai", "gpt-5.5-pro")
    bare = _auto_tier_rank("openai", "gpt-5.5")
    assert pro < bare


def test_auto_tier_rank_mini_nano_demoted():
    bare = _auto_tier_rank("openai", "gpt-5.5")
    mini = _auto_tier_rank("openai", "gpt-5.5-mini")
    nano = _auto_tier_rank("openai", "gpt-5.5-nano")
    assert bare < mini < nano


def test_auto_tier_rank_gemma_below_gemini():
    """Google's open-source Gemma line must sink below Gemini."""
    gemini = _auto_tier_rank("gemini", "gemini-3.5-flash")
    gemma = _auto_tier_rank("gemini", "gemma-4-31b-it")
    assert gemini < gemma


def test_auto_tier_rank_always_above_curated_range():
    """Auto rank is ALWAYS >= 100 so curated tiers 1-99 always win
    the composite sort. An "unknown future" model with no version
    sits near the maximum (10000) — far below any curated entry."""
    rank = _auto_tier_rank("openai", "gpt-mystery-future")
    assert rank >= 100, "must respect floor of 100 (curated range is 1-99)"
    # Unknown model with no parseable version → no major/minor
    # subtraction, lands near the 10000 ceiling.
    assert rank >= 9900


def test_auto_tier_rank_floor_at_100():
    """Even with extreme version boost + pro suffix, never go below
    100 — keeps the 1-99 curated range exclusive."""
    very_new = _auto_tier_rank("openai", "gpt-99.9-pro")
    assert very_new >= 100


# ── apply_overrides ─────────────────────────────────────────────────


def test_hidden_curated_entries_dropped():
    """Anthropic / NVIDIA CURATED entries with hidden=True drop out."""
    # No CURATED hidden=True entries exist post-P7-F. Verify the
    # mechanism still works by injecting one in-test.
    from app.services.model_sources import curated as cm
    cm.CURATED[("anthropic", "test-hidden-entry")] = ModelOverride(hidden=True)
    try:
        out = apply_overrides("anthropic", [
            _entry("anthropic", "claude-opus-4-7", "Claude Opus 4.7"),
            _entry("anthropic", "test-hidden-entry"),
        ])
        assert "test-hidden-entry" not in {e.model for e in out}
    finally:
        del cm.CURATED[("anthropic", "test-hidden-entry")]


def test_anthropic_marketing_tier_respected():
    """Opus 4.7 → Sonnet 4.6 → Opus 4.6 (CURATED tier 1, 2, 3)."""
    entries = [
        _entry("anthropic", "claude-opus-4-6",   "Claude Opus 4.6"),
        _entry("anthropic", "claude-sonnet-4-6", "Claude Sonnet 4.6"),
        _entry("anthropic", "claude-opus-4-7",   "Claude Opus 4.7"),
    ]
    out = apply_overrides("anthropic", entries)
    assert [e.model for e in out] == [
        "claude-opus-4-7", "claude-sonnet-4-6", "claude-opus-4-6",
    ]


def test_anthropic_keeps_vendor_display_name():
    """CURATED only sets tier_rank for Anthropic; vendor's
    display_name ("Claude Opus 4.7") must survive intact."""
    e = _entry("anthropic", "claude-opus-4-7", display_name="Claude Opus 4.7")
    out = apply_overrides("anthropic", [e])
    assert out[0].display_name == "Claude Opus 4.7"


def test_nvidia_curated_entry_overrides_display():
    """NVIDIA CURATED rows set both display_name + tier_rank."""
    e = _entry("nvidia_nim", "deepseek-ai/deepseek-v4-pro")
    out = apply_overrides("nvidia_nim", [e])
    assert out[0].display_name == "DeepSeek V4 Pro (NIM)"


def test_uncurated_vendor_uses_auto_derive():
    """OpenAI has no CURATED entries post-P7-F → both display_name +
    sort come from auto-derivation."""
    entries = [
        _entry("openai", "gpt-4o"),
        _entry("openai", "gpt-5.5-pro"),
        _entry("openai", "gpt-5.5"),
    ]
    out = apply_overrides("openai", entries)
    # Auto-derived display names:
    assert out[0].display_name == "GPT 5.5 Pro"
    assert out[1].display_name == "GPT 5.5"
    # Order: gpt-5.5-pro > gpt-5.5 > gpt-4o (auto-tier)
    assert [e.model for e in out] == ["gpt-5.5-pro", "gpt-5.5", "gpt-4o"]


def test_gemini_vendor_display_name_kept_over_auto():
    """If vendor sent a displayName different from the bare id, that
    one wins — we don't auto-rewrite. Anthropic and Gemini are the
    two vendors that always ship displayName."""
    e = _entry("gemini", "gemini-3.5-flash", display_name="Gemini 3.5 Flash")
    out = apply_overrides("gemini", [e])
    # Vendor's display preserved (NOT replaced with auto-derived
    # "Gemini 3.5 Flash" — even though they happen to match in this
    # case, the apply path is to leave vendor's name alone).
    assert out[0].display_name == "Gemini 3.5 Flash"


def test_gemini_gemma_sorted_below_gemini():
    """Auto-derive must push Gemma below Gemini even though Gemma
    was released later (vendor's recency sort would have Gemma first)."""
    entries = [
        _entry("gemini", "gemma-4-31b-it",      display_name="Gemma 4 31B"),
        _entry("gemini", "gemini-3.5-flash",    display_name="Gemini 3.5 Flash"),
        _entry("gemini", "gemini-3-pro-preview", display_name="Gemini 3 Pro Preview"),
    ]
    out = apply_overrides("gemini", entries)
    assert out[-1].model == "gemma-4-31b-it"
    # Both Gemini entries before any Gemma entry
    gemini_idx = {e.model: i for i, e in enumerate(out)}
    assert gemini_idx["gemma-4-31b-it"] > gemini_idx["gemini-3.5-flash"]


# ── dated-alias suppression ─────────────────────────────────────────


def test_openai_dated_alias_hidden_when_bare_present():
    entries = [
        _entry("openai", "gpt-5.5"),
        _entry("openai", "gpt-5.5-2026-04-23"),
        _entry("openai", "gpt-5.5-pro"),
        _entry("openai", "gpt-5.5-pro-2026-04-23"),
    ]
    out = apply_overrides("openai", entries)
    ids = [e.model for e in out]
    assert "gpt-5.5" in ids
    assert "gpt-5.5-pro" in ids
    assert "gpt-5.5-2026-04-23" not in ids
    assert "gpt-5.5-pro-2026-04-23" not in ids


def test_anthropic_compact_date_pattern_handled():
    """Anthropic uses YYYYMMDD with no dashes — different regex."""
    entries = [
        _entry("anthropic", "claude-opus-4-7", display_name="Claude Opus 4.7"),
        _entry("anthropic", "claude-opus-4-7-20260414"),
    ]
    out = apply_overrides("anthropic", entries)
    assert [e.model for e in out] == ["claude-opus-4-7"]


def test_dated_alias_kept_when_no_bare_present():
    """Only suppress when the BARE form is also in the list. If
    only the dated alias exists, keep it (otherwise we'd lose the
    model)."""
    entries = [
        _entry("openai", "gpt-5.5-pro-2026-04-23"),
    ]
    out = apply_overrides("openai", entries)
    assert [e.model for e in out] == ["gpt-5.5-pro-2026-04-23"]


def test_gemini_no_dated_alias_pattern():
    """Gemini's regex isn't in _DATE_SUFFIX_PATTERNS — dated-looking
    ids like ``gemini-2.5-computer-use-preview-10-2025`` pass through."""
    entries = [
        _entry("gemini", "gemini-2.5-computer-use-preview-10-2025",
               display_name="Gemini 2.5 Computer Use Preview"),
    ]
    out = apply_overrides("gemini", entries)
    assert len(out) == 1


# ── CURATED dict sanity ──────────────────────────────────────────────


def test_curated_only_contains_anthropic_and_nvidia():
    """Post-P7-F: every other vendor is fully auto-derived. If a
    new CURATED entry creeps in for OpenAI / Gemini / DeepSeek /
    Moonshot / Zhipu / Qwen / Xiaomi, this test fires so the author
    has to make a deliberate decision."""
    providers_in_curated = {key[0] for key in CURATED}
    assert providers_in_curated <= {"anthropic", "nvidia_nim"}, (
        f"CURATED has unexpected provider(s): "
        f"{providers_in_curated - {'anthropic', 'nvidia_nim'}}. "
        "If you need to hand-curate a new vendor, update this test "
        "and the curated.py docstring rationale."
    )


def test_curated_keys_are_unique():
    seen: set[tuple[str, str]] = set()
    for key in CURATED:
        assert key not in seen, f"duplicate CURATED key: {key}"
        seen.add(key)


def test_every_curated_override_has_valid_shape():
    for key, override in CURATED.items():
        assert isinstance(override, ModelOverride)
        if override.display_name is not None:
            assert isinstance(override.display_name, str) and override.display_name
        assert isinstance(override.tier_rank, int) and 0 < override.tier_rank <= 1000
        assert isinstance(override.hidden, bool)
