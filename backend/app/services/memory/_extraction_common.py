"""Shared helpers for the realtime + dreaming extraction snapshots.

Both pipelines render the same ability-state index into their prompt and parse
the same tolerant JSON-array LLM output, so the mastery labels, the index
formatter, and the parser live here once instead of being copied into each.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

# How a mastery level renders in the ability index shown to the LLM.
MASTERY_LABELS = {"weak": "弱", "improving": "进步中", "stable": "稳定", "strong": "强"}
# Entries whose last evidence is at least this old get a 距上次证据 age
# annotation when injected into prompts (MEM-1). Also mirrored by
# v3_context_loader._stale_days and the FE's staleDays() — keep in sync.
STALE_ANNOTATION_DAYS = 14
_STALE_ANNOTATION_DAYS = STALE_ANNOTATION_DAYS  # module-private alias

# Cap the ability index injected into an extraction prompt — keep it cheap.
MAX_ABILITY_INDEX = 50


def format_ability_index(
    states, cap: int = MAX_ABILITY_INDEX, *, include_age: bool = True,
) -> list[str]:
    """Render active ability states as prompt index lines:
    ``- [topic] mastery (skill_type) — summary``.

    ``include_age`` appends a 距上次证据 annotation for stale entries
    (MEM-1): without it, a weak recorded three months ago reads exactly
    like one from yesterday and the LLM can't discount it.
    """
    lines: list[str] = []
    for s in states[:cap]:
        mastery = MASTERY_LABELS.get(s.mastery_level or "", s.mastery_level or "?")
        line = f"- [{s.topic}] {mastery} ({s.skill_type}) — {s.summary or ''}"
        if include_age and getattr(s, "last_evidence_at", None):
            days = (datetime.utcnow() - s.last_evidence_at).days
            if days >= _STALE_ANNOTATION_DAYS:
                line += f"（距上次证据 {days} 天）"
        lines.append(line)
    return lines



# Anchor on ``[{`` ... ``}]`` so leading prose with a stray ``[]`` matches the
# object-array, not the empty one.
_JSON_ARRAY_RE = re.compile(r"\[\s*\{[\s\S]*\}\s*\]", re.MULTILINE)


_WRAPPER_KEYS = ("patches", "items", "memories", "result")


def _strip_fences(text: str) -> str:
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text


def parse_json_patches_ex(raw_text: str) -> tuple[list[dict[str, Any]], bool]:
    """Like :func:`parse_json_patches` but distinguishes "no patches" from
    "unparseable output": returns ``(patches, parse_ok)``. Callers that
    advance a cursor MUST hold it when ``parse_ok`` is False — advancing
    past an unparsed batch silently loses it forever (MEM-7).

    ``parse_ok`` is deliberately strict: only an actual array — bare or
    under a known wrapper key — counts as a legitimate empty result. A
    dict without any list-valued wrapper key, a bare scalar, or an
    array-looking blob whose nested parse failed are all treated as
    losses (retry beats silently skipping a hallucinated-schema batch).
    """
    patches = parse_json_patches(raw_text)
    if patches:
        return patches, True
    text = (raw_text or "").strip()
    if not text:
        return [], True
    stripped = _strip_fences(text)
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        m = _JSON_ARRAY_RE.search(stripped)
        if not m:
            return [], False
        try:
            json.loads(m.group(0))
            return [], True
        except json.JSONDecodeError:
            return [], False
    if isinstance(parsed, list):
        return [], True
    if isinstance(parsed, dict):
        return [], any(isinstance(parsed.get(k), list) for k in _WRAPPER_KEYS)
    return [], False


def parse_json_patches(raw_text: str) -> list[dict[str, Any]]:
    """Tolerant JSON-array parse of an extraction LLM response. Handles
    ``{"patches": [...]}`` wrappers, ```` ```json ```` fences, and leading prose
    before the array."""
    text = _strip_fences((raw_text or "").strip())
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        m = _JSON_ARRAY_RE.search(text)
        if not m:
            logger.warning("extraction: cannot parse LLM output: %s", text[:200])
            return []
        try:
            parsed = json.loads(m.group(0))
        except json.JSONDecodeError as exc:
            logger.warning("extraction: nested JSON parse failed: %s", exc)
            return []

    if isinstance(parsed, dict):
        for key in ("patches", "items", "memories", "result"):
            if isinstance(parsed.get(key), list):
                return parsed[key]
        return []
    if isinstance(parsed, list):
        return parsed
    return []


__all__ = ["MASTERY_LABELS", "MAX_ABILITY_INDEX", "format_ability_index", "parse_json_patches"    "parse_json_patches_ex",
]
