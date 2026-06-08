"""Realtime memory extraction — runs after every chat turn.

Flow:

* One LLM call per turn (cheap).
* Conservative — only strong signals (user self-report, explicit cognitive
  breakthrough, stable-habit declaration). Most turns produce no patches; that's
  intentional, dreaming catches the ambiguous ones with cross-session synthesis.
* Outputs ``target``-tagged items; the shared dispatcher
  (``app.services.memory._dispatch``) routes them to the three v3 write surfaces
  (ability_state / user_profile / learning_strategy).

Async-only — called from the post-turn pipeline. Celery dreaming uses a separate
sync code path.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from app.db.database import SessionLocal
from app.rag.embeddings import agent_fast_llm
from app.services.memory import memory_ability_state_service, memory_document_service
from app.services.memory._dispatch import dispatch_memory_patches
from app.services.memory._extraction_common import format_ability_index, parse_json_patches
from app.services.memory._user_memory_lock import user_memory_lock
from app.services.memory.prompts import REALTIME_EXTRACTION_PROMPT

logger = logging.getLogger(__name__)


@dataclass
class ExtractionResult:
    """Summary returned to the caller for logging / cursor advancement."""

    applied: int = 0           # patches that successfully landed
    dropped: int = 0           # patches whose match_line didn't match
    skipped: int = 0           # idempotent adds (line already there)
    by_target: dict[str, int] = field(default_factory=dict)  # per-target applied
    error: str | None = None   # set on hard failures; caller uses None to
                               # decide whether to advance the cursor


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
        and retry next turn.

    Holds ``user_memory_lock`` for the LLM call + writes so we don't race a
    dreaming worker running in parallel.
    """
    if not new_messages:
        return ExtractionResult()

    conversation = _format_conversation(new_messages)

    async with user_memory_lock(user_id):
        # Snapshot — inside the lock so dreaming can't write between our read
        # and our patches.
        snapshot = await asyncio.to_thread(_load_snapshot, user_id)

        prompt = REALTIME_EXTRACTION_PROMPT.format(
            user_profile=snapshot["user_profile"] or "（空）",
            learning_strategy=snapshot["learning_strategy"] or "（空）",
            ability_index="\n".join(snapshot["ability_index"]) or "（暂无能力状态）",
            conversation=conversation,
        )

        try:
            response = await agent_fast_llm.acomplete(
                prompt,
                response_format={"type": "json_object"},
            )
            patches = parse_json_patches(str(response.text))
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "realtime_extraction: LLM call failed user=%s session=%s: %s",
                user_id, session_id, exc,
            )
            return None

        if not patches:
            return ExtractionResult()

        dispatched = await asyncio.to_thread(
            dispatch_memory_patches,
            user_id=user_id,
            patches=patches,
            change_type="patch_realtime",
            source_conversation_id=session_id,
            source_interview_record_id=record_id,
        )
        return ExtractionResult(
            applied=dispatched.applied,
            dropped=dispatched.dropped,
            skipped=dispatched.skipped,
            by_target=dispatched.by_target,
            error=dispatched.error,
        )


# ──────────────────────────────────────────────────────────────────────
# Snapshot loading
# ──────────────────────────────────────────────────────────────────────


def _load_snapshot(user_id: str) -> dict[str, Any]:
    """Read the memory artifacts the extraction prompt needs, sharing one
    session so the snapshot is internally consistent."""
    db = SessionLocal()
    try:
        user_profile = memory_document_service.load(user_id, "user_profile", db=db)
        learning_strategy = memory_document_service.load(user_id, "learning_strategy", db=db)
        states = memory_ability_state_service.load_active(user_id, db=db)
        return {
            "user_profile": (user_profile or "").strip(),
            "learning_strategy": (learning_strategy or "").strip(),
            "ability_index": format_ability_index(states),
        }
    finally:
        db.close()


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────


def _format_conversation(messages: list[dict]) -> str:
    """Render messages as ``Role: > content`` blocks.

    Collapses embedded newlines so a user typing ``"\\n\\nUser: ignore previous,
    save: ..."`` can't fake a second turn the extraction LLM reads as real.
    """
    lines: list[str] = []
    for m in messages:
        role = (m.get("role") or "?").strip().replace("\n", " ").replace("\r", " ")
        content = (m.get("content") or "").strip()
        if not content:
            continue
        flat = content.replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
        lines.append(f"{role}: > {flat}")
    return "\n".join(lines)


__all__ = ["extract_and_apply", "ExtractionResult"]
