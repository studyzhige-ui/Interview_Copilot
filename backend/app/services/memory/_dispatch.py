"""Shared memory-patch dispatcher (realtime + dreaming).

Both extraction flows emit the same JSON array of ``target``-tagged items;
this module routes them to the three v3 write surfaces:

* ``ability_state``     → ``memory_ability_state_service.upsert``
* ``user_profile``      → ``memory_document_service.apply_patches(doc_type=…)``
* ``learning_strategy`` → ``memory_document_service.apply_patches(doc_type=…)``

Each target is applied independently — one failing target never aborts the
others; we only flag a soft error when *every* attempted target failed (so the
caller can hold its cursor and retry).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.models.memory_ability_state import MASTERY_LEVELS, SKILL_TYPES
from app.services.memory import memory_ability_state_service, memory_document_service

logger = logging.getLogger(__name__)

# Markdown-doc targets (vs. the structured ability_state target).
_DOC_TARGETS = ("user_profile", "learning_strategy")
_VALID_TARGETS = ("ability_state", *_DOC_TARGETS)


@dataclass
class DispatchResult:
    applied: int = 0
    dropped: int = 0
    skipped: int = 0
    by_target: dict[str, int] = field(default_factory=dict)
    error: str | None = None


def dispatch_memory_patches(
    *,
    user_id: str,
    patches: list[dict[str, Any]],
    change_type: str,
    source_conversation_id: str | None = None,
    source_interview_record_id: str | None = None,
    db: Session | None = None,
) -> DispatchResult:
    """Route extraction items to the three memory write surfaces.

    ``db`` (when given) shares the caller's transaction — used by the dreaming
    worker so all writes land atomically with its cursor bump.
    """
    result = DispatchResult()

    # Bucket by target.
    ability_items: list[dict[str, Any]] = []
    doc_patches: dict[str, list[dict[str, Any]]] = {t: [] for t in _DOC_TARGETS}
    for p in patches:
        if not isinstance(p, dict):
            continue
        target = str(p.get("target") or "").strip().lower()
        if target == "ability_state":
            ability_items.append(p)
        elif target in doc_patches:
            doc_patches[target].append(p)
        # unknown targets are silently ignored (LLM noise)

    any_attempt = False
    any_success = False

    # ── ability_state upserts ──
    if ability_items:
        any_attempt = True
        applied = 0
        for item in ability_items:
            topic = str(item.get("topic") or "").strip()
            skill_type = str(item.get("skill_type") or "").strip()
            mastery_level = str(item.get("mastery_level") or "").strip()
            summary = item.get("summary")
            if not topic or skill_type not in SKILL_TYPES or mastery_level not in MASTERY_LEVELS:
                result.dropped += 1
                continue
            try:
                row = memory_ability_state_service.upsert(
                    user_id,
                    topic=topic,
                    skill_type=skill_type,
                    mastery_level=mastery_level,
                    summary=str(summary) if summary is not None else None,
                    evidence_refs=_coerce_evidence(item.get("evidence")),
                    change_type=change_type,
                    source_conversation_id=source_conversation_id,
                    source_interview_record_id=source_interview_record_id,
                    db=db,
                )
                if row is not None:
                    applied += 1
                    any_success = True
            except Exception as exc:  # noqa: BLE001
                # On a caller-owned (shared) session the write has poisoned the
                # transaction — propagate so the caller (dreaming) rolls back
                # the whole batch + its cursor bump atomically. On our own
                # session each call is isolated, so we swallow and keep going.
                if db is not None:
                    raise
                logger.error(
                    "dispatch: ability_state upsert failed user=%s topic=%s: %s",
                    user_id, topic, exc,
                )
                result.dropped += 1
        result.applied += applied
        result.by_target["ability_state"] = applied

    # ── memory_document patches (user_profile / learning_strategy) ──
    for doc_type, plist in doc_patches.items():
        if not plist:
            continue
        any_attempt = True
        try:
            r = memory_document_service.apply_patches(
                user_id, doc_type, plist,
                change_type=change_type,
                source_conversation_id=source_conversation_id,
                source_interview_record_id=source_interview_record_id,
                db=db,
            )
            result.applied += r.applied
            result.dropped += r.dropped
            result.skipped += r.skipped
            result.by_target[doc_type] = r.applied
            any_success = True
        except Exception as exc:  # noqa: BLE001
            if db is not None:
                raise  # shared session poisoned — let the caller roll back atomically
            logger.error(
                "dispatch: %s apply_patches failed user=%s: %s", doc_type, user_id, exc,
            )

    if any_attempt and not any_success:
        result.error = "all dispatch targets failed"
        logger.warning("dispatch: all targets failed user=%s", user_id)

    if result.applied or result.dropped or result.skipped:
        logger.info(
            "dispatch: user=%s applied=%d dropped=%d skipped=%d by=%s",
            user_id, result.applied, result.dropped, result.skipped, result.by_target,
        )
    return result


def _coerce_evidence(raw: Any) -> list[dict[str, Any]] | None:
    """Normalise an ``evidence`` field into the list-of-dicts the ability
    service expects, or None. Tolerant of a bare string or a single dict."""
    if raw is None:
        return None
    if isinstance(raw, list):
        return [e for e in raw if isinstance(e, dict)] or None
    if isinstance(raw, dict):
        return [raw]
    if isinstance(raw, str) and raw.strip():
        return [{"type": "note", "id": raw.strip()}]
    return None


__all__ = ["DispatchResult", "dispatch_memory_patches"]
