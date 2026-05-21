"""Dreaming worker — nightly / per-record memory synthesis.

Why dreaming
============
Realtime extraction is conservative — it only picks up strong signals
from a single turn. Many real insights only emerge across multiple
sessions (user says "I'll try X" in session 1, reports "X worked" in
session 2 → only then should X get promoted from "trying" to
"internalised"). Dreaming sees the full conversation window of an
interview record and can synthesise these multi-session patterns.

Trigger model (two paths, both supported)
=========================================

Path A — per-record idle:
  A scheduler scans for ``interview_records`` where
    (last_dreamed_at IS NULL OR updated_at > last_dreamed_at)
    AND no chat_message added in the last 24h (debrief is "quiet")
  and dreams each one.

Path C — nightly batch:
  A Celery beat job at the user's local ~03:00 runs the same scan but
  also requires the user has been inactive for ≥4h (don't dream
  while the user is actively chatting).

Cursor + concurrency
====================

Each record has ``last_dreamed_at``. Dreaming bumps it to ``now()`` on
success. The next scan will skip records whose ``updated_at`` hasn't
changed since their last dream — saves LLM calls.

The work itself runs under ``user_memory_lock_sync`` (sync because
Celery is sync). Realtime extraction holds the async sibling lock.
The two are the same Redis key, so they serialise correctly.

Conflict avoidance
==================

The LLM gets the CURRENT memory snapshot (after any realtime writes
that happened during the record period). It produces patches that are
deltas ON TOP of that snapshot. The patch protocol's exact-line-match
means a patch whose ``match_line`` is no longer present (because
realtime extraction already updated it) is dropped — not allowed to
revert a newer state.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.models.chat import ChatMessage, ChatSession
from app.models.interview_record import InterviewRecord
from app.rag.embeddings import agent_fast_llm
from app.services.memory import (
    habit_doc_service,
    knowledge_doc_service,
    strategy_doc_service,
    user_profile_doc_service,
)
from app.services.memory._user_memory_lock import user_memory_lock_sync
from app.services.memory.prompts import DREAMING_PROMPT

logger = logging.getLogger(__name__)


# ── Trigger parameters ────────────────────────────────────────────────

# Path A: a record's last chat message must be at least this old before
# dreaming considers it. Avoids dreaming a record while the user is
# actively still talking about it.
RECORD_QUIET_HOURS = 24

# Path C: nightly batch only dreams when the user has been inactive
# globally for at least this long. Covers normal sleep windows.
USER_INACTIVE_HOURS_FOR_BATCH = 4


# ──────────────────────────────────────────────────────────────────────
# Selection: which records need dreaming?
# ──────────────────────────────────────────────────────────────────────


def select_candidate_records(
    *,
    user_id: str | None = None,
    require_user_inactive: bool = False,
    limit: int = 50,
) -> list[InterviewRecord]:
    """Return records that need a dream pass.

    Filters:
      * Status is ``completed`` (we don't dream half-analysed records)
      * ``updated_at > last_dreamed_at`` OR ``last_dreamed_at IS NULL``
      * Last chat_message on any debrief session of this record is at
        least ``RECORD_QUIET_HOURS`` old (record is "settled")
      * If ``require_user_inactive`` is True, the user has had no
        new chat_message anywhere in the last
        ``USER_INACTIVE_HOURS_FOR_BATCH`` hours

    ``user_id=None`` means scan everyone (Path C nightly batch).
    """
    now = datetime.utcnow()
    quiet_threshold = now - timedelta(hours=RECORD_QUIET_HOURS)
    user_idle_threshold = now - timedelta(hours=USER_INACTIVE_HOURS_FOR_BATCH)

    db: Session = SessionLocal()
    try:
        q = (
            db.query(InterviewRecord)
            .filter(InterviewRecord.status == "completed")
        )
        if user_id is not None:
            q = q.filter(InterviewRecord.user_id == user_id)
        # Records that have new content since their last dream
        # (or have never been dreamed).
        from sqlalchemy import or_
        q = q.filter(
            or_(
                InterviewRecord.last_dreamed_at.is_(None),
                InterviewRecord.updated_at > InterviewRecord.last_dreamed_at,
            )
        )
        # Limit at the SQL layer; we'll filter quiet/inactive below.
        candidates = q.order_by(InterviewRecord.updated_at.asc()).limit(limit * 2).all()

        out: list[InterviewRecord] = []
        for rec in candidates:
            # Skip records whose debrief sessions are still hot.
            latest_msg_at = _latest_debrief_message_at(db, rec.id)
            if latest_msg_at is None:
                # No debrief chat at all → nothing to dream over.
                continue
            if latest_msg_at > quiet_threshold:
                continue
            if require_user_inactive:
                # Path C check: this user has been globally inactive
                # for the batch window.
                user_latest = _latest_user_chat_at(db, rec.user_id)
                if user_latest is not None and user_latest > user_idle_threshold:
                    continue
            out.append(rec)
            if len(out) >= limit:
                break
        return out
    finally:
        db.close()


def _latest_debrief_message_at(db: Session, record_id: str) -> datetime | None:
    """Most recent ChatMessage timestamp across all debrief sessions of
    this record. Returns None if there are none."""
    row = (
        db.query(ChatMessage.created_at)
        .join(ChatSession, ChatSession.id == ChatMessage.session_id)
        .filter(
            ChatSession.interview_id == record_id,
            ChatSession.session_type == "debrief",
        )
        .order_by(ChatMessage.created_at.desc())
        .first()
    )
    return row[0] if row else None


def _latest_user_chat_at(db: Session, user_id: str) -> datetime | None:
    """Most recent ChatMessage timestamp across all of the user's
    sessions, used to check whether they're currently active."""
    row = (
        db.query(ChatMessage.created_at)
        .join(ChatSession, ChatSession.id == ChatMessage.session_id)
        .filter(ChatSession.user_id == user_id)
        .order_by(ChatMessage.created_at.desc())
        .first()
    )
    return row[0] if row else None


# ──────────────────────────────────────────────────────────────────────
# Single-record dream
# ──────────────────────────────────────────────────────────────────────


def dream_for_record(record_id: str) -> dict[str, Any]:
    """Run one dream pass for a single record.

    Returns a small summary dict for logging. Never raises in normal
    operation — failures are logged and ``error`` is set on the
    return so the Celery task can decide whether to retry.
    """
    summary: dict[str, Any] = {
        "record_id": record_id,
        "user_id": None,
        "applied": 0,
        "dropped": 0,
        "skipped": 0,
        "skipped_reason": None,
        "error": None,
    }

    db: Session = SessionLocal()
    try:
        record = db.query(InterviewRecord).filter(InterviewRecord.id == record_id).first()
        if record is None:
            summary["skipped_reason"] = "record not found"
            return summary
        summary["user_id"] = record.user_id
        user_id = record.user_id
    finally:
        db.close()

    with user_memory_lock_sync(user_id):
        # Re-check inside the lock — another worker may have just
        # dreamed this record.
        db = SessionLocal()
        try:
            record = db.query(InterviewRecord).filter(InterviewRecord.id == record_id).first()
            if record is None:
                summary["skipped_reason"] = "record disappeared"
                return summary
            if (
                record.last_dreamed_at is not None
                and record.updated_at is not None
                and record.last_dreamed_at >= record.updated_at
            ):
                summary["skipped_reason"] = "already dreamed (no new content)"
                return summary

            # Load record period conversation
            messages = _load_record_debrief_messages(db, record_id)
            if not messages:
                # Nothing to dream — still bump cursor so we don't keep
                # rescanning a quiet record.
                record.last_dreamed_at = datetime.utcnow()
                db.commit()
                summary["skipped_reason"] = "no debrief messages"
                return summary

            snapshot = _load_snapshot_for_dream(
                user_id, _topics_mentioned_in_messages(user_id, messages),
            )
            prompt = DREAMING_PROMPT.format(
                record_id=record_id,
                user_profile=snapshot["user_profile"] or "（空）",
                knowledge_index="\n".join(snapshot["knowledge_index"]) or "（暂无主题）",
                knowledge_active_bodies=snapshot["active_bodies"] or "（无相关主题主体）",
                strategy_body=snapshot["strategy"] or "（空）",
                habit_body=snapshot["habit"] or "（空）",
                record_messages=_format_record_messages(messages),
                record_debrief_summary=(record.debrief_summary or "（无客观摘要）"),
            )

            try:
                # NB: this is a sync call from a sync worker — wrap the
                # async LLM in run_async via the worker helper.
                from app.worker.tasks import run_async
                response = run_async(agent_fast_llm.acomplete(
                    prompt,
                    response_format={"type": "json_object"},
                ))
                patches = _parse_json_patches(str(response.text))
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "dreaming: LLM call failed record=%s user=%s: %s",
                    record_id, user_id, exc,
                )
                summary["error"] = f"llm_failed: {type(exc).__name__}"
                return summary

            # Dispatch patches. Pass the worker's db so patches + the
            # last_dreamed_at cursor bump commit in a SINGLE transaction.
            # If we used per-service own-sessions and crashed before the
            # cursor bump, the next scan would re-dream the same record
            # → duplicate LLM call. Atomic commit eliminates that wasted-
            # work window. The exact-line-match patch protocol still
            # bounds the damage if a duplicate dream slips through.
            applied, dropped, skipped = _dispatch_dream_patches(
                db=db,
                user_id=user_id,
                record_id=record_id,
                patches=patches,
            )
            summary["applied"] = applied
            summary["dropped"] = dropped
            summary["skipped"] = skipped

            # Bump cursor. Always — even when patches=0, so we don't
            # repeatedly process a quiet record.
            record.last_dreamed_at = datetime.utcnow()
            db.commit()
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            logger.exception(
                "dreaming: hard failure record=%s user=%s", record_id, user_id,
            )
            summary["error"] = f"hard_failure: {type(exc).__name__}: {exc}"
        finally:
            db.close()

    logger.info(
        "dreaming: record=%s user=%s applied=%d dropped=%d skipped=%d reason=%s err=%s",
        record_id, summary["user_id"], summary["applied"],
        summary["dropped"], summary["skipped"],
        summary["skipped_reason"], summary["error"],
    )
    return summary


# ──────────────────────────────────────────────────────────────────────
# Snapshot helpers
# ──────────────────────────────────────────────────────────────────────


def _load_snapshot_for_dream(user_id: str, mentioned_topics: list[str]) -> dict[str, Any]:
    """Same as realtime_extraction snapshot but also loads the body of
    knowledge_doc topics that came up in the record's conversation —
    dreaming may patch them, so it needs to see their current state.
    """
    knowledge_index = knowledge_doc_service.list_index_lines(user_id, max_topics=50)

    active_bodies: list[str] = []
    for topic in mentioned_topics:
        doc = knowledge_doc_service.load(user_id, topic)
        if doc and (doc.body or "").strip():
            active_bodies.append(f"### {topic}\n{doc.body}")

    return {
        "user_profile": user_profile_doc_service.load(user_id),
        "knowledge_index": knowledge_index,
        "active_bodies": "\n\n".join(active_bodies),
        "strategy": strategy_doc_service.load(user_id),
        "habit": habit_doc_service.load(user_id),
    }


def _topics_mentioned_in_messages(user_id: str, messages: list[dict]) -> list[str]:
    """Return the user's existing topics that appear in the message text.

    Pre-loading bodies for these topics into the dreaming prompt lets
    the LLM produce ``match_line`` patches against the real current
    body rather than hallucinating against an empty body.

    Filters:
      * Topic name must be at least 3 characters to count as a hit.
        Otherwise short ones (``"C"``, ``"Go"``, ``"AI"``) would match
        substrings of unrelated words (``"Go" in "google"``) and load
        many irrelevant topic bodies, blowing the dreaming prompt's
        token budget.
      * For multi-byte topics (CJK ≥ 3 chars) substring is fine.
      * For ASCII topics (latin letters), require word-boundary match
        so ``"TCP"`` matches ``"TCP/IP"`` but not part of a longer
        word that happens to contain those letters.
    """
    text = "\n".join(str(m.get("content") or "") for m in messages)
    if not text.strip():
        return []
    topics = knowledge_doc_service.load_all(user_id)
    hits: list[str] = []
    for d in topics:
        if not d.topic or len(d.topic) < 3:
            continue
        if _topic_in_text(d.topic, text):
            hits.append(d.topic)
    return hits


def _topic_in_text(topic: str, text: str) -> bool:
    """Word-aware substring check for topic name in conversation text."""
    if not topic or not text:
        return False
    # ASCII-only topic → word boundary required to avoid false positives
    # like "Go" matching "google".
    if all(ord(c) < 128 for c in topic):
        # \b doesn't always work for symbol-containing topics like
        # "C#" — fall back to a literal substring with surrounding
        # boundary chars on either side.
        pattern = r"(?:^|[^A-Za-z0-9])" + re.escape(topic) + r"(?:$|[^A-Za-z0-9])"
        return re.search(pattern, text) is not None
    # CJK / mixed-script topic — plain substring is fine.
    return topic in text


# ──────────────────────────────────────────────────────────────────────
# Messages
# ──────────────────────────────────────────────────────────────────────


def _load_record_debrief_messages(db: Session, record_id: str) -> list[dict]:
    """Concatenate all ChatMessage rows under all debrief sessions of
    this record, ordered by time."""
    rows = (
        db.query(ChatMessage)
        .join(ChatSession, ChatSession.id == ChatMessage.session_id)
        .filter(
            ChatSession.interview_id == record_id,
            ChatSession.session_type == "debrief",
        )
        .order_by(ChatMessage.created_at.asc(), ChatMessage.seq.asc())
        .all()
    )
    return [
        {
            "role": r.role,
            "content": r.content,
            "created_at": r.created_at.isoformat() if r.created_at else "",
        }
        for r in rows
    ]


def _format_record_messages(messages: list[dict]) -> str:
    """Render messages for the dreaming prompt. Caps total length to
    avoid blowing the context window.

    Strategy:
      * Keep the END of the conversation (insights typically land
        at the end of a debrief). If over budget, drop from the front.
      * **Floor**: even if a single message body exceeds the budget,
        emit at least its tail so the LLM has SOMETHING to dream over.
        Otherwise an unusually long message would mean the dreaming
        prompt only sees the elision banner and produces ``[]``,
        which silently bumps the cursor without learning anything.
    """
    MAX_CHARS = 30_000
    rendered: list[str] = []
    for m in messages:
        role = m.get("role") or "?"
        ts = m.get("created_at") or ""
        body = (m.get("content") or "").strip()
        if not body:
            continue
        # Defang embedded markers in the body the same way the realtime
        # path does — prevents prompt injection via record messages.
        flat = body.replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
        rendered.append(f"[{ts}] {role}: {flat}")

    if not rendered:
        return ""

    # Walk from the end backwards, accumulating until budget exceeded.
    kept: list[str] = []
    used = 0
    for line in reversed(rendered):
        if used + len(line) + 1 > MAX_CHARS:
            break
        kept.append(line)
        used += len(line) + 1
    kept.reverse()

    if not kept:
        # Every message exceeds the budget — at least include the tail
        # of the most recent message so the LLM has actual content.
        last = rendered[-1]
        kept = [last[-MAX_CHARS:]]
        if len(rendered) > 1:
            kept.insert(
                0,
                f"[... earlier {len(rendered) - 1} messages elided; "
                "the message below was truncated to fit token budget ...]",
            )
        else:
            kept.insert(0, "[... single oversized message truncated to fit token budget ...]")
    elif len(kept) < len(rendered):
        kept.insert(
            0,
            f"[... earlier {len(rendered) - len(kept)} messages elided "
            "for token budget ...]",
        )

    return "\n".join(kept)


# ──────────────────────────────────────────────────────────────────────
# Patch parsing (shared form with realtime)
# ──────────────────────────────────────────────────────────────────────


# Anchored on ``[{ ... }]`` — see realtime_extraction._JSON_ARRAY_RE.
_JSON_ARRAY_RE = re.compile(r"\[\s*\{[\s\S]*\}\s*\]", re.MULTILINE)


def _parse_json_patches(raw_text: str) -> list[dict[str, Any]]:
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
            logger.warning("dreaming: cannot parse LLM output: %s", text[:200])
            return []
        try:
            parsed = json.loads(m.group(0))
        except json.JSONDecodeError as exc:
            logger.warning("dreaming: nested JSON parse failed: %s", exc)
            return []

    if isinstance(parsed, dict):
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


def _dispatch_dream_patches(
    *,
    db: Session,
    user_id: str,
    record_id: str,
    patches: list[dict[str, Any]],
) -> tuple[int, int, int]:
    """Apply patches via per-type services within ``db``'s transaction.

    All writes share ``db`` so the caller can commit them atomically
    with the ``last_dreamed_at`` cursor bump.

    Returns (total_applied, total_dropped, total_skipped). Per-service
    exceptions are caught + logged; other services still run.
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

    applied = dropped = skipped = 0

    if buckets["knowledge"]:
        by_topic: dict[str, list[dict[str, Any]]] = {}
        for p in buckets["knowledge"]:
            topic = str(p.get("topic") or "").strip()
            if not topic:
                continue
            by_topic.setdefault(topic, []).append(p)
        for topic, plist in by_topic.items():
            try:
                r = knowledge_doc_service.apply_patches(
                    user_id=user_id,
                    topic=topic,
                    patches=plist,
                    change_type="patch_dreaming",
                    source_record_id=record_id,
                    db=db,
                )
                applied += r.applied
                dropped += r.dropped
                skipped += r.skipped
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "dreaming dispatch knowledge user=%s topic=%s: %s",
                    user_id, topic, exc,
                )

    if buckets["strategy"]:
        try:
            r = strategy_doc_service.apply_patches(
                user_id=user_id,
                patches=buckets["strategy"],
                change_type="patch_dreaming",
                source_record_id=record_id,
                db=db,
            )
            applied += r.applied
            dropped += r.dropped
            skipped += r.skipped
        except Exception as exc:  # noqa: BLE001
            logger.error("dreaming dispatch strategy user=%s: %s", user_id, exc)

    if buckets["habit"]:
        try:
            r = habit_doc_service.apply_patches(
                user_id=user_id,
                patches=buckets["habit"],
                change_type="patch_dreaming",
                source_record_id=record_id,
                db=db,
            )
            applied += r.applied
            dropped += r.dropped
            skipped += r.skipped
        except Exception as exc:  # noqa: BLE001
            logger.error("dreaming dispatch habit user=%s: %s", user_id, exc)

    if buckets["user_profile"]:
        # user_profile shares the dreaming transaction (checkpoint 3 fix):
        # patches + audit row land with the cursor bump in one commit,
        # so a crash between the two cannot leave the user_profile mutated
        # but the cursor un-bumped (which would cause the next nightly
        # scan to re-apply the same patches).
        try:
            stats = user_profile_doc_service.apply_patches(
                user_id, buckets["user_profile"],
                change_type="patch_dreaming",
                source_record_id=record_id,
                db=db,
            )
            applied += stats.get("applied", 0)
            dropped += stats.get("dropped", 0)
            skipped += stats.get("skipped", 0)
        except Exception as exc:  # noqa: BLE001
            logger.error("dreaming dispatch user_profile user=%s: %s", user_id, exc)

    return applied, dropped, skipped


__all__ = [
    "RECORD_QUIET_HOURS",
    "USER_INACTIVE_HOURS_FOR_BATCH",
    "dream_for_record",
    "select_candidate_records",
]
