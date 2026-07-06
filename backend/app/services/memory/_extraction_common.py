"""Shared helpers for the realtime + dreaming extraction snapshots.

Both pipelines render the same ability-state index into their prompt and parse
the same tolerant JSON-array LLM output, so the mastery labels, the index
formatter, and the parser live here once instead of being copied into each.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# How a mastery level renders in the ability index shown to the LLM.
MASTERY_LABELS = {"weak": "弱", "improving": "进步中", "stable": "稳定", "strong": "强"}
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
    from datetime import datetime

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


def parse_json_patches_ex(raw_text: str) -> tuple[list[dict[str, Any]], bool]:
    """Like :func:`parse_json_patches` but distinguishes "no patches" from
    "unparseable output": returns ``(patches, parse_ok)``. Callers that
    advance a cursor MUST hold it when ``parse_ok`` is False — advancing
    past an unparsed batch silently loses it forever (MEM-7).
    """
    patches = parse_json_patches(raw_text)
    if patches:
        return patches, True
    text = (raw_text or "").strip()
    if not text:
        return [], True
    # Non-empty output that produced zero patches: either a legitimate
    # empty array (fine) or garbage (a loss). Re-check cheaply.
    stripped = text
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        parsed = json.loads(stripped)
        ok = isinstance(parsed, (list, dict))
    except json.JSONDecodeError:
        ok = _JSON_ARRAY_RE.search(stripped) is not None
    return [], ok


def parse_json_patches(raw_text: str) -> list[dict[str, Any]]:
    """Tolerant JSON-array parse of an extraction LLM response. Handles
    ``{"patches": [...]}`` wrappers, ```` ```json ```` fences, and leading prose
    before the array."""
    text = (raw_text or "").strip()
    if not text:
        return []
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
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


__all__ = ["MASTERY_LABELS", "MAX_ABILITY_INDEX", "format_ability_index", "parse_json_patches"]
