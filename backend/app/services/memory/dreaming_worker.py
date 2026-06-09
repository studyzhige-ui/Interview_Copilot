"""Dreaming worker — nightly memory consolidation (Path B).

Why dreaming
============
Realtime extraction is conservative — it only picks up strong signals
from a single turn. Many real insights only emerge across multiple
sessions (user says "I'll try X" in session 1, reports "X worked" in
session 2 → only then should X get promoted from "trying" to
"internalised"). Dreaming sees the full conversation window of an
interview record and can synthesise these multi-session patterns.

Trigger model (Path B — single entry, nightly cron)
====================================================
After deliberation we picked **Path B over Path A (per-turn hook)**.
The short version: post-turn hook + "nightly only" time window are
contradictory (users don't chat at 03:00); since we have Celery Beat
and Claude Code's per-turn-hook constraint doesn't apply to us, a
nightly batch is the right fit for an interview-prep tool.

  Celery Beat (worker/celery_app.py beat_schedule)
       ↓ daily 03:30 Asia/Shanghai
  scan_and_dream_batch_task (worker/tasks.py)
       ↓ for each user, check 4 gates (per ``select_dreamable_users``):
       │    1. time:   NOW - users.last_dreamed_at >= 24h
       │    2. (no scan throttle — cron fires at most once per day)
       │    3. volume: new debrief messages >= NEW_MESSAGES_THRESHOLD
       │    4. lock:   user_memory_lock_sync acquired
       ↓ for each user that passes:
  select_records_for_user(user_id)
       ↓ silent >= RECORD_QUIET_HOURS, status=completed
  dream_for_record(record_id) per candidate
       ↓ after all records processed
  users.last_dreamed_at = NOW()

Cursor + concurrency
====================
``users.last_dreamed_at`` is the per-user cursor that drives gate 1.
``interview_records.last_dreamed_at`` is the per-record cursor that
makes ``dream_for_record`` idempotent (re-running it after a successful
dream is a no-op until the record gets new conversation_messages).

The work itself runs under ``user_memory_lock_sync`` (sync because
Celery is sync). Realtime extraction holds the async sibling lock.
The two are the same Redis key, so they serialise correctly even when
realtime fires during the dreaming window (unlikely at 03:30 but
possible if a user is chatting through the night).

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

import logging
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.core.user_identity import resolve_user_pk
from app.db.database import SessionLocal
from app.models.chat import ConversationMessage, Conversation
from app.models.interview_record import InterviewRecord
from app.models.user import User
from app.rag.embeddings import agent_fast_llm
from app.services.memory import memory_ability_state_service, memory_document_service
from app.services.memory._dispatch import dispatch_memory_patches
from app.services.memory._extraction_common import format_ability_index, parse_json_patches
from app.services.memory._user_memory_lock import user_memory_lock_sync
from app.services.memory.prompts import DREAMING_PROMPT

logger = logging.getLogger(__name__)


# ── Trigger parameters ────────────────────────────────────────────────

# Gate 1 — minimum hours between consecutive nightly dreams for a user.
# At cron cadence (once daily 03:30) this effectively means "at most one
# dream per user per night". Lower than 24h would allow back-to-back
# dreams if the operator ran an ad-hoc batch.
USER_MIN_HOURS_SINCE_LAST_DREAM = 24

# Gate 3 — minimum new debrief messages since users.last_dreamed_at before
# we bother to dream. Below this the LLM call is unlikely to discover
# anything new, so we save the budget for an active user. Messages are the
# sole gate signal now (the old session-count branch was dropped — a session
# with no debrief turns produces no work for the dreamer).
NEW_MESSAGES_THRESHOLD = 50

# Per-record gate — a record's last chat message must be at least this
# old before dreaming considers it. Avoids dreaming a record while the
# user is actively chatting in it. At 03:30 essentially always passes,
# but defensive against edge cases (night-owl user).
RECORD_QUIET_HOURS = 6


# ──────────────────────────────────────────────────────────────────────
# Selection: which records need dreaming?
# ──────────────────────────────────────────────────────────────────────


def select_dreamable_users(*, limit: int = 200) -> list[str]:
    """Return user_ids that pass the per-user dream gates (1 + 3).

    Gate 1 (time): the user has either NEVER been dreamed
    (``last_dreamed_at IS NULL``) OR was last dreamed more than
    ``USER_MIN_HOURS_SINCE_LAST_DREAM`` ago.

    Gate 3 (volume): since the cursor, the user has accumulated
    ``>= NEW_MESSAGES_THRESHOLD`` new debrief conversation_messages. NULL cursor →
    all history counts, so a new user with real activity passes naturally.

    Gates 2 (scan throttle) and 4 (Redis lock) live elsewhere:
      - Gate 2 isn't needed because cron fires at most once per day,
        so re-scanning isn't a concern.
      - Gate 4 is checked inside ``dream_for_record`` via the per-user
        Redis lock, not at selection time.

    Returns user_ids ordered by least-recently-dreamed first so a long
    backlog drains evenly across nights.
    """
    now = datetime.utcnow()
    time_threshold = now - timedelta(hours=USER_MIN_HOURS_SINCE_LAST_DREAM)

    db: Session = SessionLocal()
    try:
        from sqlalchemy import or_

        # Gate 1 prefilter — cheap (single index on users).
        users = (
            db.query(User.username, User.last_dreamed_at)
            .filter(
                or_(
                    User.last_dreamed_at.is_(None),
                    User.last_dreamed_at <= time_threshold,
                )
            )
            .filter(User.is_active.is_(True))
            .order_by(User.last_dreamed_at.asc().nullsfirst())
            .limit(limit * 4)   # over-fetch then filter on gate 3
            .all()
        )

        out: list[str] = []
        for username, cursor in users:
            counts = _count_new_activity_since(db, username, cursor)
            # Gate 3 is messages-only now. ``counts["sessions"]`` is still
            # computed for the log line below but no longer affects selection.
            if counts["messages"] >= NEW_MESSAGES_THRESHOLD:
                out.append(username)
                logger.info(
                    "dreaming select: user=%s new_messages=%d new_sessions=%d -> dream",
                    username, counts["messages"], counts["sessions"],
                )
                if len(out) >= limit:
                    break
        return out
    finally:
        db.close()


def _count_new_activity_since(
    db: Session, user_id: str, cursor: datetime | None,
) -> dict[str, int]:
    """Counts of new debrief conversation_messages + conversations for
    ``user_id`` since ``cursor`` (None = all-time). Used by gate 3.

    Only ``session_type == 'debrief'`` counts: dreaming consumes
    exclusively debrief messages (see ``dream_for_record``'s
    ``_load_record_debrief_messages``). A user opening 10 general
    chats without any debrief activity wouldn't produce work for the
    dreamer, so they shouldn't trip the gate either (review found
    this as M2 — was dispatching empty Celery tasks).
    """
    user_pk = resolve_user_pk(db, user_id)
    msg_q = (
        db.query(ConversationMessage)
        .join(Conversation, Conversation.id == ConversationMessage.session_id)
        .filter(
            Conversation.user_id == user_pk,
            Conversation.session_type == "debrief",
        )
    )
    sess_q = db.query(Conversation).filter(
        Conversation.user_id == user_pk,
        Conversation.session_type == "debrief",
    )
    if cursor is not None:
        msg_q = msg_q.filter(ConversationMessage.created_at > cursor)
        sess_q = sess_q.filter(Conversation.created_at > cursor)
    return {"messages": msg_q.count(), "sessions": sess_q.count()}


def select_records_for_user(
    user_id: str, *, limit: int = 50,
) -> list[InterviewRecord]:
    """Return records that should be dreamed for ``user_id``.

    Filters:
      * status='completed' (we don't dream half-analysed records)
      * ``updated_at > last_dreamed_at`` OR ``last_dreamed_at IS NULL``
      * Last chat_message on any debrief session is at least
        ``RECORD_QUIET_HOURS`` old (record is "settled" — covers the
        "exclude currently-chatted record" requirement at 03:30, which
        in practice is always true unless the user is awake at night).
    """
    now = datetime.utcnow()
    quiet_threshold = now - timedelta(hours=RECORD_QUIET_HOURS)

    db: Session = SessionLocal()
    try:
        from sqlalchemy import or_

        q = (
            db.query(InterviewRecord)
            .filter(InterviewRecord.user_id == resolve_user_pk(db, user_id))
            .filter(InterviewRecord.status == "completed")
            .filter(
                or_(
                    InterviewRecord.last_dreamed_at.is_(None),
                    InterviewRecord.updated_at > InterviewRecord.last_dreamed_at,
                )
            )
            .order_by(InterviewRecord.updated_at.asc())
            .limit(limit * 2)
        )
        out: list[InterviewRecord] = []
        for rec in q.all():
            latest_msg_at = _latest_debrief_message_at(db, rec.id)
            if latest_msg_at is None:
                continue   # no debrief chat → nothing to consolidate
            if latest_msg_at > quiet_threshold:
                continue   # still active
            out.append(rec)
            if len(out) >= limit:
                break
        return out
    finally:
        db.close()


def bump_user_last_dreamed_at(
    user_id: str, *, at: datetime | None = None,
) -> None:
    """Move the user's dream cursor. Caller invokes ONCE after finishing
    the per-user dream loop, regardless of whether each individual
    record produced patches — the per-record skip protection lives
    inside ``dream_for_record`` (idempotent re-check).

    ``at`` lets the caller pin the cursor to the moment the scan
    STARTED, not the moment dreaming finished. The dream loop can take
    several minutes per user (slow LLM × N records); without ``at``,
    any chat_message that arrived during the loop has
    ``created_at < bump_time`` and gets silently dropped from the next
    nightly's gate-3 count. Review found this as M1.
    """
    db: Session = SessionLocal()
    try:
        user = db.query(User).filter(User.username == user_id).first()
        if user is None:
            return
        user.last_dreamed_at = at if at is not None else datetime.utcnow()
        db.commit()
    finally:
        db.close()


def _latest_debrief_message_at(db: Session, record_id: str) -> datetime | None:
    """Most recent ConversationMessage timestamp across all debrief sessions of
    this record. Returns None if there are none."""
    row = (
        db.query(ConversationMessage.created_at)
        .join(Conversation, Conversation.id == ConversationMessage.session_id)
        .filter(
            Conversation.interview_id == record_id,
            Conversation.session_type == "debrief",
        )
        .order_by(ConversationMessage.created_at.desc())
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
        # record.user_id is the stable users.id (CLEANUP #2); the memory dispatch
        # + lock key on the username, so bridge pk -> username here.
        user_id = db.query(User.username).filter(User.id == record.user_id).scalar()
        summary["user_id"] = user_id
    finally:
        db.close()

    with user_memory_lock_sync(user_id):
        # Re-check inside the lock. Under Path B's single nightly cron
        # there's no "another worker" in normal operation, but the
        # re-check is defensive against operator-triggered ad-hoc
        # re-runs (and against realtime extraction having bumped
        # something between our pre-lock read and now).
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

            # Snapshot reads share the worker's db so they're consistent with
            # the writes that follow in the same transaction.
            snapshot = _load_snapshot_for_dream(user_id, db=db)
            prompt = DREAMING_PROMPT.format(
                record_id=record_id,
                user_profile=snapshot["user_profile"] or "（空）",
                learning_strategy=snapshot["learning_strategy"] or "（空）",
                ability_index="\n".join(snapshot["ability_index"]) or "（暂无能力状态）",
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
                patches = parse_json_patches(str(response.text))
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "dreaming: LLM call failed record=%s user=%s: %s",
                    record_id, user_id, exc,
                )
                summary["error"] = f"llm_failed: {type(exc).__name__}"
                return summary

            # Dispatch patches. Pass the worker's db so patches + the
            # last_dreamed_at cursor bump commit in a SINGLE transaction.
            # If we used a service-owned session and crashed before the
            # cursor bump, the next scan would re-dream the same record
            # → duplicate LLM call. Atomic commit eliminates that wasted-
            # work window. The exact-line-match patch protocol still
            # bounds the damage if a duplicate dream slips through.
            dispatched = dispatch_memory_patches(
                user_id=user_id,
                patches=patches,
                change_type="patch_dreaming",
                source_interview_record_id=record_id,
                db=db,
            )
            summary["applied"] = dispatched.applied
            summary["dropped"] = dispatched.dropped
            summary["skipped"] = dispatched.skipped

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


def _load_snapshot_for_dream(user_id: str, *, db: Session) -> dict[str, Any]:
    """Read the memory artifacts the dreaming prompt needs, sharing the
    worker's ``db`` so the snapshot is consistent with the writes that
    follow in the same transaction.

    Mirrors ``realtime_extraction._load_snapshot``: the two markdown docs
    plus an ability index built from the active ability states. There is no
    "load full bodies for mentioned topics" step anymore — ability summaries
    ARE the per-topic content the LLM patches against.
    """
    user_profile = memory_document_service.load(user_id, "user_profile", db=db)
    learning_strategy = memory_document_service.load(user_id, "learning_strategy", db=db)
    states = memory_ability_state_service.load_active(user_id, db=db)
    return {
        "user_profile": (user_profile or "").strip(),
        "learning_strategy": (learning_strategy or "").strip(),
        "ability_index": format_ability_index(states),
    }


# ──────────────────────────────────────────────────────────────────────
# Messages
# ──────────────────────────────────────────────────────────────────────


def _load_record_debrief_messages(db: Session, record_id: str) -> list[dict]:
    """Concatenate all ConversationMessage rows under all debrief sessions of
    this record, ordered by time."""
    rows = (
        db.query(ConversationMessage)
        .join(Conversation, Conversation.id == ConversationMessage.session_id)
        .filter(
            Conversation.interview_id == record_id,
            Conversation.session_type == "debrief",
        )
        .order_by(ConversationMessage.created_at.asc(), ConversationMessage.seq.asc())
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


__all__ = [
    "NEW_MESSAGES_THRESHOLD",
    "RECORD_QUIET_HOURS",
    "USER_MIN_HOURS_SINCE_LAST_DREAM",
    "bump_user_last_dreamed_at",
    "dream_for_record",
    "select_dreamable_users",
    "select_records_for_user",
]
