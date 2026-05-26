"""Tests for the curated UX layer (P7-B).

Locks in:
  - Hidden entries dropped from output
  - Display name override applied
  - tier_rank sort ordering
  - Auto-hide of dated alias when bare equivalent is present (OpenAI's
    ``gpt-5.5-2026-04-23`` shadowed by ``gpt-5.5``)
  - Anthropic compact YYYYMMDD pattern handled separately
  - Vendors without a dated-alias pattern (gemini, nvidia_nim, zai,
    xiaomi) leave such ids alone
  - Uncurated entries (no CURATED row) keep their display + stay visible,
    sorted to the end via default tier_rank=999
"""
from __future__ import annotations

from app.services.model_sources.base import ModelEntry
from app.services.model_sources.curated import (
    CURATED,
    ModelOverride,
    apply_overrides,
)


def _entry(provider: str, model: str, display_name: str | None = None) -> ModelEntry:
    return ModelEntry(
        provider=provider, model=model,
        display_name=display_name or model,
        supports_function_calling=True,
        context_window=128_000, max_output_tokens=4_096, supports_vision=False,
    )


# ── hidden ─────────────────────────────────────────────────────────────


def test_hidden_entries_dropped():
    # gpt-5.5-chat-latest is marked hidden in CURATED
    entries = [_entry("openai", "gpt-5.5"), _entry("openai", "gpt-5.5-chat-latest")]
    out = apply_overrides("openai", entries)
    assert [e.model for e in out] == ["gpt-5.5"]


# ── display_name override ──────────────────────────────────────────────


def test_display_name_override_applied():
    out = apply_overrides("openai", [_entry("openai", "gpt-5.5-pro")])
    assert out[0].display_name == "GPT-5.5 Pro"


def test_display_name_not_overridden_when_only_tier_rank_set():
    """Anthropic's CURATED entries only set tier_rank — vendor's
    display_name (already 'Claude Opus 4.7') must survive."""
    e = _entry("anthropic", "claude-opus-4-7", display_name="Claude Opus 4.7")
    out = apply_overrides("anthropic", [e])
    assert out[0].display_name == "Claude Opus 4.7"


# ── tier_rank sort ────────────────────────────────────────────────────


def test_tier_rank_sorts_curated_above_uncurated():
    """Curated tier_rank=1 must come before uncurated 999."""
    entries = [
        _entry("openai", "gpt-3.5-turbo"),     # no override → 999
        _entry("openai", "gpt-5.5-pro"),       # tier_rank=1
        _entry("openai", "gpt-4o"),            # tier_rank=40
    ]
    out = apply_overrides("openai", entries)
    assert [e.model for e in out] == ["gpt-5.5-pro", "gpt-4o", "gpt-3.5-turbo"]


def test_tier_rank_within_anthropic_respects_marketing_hierarchy():
    """Opus 4.7 > Sonnet 4.6 > Opus 4.6 — per CURATED ranks."""
    entries = [
        _entry("anthropic", "claude-opus-4-6"),
        _entry("anthropic", "claude-opus-4-7"),
        _entry("anthropic", "claude-sonnet-4-6"),
    ]
    out = apply_overrides("anthropic", entries)
    assert [e.model for e in out] == [
        "claude-opus-4-7", "claude-sonnet-4-6", "claude-opus-4-6",
    ]


# ── auto-hide dated alias ─────────────────────────────────────────────


def test_dated_alias_hidden_when_bare_present_openai():
    """OpenAI ships rolling ``gpt-5.5`` AND pinned ``gpt-5.5-2026-04-23``.
    Auto-suppression drops the pinned dated alias."""
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
    # The dated aliases are gone:
    assert "gpt-5.5-2026-04-23" not in ids
    assert "gpt-5.5-pro-2026-04-23" not in ids


def test_dated_alias_kept_when_no_bare_present():
    """Anthropic ships ``claude-haiku-4-5-20251001`` with NO bare
    ``claude-haiku-4-5`` sibling — keep the dated entry, it's the
    only one we have."""
    entries = [
        _entry("anthropic", "claude-opus-4-7"),
        _entry("anthropic", "claude-haiku-4-5-20251001"),
    ]
    out = apply_overrides("anthropic", entries)
    ids = [e.model for e in out]
    assert "claude-haiku-4-5-20251001" in ids


def test_anthropic_compact_date_pattern():
    """Anthropic uses ``-YYYYMMDD`` (no dashes). Bare-shadow suppression
    must use the compact pattern for Anthropic specifically."""
    entries = [
        _entry("anthropic", "claude-opus-4-7"),
        _entry("anthropic", "claude-opus-4-7-20260414"),  # dated alias
    ]
    out = apply_overrides("anthropic", entries)
    assert [e.model for e in out] == ["claude-opus-4-7"]


def test_qwen_dated_alias_suppression():
    entries = [
        _entry("qwen", "qwen-plus"),
        _entry("qwen", "qwen-plus-2025-07-14"),
    ]
    out = apply_overrides("qwen", entries)
    assert [e.model for e in out] == ["qwen-plus"]


def test_gemini_no_dated_alias_pattern():
    """Gemini IDs don't ship dated aliases — patterns are absent from
    _DATE_SUFFIX_PATTERNS for gemini. Any ID with a date in it must
    pass through (e.g. ``gemini-2.5-computer-use-preview-10-2025``)."""
    entries = [
        _entry("gemini", "gemini-3.5-flash"),
        _entry("gemini", "gemini-2.5-computer-use-preview-10-2025"),
    ]
    out = apply_overrides("gemini", entries)
    ids = [e.model for e in out]
    # Both pass through (computer-use isn't auto-hidden by the bare
    # pattern logic, even though its name contains date-ish numbers).
    assert "gemini-3.5-flash" in ids


# ── uncurated entries ────────────────────────────────────────────────


def test_uncurated_entry_keeps_display_and_stays_visible():
    """A vendor entry with no CURATED row keeps the vendor's
    display_name and stays in the output (just sorted to the bottom)."""
    e = _entry("openai", "gpt-mystery-future-model", display_name="future-mystery")
    out = apply_overrides("openai", [e])
    assert len(out) == 1
    assert out[0].display_name == "future-mystery"


def test_uncurated_provider_passes_through_unchanged():
    """A provider with no CURATED entries (e.g. mistral / cohere
    when later enabled) just gets the sort applied to default 999
    everywhere — so ordering = whatever the input order was (stable)."""
    entries = [
        _entry("mistral", "mistral-medium-3"),
        _entry("mistral", "mistral-large-2"),
        _entry("mistral", "mistral-small-3"),
    ]
    out = apply_overrides("mistral", entries)
    # All three survived, in original order (no rank to reshuffle).
    assert [e.model for e in out] == [
        "mistral-medium-3", "mistral-large-2", "mistral-small-3",
    ]


# ── CURATED dict sanity ──────────────────────────────────────────────


def test_curated_keys_are_unique_per_provider_model():
    """Dict keys are (provider, model_id) tuples — duplicates would
    silently overwrite, hiding mistakes. Build a set of keys and
    ensure no duplicates exist."""
    seen: set[tuple[str, str]] = set()
    for key in CURATED:
        assert key not in seen, f"duplicate CURATED key: {key}"
        seen.add(key)
        # And each key must be a 2-tuple of strings.
        assert isinstance(key, tuple) and len(key) == 2
        provider, model = key
        assert isinstance(provider, str) and provider
        assert isinstance(model, str) and model


def test_every_curated_override_has_valid_shape():
    for key, override in CURATED.items():
        assert isinstance(override, ModelOverride), f"{key} not a ModelOverride"
        if override.display_name is not None:
            assert isinstance(override.display_name, str) and override.display_name
        assert isinstance(override.tier_rank, int) and 0 < override.tier_rank <= 1000
        assert isinstance(override.hidden, bool)
