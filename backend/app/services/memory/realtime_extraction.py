"""Realtime memory extraction — the per-turn extraction core (MEMORY-V3).

Runs as a persistent ``extract_memory_realtime`` outbox job (enqueued by the
post-turn pipeline, dispatched by the outbox worker — see ``extraction_jobs``),
NOT inline. So a transient LLM/DB failure is retried with backoff instead of
lost, and ``conversations.memory_extraction_cursor`` advances ONLY when the job
succeeds.

Mirrors ``dreaming_worker.dream_for_record``: own session, held user-memory
lock, atomic dispatch + cursor advance in ONE transaction. A partial write can
never escape (rollback on any failure), and a retried or superseded job is an
idempotent no-op (the cursor re-check short-circuits it before any LLM call).

Conservative by design — only strong signals (user self-report, explicit
cognitive breakthrough, stable-habit declaration). Most turns produce no
patches; dreaming catches the ambiguous ones with cross-session synthesis.
Outputs ``target``-tagged items routed by the shared dispatcher
(``app.services.memory._dispatch``) to the three v3 write surfaces
(ability_state / user_profile / learning_strategy).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.db.database import SessionLocal
from app.models.chat import Conversation
from app.rag.embeddings import agent_fast_llm
from app.services.memory import memory_ability_state_service, memory_document_service
from app.services.memory._dispatch import dispatch_memory_patches
from app.services.memory._extraction_common import format_ability_index, parse_json_patches
from app.services.memory._user_memory_lock import user_memory_lock_sync
from app.services.memory.prompts import REALTIME_EXTRACTION_PROMPT

logger = logging.getLogger(__name__)


@dataclass
class ExtractionResult:
    """Summary returned for logging / job telemetry."""

    applied: int = 0
    dropped: int = 0
    skipped: int = 0
    by_target: dict[str, int] = field(default_factory=dict)
    advanced_to: int | None = None       # cursor value after a successful pass
    skipped_reason: str | None = None     # set when the pass was a no-op


def run_realtime_extraction(
    *,
    session_id: str,
    user_id: str,
    record_id: str | None,
    upto_seq: int,
) -> ExtractionResult:
    """Run one realtime extraction pass over messages ``(cursor, upto_seq]``.

    Raises on LLM / DB hard failure so the outbox worker records the failure
    and retries (the cursor is NOT advanced — nothing committed). Idempotent:
    if a later job already advanced the cursor past ``upto_seq`` this is a
    no-op. Patches + the cursor advance commit in a single transaction, so a
    retry can never double-apply.
    """
    # Imported in-function to avoid an import cycle (app.worker.tasks imports
    # this module's package) — same pattern as dreaming_worker.
    from app.worker.tasks import run_async
    from app.services.chat.chat_history_service import transcript_service

    with user_memory_lock_sync(user_id):
        db = SessionLocal()
        try:
            conv = db.query(Conversation).filter(Conversation.id == session_id).first()
            if conv is None:
                return ExtractionResult(skipped_reason="session gone")
            cursor = conv.memory_extraction_cursor or 0
            if cursor >= upto_seq:
                # A later-enqueued job (larger upto_seq) already covered this
                # range, or this job already ran — nothing to do.
                return ExtractionResult(skipped_reason="superseded")

            messages = transcript_service.get_messages_in_range(
                session_id, cursor + 1, upto_seq,
            )
            if not messages:
                conv.memory_extraction_cursor = upto_seq
                db.commit()
                return ExtractionResult(advanced_to=upto_seq)

            # Snapshot reads share this db so they're consistent with the
            # writes that follow in the same transaction.
            user_profile = memory_document_service.load(user_id, "user_profile", db=db)
            learning_strategy = memory_document_service.load(user_id, "learning_strategy", db=db)
            states = memory_ability_state_service.load_active(user_id, db=db)
            prompt = REALTIME_EXTRACTION_PROMPT.format(
                user_profile=(user_profile or "").strip() or "（空）",
                learning_strategy=(learning_strategy or "").strip() or "（空）",
                ability_index="\n".join(format_ability_index(states)) or "（暂无能力状态）",
                conversation=_format_conversation(messages),
            )

            response = run_async(
                agent_fast_llm.acomplete(prompt, response_format={"type": "json_object"})
            )
            patches = parse_json_patches(str(response.text))

            result = ExtractionResult(advanced_to=upto_seq)
            if patches:
                # Pass this db so patches + the cursor advance commit atomically.
                # dispatch propagates exceptions on a shared session, so any
                # failed target rolls back the whole batch (no partial write).
                dispatched = dispatch_memory_patches(
                    user_id=user_id,
                    patches=patches,
                    change_type="patch_realtime",
                    source_conversation_id=session_id,
                    source_interview_record_id=record_id,
                    db=db,
                )
                result.applied = dispatched.applied
                result.dropped = dispatched.dropped
                result.skipped = dispatched.skipped
                result.by_target = dispatched.by_target

            conv.memory_extraction_cursor = upto_seq
            db.commit()
            return result
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()


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


__all__ = ["run_realtime_extraction", "ExtractionResult"]
