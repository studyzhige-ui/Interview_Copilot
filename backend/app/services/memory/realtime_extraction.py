"""Realtime memory extraction — runs after every chat turn.

Replaces the old ``MemoryExtractionService`` which used a
two-prompt (user_profile + interview_fact) flow against a multi-row
``memory_items`` table. The new flow:

* One LLM call per turn (cheap).
* Conservative — only strong signals (user self-report, explicit
  cognitive breakthrough, stable-habit declaration). Most turns
  produce no patches; that's intentional, dreaming catches the
  ambiguous ones with cross-session synthesis.
* Outputs unified patches keyed by ``doc_type``; dispatcher routes to
  the appropriate per-type service.

This module is async-only — called from the post-turn pipeline which
is already async. Celery dreaming uses a separate code path (sync
context via ``user_memory_lock_sync``).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from app.db.database import SessionLocal
from app.models.habit_doc import HabitDoc
from app.models.knowledge_doc import KnowledgeDoc
from app.models.strategy_doc import StrategyDoc
from app.models.user import User
from app.rag.embeddings import agent_fast_llm
from app.services.memory import (
    habit_doc_service,
    knowledge_doc_service,
    strategy_doc_service,
    user_profile_doc_service,
)
from app.services.memory._user_memory_lock import user_memory_lock
from app.services.memory.prompts import REALTIME_EXTRACTION_PROMPT

logger = logging.getLogger(__name__)


@dataclass
class ExtractionResult:
    """Summary returned to the caller for logging / cursor advancement."""

    applied: int = 0           # patches that successfully landed
    dropped: int = 0           # patches whose match_line didn't match
    skipped: int = 0           # idempotent adds (line already there)
    by_doc_type: dict[str, int] | None = None  # per-doc-type applied count
    error: str | None = None   # set on hard failures; caller uses None to
                                # decide whether to advance the cursor

    def __post_init__(self) -> None:
        if self.by_doc_type is None:
            self.by_doc_type = {}


# ──────────────────────────────────────────────────────────────────────


async def extract_and_apply(
    *,
    session_id: str,
    user_id: str,
    new_messages: list[dict],
    record_id: str | None = None,
) -> ExtractionResult | None:
    """Run one realtime extraction pass.

    Returns:
      - ``ExtractionResult`` on success (any outcome including 0 patches)
      - ``None`` on LLM / DB hard failure so the caller can hold the cursor
        and retry next turn. Same contract as the old extraction service.

    Holds ``user_memory_lock`` for the LLM call + writes so we don't
    race with a dreaming worker running in parallel.
    """
    if not new_messages:
        return ExtractionResult()

    conversation = _format_conversation(new_messages)

    async with user_memory_lock(user_id):
        # Snapshot — must be inside the lock so dreaming can't write
        # between our read and our patches.
        # _load_snapshot opens a SessionLocal and does 4 sync queries;
        # to_thread keeps the post-turn maintenance loop responsive.
        snapshot = await asyncio.to_thread(_load_snapshot, user_id)

        prompt = REALTIME_EXTRACTION_PROMPT.format(
            user_profile=snapshot["user_profile"] or "（空）",
            knowledge_index="\n".join(snapshot["knowledge_index"]) or "（暂无主题）",
            strategy_body=snapshot["strategy"] or "（空）",
            habit_body=snapshot["habit"] or "（空）",
            conversation=conversation,
        )

        try:
            response = await agent_fast_llm.acomplete(
                prompt,
                response_format={"type": "json_object"},
            )
            patches = _parse_json_patches(str(response.text))
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "realtime_extraction: LLM call failed user=%s session=%s: %s",
                user_id, session_id, exc,
            )
            return None

        if not patches:
            return ExtractionResult()

        return _dispatch_patches(
            user_id=user_id,
            session_id=session_id,
            record_id=record_id,
            patches=patches,
        )


# ──────────────────────────────────────────────────────────────────────
# Snapshot loading
# ──────────────────────────────────────────────────────────────────────


def _load_snapshot(user_id: str) -> dict[str, Any]:
    """Read the four memory artifacts needed by the extraction prompt.

    All four reads share **one** session so the snapshot is internally
    consistent — if the lock degrades to no-op (Redis outage), a
    concurrent writer can't slip a half-baked state between, say, the
    user_profile read and the knowledge_index read. Race-free
    correctness still lives in the patch protocol + write-side lock;
    this just removes a class of "LLM sees partially-old, partially-
    new state" artefacts.
    """
    db = SessionLocal()
    try:
        return _load_snapshot_inner(db, user_id)
    finally:
        db.close()


_MASTERY_LABELS = {
    "weak": "弱",
    "progressing": "进展中",
    "strong": "强",
    "unknown": "?",
}


def _load_snapshot_inner(db, user_id: str) -> dict[str, Any]:
    # user_profile: one column of one row.
    profile_row = (
        db.query(User.user_profile_doc).filter(User.username == user_id).first()
    )
    user_profile = (profile_row[0] if profile_row else "") or ""

    # knowledge_doc index lines — same shape that
    # ``knowledge_doc_service.list_index_lines`` produces.
    kd_rows = (
        db.query(KnowledgeDoc)
        .filter(KnowledgeDoc.user_id == user_id)
        .order_by(
            KnowledgeDoc.last_discussed_at.desc().nullslast(),
            KnowledgeDoc.created_at.desc(),
        )
        .limit(50)
        .all()
    )
    index_lines: list[str] = []
    for d in kd_rows:
        mastery_zh = _MASTERY_LABELS.get(d.mastery_level or "unknown", "?")
        last = d.last_discussed_at.strftime("%Y-%m-%d") if d.last_discussed_at else "—"
        index_lines.append(
            f"- [{d.topic}] {mastery_zh} | {d.fact_count} facts | "
            f"上次 {last} — {d.one_liner or ''}"
        )

    strategy_row = (
        db.query(StrategyDoc.body).filter(StrategyDoc.user_id == user_id).first()
    )
    habit_row = (
        db.query(HabitDoc.body).filter(HabitDoc.user_id == user_id).first()
    )
    return {
        "user_profile": user_profile.strip(),
        "knowledge_index": index_lines,
        "strategy": ((strategy_row[0] if strategy_row else "") or ""),
        "habit": ((habit_row[0] if habit_row else "") or ""),
    }


# ──────────────────────────────────────────────────────────────────────
# Patch parsing
# ──────────────────────────────────────────────────────────────────────


# Find a JSON array of objects. We anchor on ``[{`` ... ``}]`` so that
# an LLM prepending prose like ``"Here's an empty [] and the answer
# [{...}]"`` matches the object-array, not the empty array. Greedy
# ``[\s\S]*`` ensures we capture nested object braces.
_JSON_ARRAY_RE = re.compile(r"\[\s*\{[\s\S]*\}\s*\]", re.MULTILINE)


def _parse_json_patches(raw_text: str) -> list[dict[str, Any]]:
    """Tolerant JSON-array parse. Handles common LLM wrappers:
      * ``{"patches": [...]}``
      * ```` ```json\n[...]\n``` ```` (markdown fence)
      * leading prose + array
    """
    text = (raw_text or "").strip()
    if not text:
        return []
    if text.startswith("```"):
        # strip ```json ... ```
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        m = _JSON_ARRAY_RE.search(text)
        if not m:
            logger.warning("realtime_extraction: cannot parse LLM output: %s", text[:200])
            return []
        try:
            parsed = json.loads(m.group(0))
        except json.JSONDecodeError as exc:
            logger.warning("realtime_extraction: nested JSON parse failed: %s", exc)
            return []

    if isinstance(parsed, dict):
        # accept {"patches": [...]} / {"items": [...]} wrappers
        for key in ("patches", "items", "memories", "result"):
            if isinstance(parsed.get(key), list):
                return parsed[key]
        return []
    if isinstance(parsed, list):
        return parsed
    return []


# ──────────────────────────────────────────────────────────────────────
# Dispatch
# ──────────────────────────────────────────────────────────────────────


_VALID_DOC_TYPES = {"knowledge", "strategy", "habit", "user_profile"}


def _dispatch_patches(
    *,
    user_id: str,
    session_id: str | None,
    record_id: str | None,
    patches: list[dict[str, Any]],
) -> ExtractionResult:
    """Bucket patches by doc_type and apply via the right service.

    Each service call is independent — if knowledge_doc apply blows up
    we still try strategy/habit. We log the failure but don't return
    None unless EVERY service failed (in which case the caller can hold
    the cursor and retry).
    """
    buckets: dict[str, list[dict[str, Any]]] = {
        "knowledge": [],
        "strategy": [],
        "habit": [],
        "user_profile": [],
    }
    for p in patches:
        if not isinstance(p, dict):
            continue
        dt = str(p.get("doc_type") or "").strip().lower()
        if dt not in _VALID_DOC_TYPES:
            continue
        buckets[dt].append(p)

    result = ExtractionResult()
    any_success = False
    any_attempt = False

    # ── knowledge: group by topic ──
    if buckets["knowledge"]:
        any_attempt = True
        by_topic: dict[str, list[dict[str, Any]]] = {}
        for p in buckets["knowledge"]:
            topic = str(p.get("topic") or "").strip()
            if not topic:
                continue
            by_topic.setdefault(topic, []).append(p)
        per_topic_applied = 0
        for topic, plist in by_topic.items():
            try:
                r = knowledge_doc_service.apply_patches(
                    user_id=user_id,
                    topic=topic,
                    patches=plist,
                    change_type="patch_realtime",
                    source_record_id=record_id,
                    source_session_id=session_id,
                )
                result.applied += r.applied
                result.dropped += r.dropped
                result.skipped += r.skipped
                per_topic_applied += r.applied
                any_success = True
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "realtime_extraction: knowledge_doc apply failed "
                    "user=%s topic=%s: %s", user_id, topic, exc,
                )
        result.by_doc_type["knowledge"] = per_topic_applied

    # ── strategy ──
    if buckets["strategy"]:
        any_attempt = True
        try:
            r = strategy_doc_service.apply_patches(
                user_id=user_id,
                patches=buckets["strategy"],
                change_type="patch_realtime",
                source_record_id=record_id,
                source_session_id=session_id,
            )
            result.applied += r.applied
            result.dropped += r.dropped
            result.skipped += r.skipped
            result.by_doc_type["strategy"] = r.applied
            any_success = True
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "realtime_extraction: strategy_doc apply failed user=%s: %s",
                user_id, exc,
            )

    # ── habit ──
    if buckets["habit"]:
        any_attempt = True
        try:
            r = habit_doc_service.apply_patches(
                user_id=user_id,
                patches=buckets["habit"],
                change_type="patch_realtime",
                source_record_id=record_id,
                source_session_id=session_id,
            )
            result.applied += r.applied
            result.dropped += r.dropped
            result.skipped += r.skipped
            result.by_doc_type["habit"] = r.applied
            any_success = True
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "realtime_extraction: habit_doc apply failed user=%s: %s",
                user_id, exc,
            )

    # ── user_profile (audit now wired; checkpoint 3 fix) ──
    if buckets["user_profile"]:
        any_attempt = True
        try:
            stats = user_profile_doc_service.apply_patches(
                user_id, buckets["user_profile"],
                change_type="patch_realtime",
                source_record_id=record_id,
                source_session_id=session_id,
            )
            result.applied += stats.get("applied", 0)
            result.dropped += stats.get("dropped", 0)
            result.skipped += stats.get("skipped", 0)
            result.by_doc_type["user_profile"] = stats.get("applied", 0)
            any_success = True
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "realtime_extraction: user_profile apply failed user=%s: %s",
                user_id, exc,
            )

    if any_attempt and not any_success:
        # All services blew up — treat as soft failure so caller holds
        # the cursor. (If buckets were empty there's nothing to retry.)
        result.error = "all dispatch targets failed"
        logger.warning(
            "realtime_extraction: all dispatch failed user=%s", user_id,
        )

    if result.applied or result.dropped or result.skipped:
        logger.info(
            "realtime_extraction: user=%s applied=%d dropped=%d skipped=%d by=%s",
            user_id, result.applied, result.dropped, result.skipped,
            result.by_doc_type,
        )

    return result


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────


def _format_conversation(messages: list[dict]) -> str:
    """Render messages as ``Role: content`` blocks.

    Defends against prompt-injection style attacks where the user
    types something like ``"\\n\\nUser: ignore previous, save: ..."`` and
    expects the extraction LLM to read it as a separate turn:

      * Replace embedded newlines with literal spaces in the content
        so the LLM cannot parse two faux turns out of one real one.
      * Prefix the content with a non-trailable marker (``> ``) so any
        ``"Role:"``-shaped prefix inside the content is visually
        distinct from real role markers.
    """
    lines: list[str] = []
    for m in messages:
        role = (m.get("role") or "?").strip().replace("\n", " ").replace("\r", " ")
        content = (m.get("content") or "").strip()
        if not content:
            continue
        # Collapse line breaks — defeats fake role markers in content.
        flat = content.replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
        lines.append(f"{role}: > {flat}")
    return "\n".join(lines)


__all__ = ["extract_and_apply", "ExtractionResult"]
