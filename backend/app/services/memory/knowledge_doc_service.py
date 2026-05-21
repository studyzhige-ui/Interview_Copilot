"""CRUD + patch application for ``knowledge_docs``.

One service for all per-topic operations:

  * ``load`` / ``load_all`` — read paths
  * ``list_index_lines`` — produce the always-loaded topic index
  * ``apply_patches`` — write path, used by realtime extraction AND
    dreaming. Wraps the generic patch protocol with our schema-aware
    bookkeeping (recompute one_liner / mastery_level / fact_count).
  * ``upsert_user_edit`` — write path for the management UI
  * ``delete_topic`` — drop a topic

Section structure
-----------------
The body always has two ``##`` sections in this order::

    ## 已掌握的认知
    - ...

    ## 学习进展
    - ...

Empty sections are kept so extraction prompts can target them by name
(``add`` patches reference ``section="已掌握的认知"``). The order is
enforced by ``_canonicalise_body``.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from datetime import datetime
from typing import Any, Iterable

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.models.knowledge_doc import KnowledgeDoc
from app.services.memory._audit_log_service import record as audit_record
from app.services.memory._doc_patch_protocol import PatchResult, apply_patches as patch_body

logger = logging.getLogger(__name__)


# ── Section conventions ────────────────────────────────────────────────

SECTION_INSIGHT = "已掌握的认知"
SECTION_PROGRESS = "学习进展"
_CANONICAL_SECTIONS = (SECTION_INSIGHT, SECTION_PROGRESS)

_VALID_MASTERY = {"weak", "progressing", "strong", "unknown"}


def _sanitize_topic(topic: str | None) -> str:
    """Strip forbidden chars + cap length on a topic name.

    Removes brackets/newlines/tabs which would either break the
    ``- [TOPIC] ...`` index line format (making the topic unreachable
    via the context selection regex) or break the canonical body
    when the topic surfaces in audit logs. NFKC-normalised so
    fullwidth/halfwidth variants collide.
    """
    if not topic:
        return ""
    cleaned = unicodedata.normalize("NFKC", topic)
    for ch in _TOPIC_FORBIDDEN_CHARS:
        cleaned = cleaned.replace(ch, "")
    return cleaned.strip()[:_TOPIC_MAX]

# Max length on the one-liner so the index stays cheap to load fully.
_ONE_LINER_MAX = 150
# Max length on a topic name. Mostly to prevent the LLM from inventing
# a 500-char "topic" that's really a sentence.
_TOPIC_MAX = 80

# Characters that break the index line format ``- [TOPIC] ...`` if
# they appear in the topic name. The selection regex pulls the topic
# substring out of ``[...]``, so ``]`` inside the topic would truncate
# the name and make the topic unreachable.
#
# ``/`` ``?`` ``#`` are also stripped because topics travel via URL
# path params (``GET /memory/knowledge/topics/{topic}``) — those would
# either split the path or become URL fragments / query separators,
# making the topic unreachable from the API surface.
_TOPIC_FORBIDDEN_CHARS = "[]\n\r\t/?#"


# ── Read paths ─────────────────────────────────────────────────────────


def load(user_id: str, topic: str) -> KnowledgeDoc | None:
    db: Session = SessionLocal()
    try:
        return (
            db.query(KnowledgeDoc)
            .filter(KnowledgeDoc.user_id == user_id, KnowledgeDoc.topic == topic)
            .first()
        )
    finally:
        db.close()


def load_all(user_id: str) -> list[KnowledgeDoc]:
    """All topics for a user, ordered by last_discussed_at desc then
    created_at desc so the most recently-touched topics come first
    in the index."""
    db: Session = SessionLocal()
    try:
        return (
            db.query(KnowledgeDoc)
            .filter(KnowledgeDoc.user_id == user_id)
            .order_by(
                KnowledgeDoc.last_discussed_at.desc().nullslast(),
                KnowledgeDoc.created_at.desc(),
            )
            .all()
        )
    finally:
        db.close()


def list_index_lines(user_id: str, max_topics: int = 50) -> list[str]:
    """Render the always-loaded topic index for context assembly.

    Format (per line)::

        - [Redis] 中等偏弱 | 8 facts | 上次 2026-03-15 — <one_liner>

    Pushes ``LIMIT max_topics`` into the DB so a user with hundreds of
    topics doesn't read them all just to slice off 50.
    """
    db: Session = SessionLocal()
    try:
        docs = (
            db.query(KnowledgeDoc)
            .filter(KnowledgeDoc.user_id == user_id)
            .order_by(
                KnowledgeDoc.last_discussed_at.desc().nullslast(),
                KnowledgeDoc.created_at.desc(),
            )
            .limit(max_topics)
            .all()
        )
    finally:
        db.close()
    out: list[str] = []
    for d in docs:
        mastery_zh = {
            "weak": "弱",
            "progressing": "进展中",
            "strong": "强",
            "unknown": "?",
        }.get(d.mastery_level or "unknown", "?")
        last = d.last_discussed_at.strftime("%Y-%m-%d") if d.last_discussed_at else "—"
        line = (
            f"- [{d.topic}] {mastery_zh} | {d.fact_count} facts | "
            f"上次 {last} — {d.one_liner or ''}"
        )
        out.append(line)
    return out


# ── Write path: patches ────────────────────────────────────────────────


def apply_patches(
    user_id: str,
    topic: str,
    patches: Iterable[dict[str, Any]],
    *,
    change_type: str,
    source_record_id: str | None = None,
    source_session_id: str | None = None,
    new_one_liner: str | None = None,
    new_mastery_level: str | None = None,
    db: Session | None = None,
) -> PatchResult:
    """Apply patches against the (user, topic) doc, creating it if missing.

    ``change_type`` is one of the audit-log enum values
    (``patch_realtime`` / ``patch_dreaming``). We surface it as a
    required kwarg so the caller has to think about provenance — there
    is no sensible default.

    ``new_one_liner`` and ``new_mastery_level`` are optional override
    values from the extraction LLM. If absent, we re-derive them from
    the body using heuristics (see ``_recompute_index_fields``).

    ``db`` lets the caller participate in their own transaction (e.g.
    the dreaming worker updating ``last_dreamed_at`` + memory patches
    atomically). When ``db`` is passed we DO NOT commit — the caller
    owns commit + rollback semantics. When ``db`` is None we open and
    own a session as before.

    Concurrency: the UniqueConstraint ``(user_id, topic)`` can race
    when two extraction tasks fire simultaneously for the same topic.
    We catch ``IntegrityError`` once and retry as the update path
    (refetch the row another worker just created). This is in addition
    to ``user_memory_lock`` — that lock degrades to no-op on Redis
    outage, so we still need DB-level defence.
    """
    topic = _sanitize_topic(topic)
    if not topic:
        return PatchResult(body="", applied=0, dropped=0, skipped=0)

    own_db = db is None
    if own_db:
        db = SessionLocal()

    try:
        result = _apply_patches_inner(
            db=db,
            user_id=user_id,
            topic=topic,
            patches=patches,
            change_type=change_type,
            source_record_id=source_record_id,
            source_session_id=source_session_id,
            new_one_liner=new_one_liner,
            new_mastery_level=new_mastery_level,
        )
        if own_db:
            db.commit()
        return result
    except IntegrityError:
        # Another worker created the same (user, topic) row between
        # our SELECT and INSERT. Rollback and retry once as the
        # update path — the row now exists, so the second pass will
        # fall through the ``was_new=False`` branch.
        if own_db:
            db.rollback()
        else:
            # Caller owns the transaction; let them decide what to do.
            raise

        db.close()
        db = SessionLocal()
        try:
            result = _apply_patches_inner(
                db=db,
                user_id=user_id,
                topic=topic,
                patches=patches,
                change_type=change_type,
                source_record_id=source_record_id,
                source_session_id=source_session_id,
                new_one_liner=new_one_liner,
                new_mastery_level=new_mastery_level,
            )
            db.commit()
            return result
        except Exception:
            db.rollback()
            raise
    except Exception:
        if own_db:
            db.rollback()
        raise
    finally:
        if own_db and db is not None:
            db.close()


def _apply_patches_inner(
    *,
    db: Session,
    user_id: str,
    topic: str,
    patches: Iterable[dict[str, Any]],
    change_type: str,
    source_record_id: str | None,
    source_session_id: str | None,
    new_one_liner: str | None,
    new_mastery_level: str | None,
) -> PatchResult:
    """The body of ``apply_patches`` minus session management. Caller
    owns commit/rollback and may share the session with other writes.
    """
    doc = (
        db.query(KnowledgeDoc)
        .filter(KnowledgeDoc.user_id == user_id, KnowledgeDoc.topic == topic)
        .first()
    )
    was_new = doc is None

    # ── New row path ───────────────────────────────────────────────
    # Compute the new body BEFORE inserting the row. If no patches
    # apply (LLM hallucinated everything), do not create an empty
    # topic row — that would pollute the index with zero-fact entries
    # the user can see in their UI.
    if was_new:
        working_body = _canonicalise_body(_empty_body())
        result = patch_body(working_body, patches)
        new_body = _canonicalise_body(result.body)

        if result.applied == 0:
            # Nothing landed. Don't materialise the row.
            return result

        doc = KnowledgeDoc(
            user_id=user_id,
            topic=topic,
            body=new_body,
        )
        before_body = ""
    else:
        before_body = doc.body or ""
        working_body = _canonicalise_body(before_body)
        result = patch_body(working_body, patches)
        new_body = _canonicalise_body(result.body)

        if new_body == before_body:
            if result.applied or result.dropped:
                logger.info(
                    "knowledge_doc.apply_patches: net no-op for user=%s topic=%s "
                    "(applied=%d dropped=%d skipped=%d)",
                    user_id, topic, result.applied, result.dropped, result.skipped,
                )
            return result

        doc.body = new_body

    # Re-index. Optional explicit overrides from the LLM take precedence.
    one_liner, mastery, count = _recompute_index_fields(new_body)
    doc.one_liner = (new_one_liner or one_liner)[:_ONE_LINER_MAX]
    doc.mastery_level = new_mastery_level if new_mastery_level in _VALID_MASTERY else mastery
    doc.fact_count = count
    doc.last_discussed_at = datetime.utcnow()
    doc.updated_at = datetime.utcnow()
    db.add(doc)
    if was_new:
        db.flush()  # surface IntegrityError now, not at commit

    audit_record(
        user_id=user_id,
        doc_type="knowledge",
        topic=topic,
        change_type=change_type,
        before_body=before_body,
        after_body=new_body,
        summary=_summarise_patch_result(result, was_new),
        source_record_id=source_record_id,
        source_session_id=source_session_id,
        db=db,
    )
    return result


# ── Write path: user edit / delete ────────────────────────────────────


def upsert_user_edit(
    user_id: str,
    topic: str,
    new_body: str,
    *,
    new_one_liner: str | None = None,
    new_mastery_level: str | None = None,
) -> KnowledgeDoc:
    """Persist a user-edited body directly. Bypasses patches because
    when a human edits in the UI, they want their text honoured verbatim
    (subject to canonical-section normalisation)."""
    topic = _sanitize_topic(topic)
    if not topic:
        raise ValueError("topic is required")

    db: Session = SessionLocal()
    try:
        doc = (
            db.query(KnowledgeDoc)
            .filter(KnowledgeDoc.user_id == user_id, KnowledgeDoc.topic == topic)
            .first()
        )
        was_new = doc is None
        if doc is None:
            doc = KnowledgeDoc(user_id=user_id, topic=topic)
            db.add(doc)

        before_body = doc.body or ""
        canon_body = _canonicalise_body(new_body or "")
        doc.body = canon_body
        one_liner, mastery, count = _recompute_index_fields(canon_body)
        doc.one_liner = (new_one_liner or one_liner)[:_ONE_LINER_MAX]
        doc.mastery_level = new_mastery_level if new_mastery_level in _VALID_MASTERY else mastery
        doc.fact_count = count
        doc.updated_at = datetime.utcnow()

        audit_record(
            user_id=user_id,
            doc_type="knowledge",
            topic=topic,
            change_type="user_edit",
            before_body=before_body,
            after_body=canon_body,
            summary=("created via user edit" if was_new else "user edit"),
            db=db,
        )
        db.commit()
        db.refresh(doc)
        return doc
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def delete_topic(user_id: str, topic: str) -> bool:
    """Drop a topic entirely. Returns True iff a row was deleted."""
    db: Session = SessionLocal()
    try:
        doc = (
            db.query(KnowledgeDoc)
            .filter(KnowledgeDoc.user_id == user_id, KnowledgeDoc.topic == topic)
            .first()
        )
        if doc is None:
            return False
        before_body = doc.body or ""
        # Order matters cosmetically: delete first, then audit, then commit.
        # All three land in the same transaction so on rollback the audit
        # row also vanishes — but logically the audit reads "topic was
        # deleted" only after the delete is staged.
        db.delete(doc)
        audit_record(
            user_id=user_id,
            doc_type="knowledge",
            topic=topic,
            change_type="user_delete",
            before_body=before_body,
            after_body="",
            summary=f"topic deleted ({len(before_body.splitlines())} lines)",
            db=db,
        )
        db.commit()
        return True
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# ── Canonical body helpers ─────────────────────────────────────────────


def _empty_body() -> str:
    return (
        f"## {SECTION_INSIGHT}\n"
        f"\n"
        f"## {SECTION_PROGRESS}\n"
    )


_SECTION_HEADER_RE = re.compile(r"^\s*##\s+(.+?)\s*$")


def _canonicalise_body(body: str) -> str:
    """Force the two canonical sections to exist and be in canonical
    order. Content inside each section is preserved verbatim. Unknown
    ``##`` sections (likely LLM hallucination) get folded into the
    nearest canonical one — by default into ``已掌握的认知``."""
    lines = (body or "").splitlines()
    # Map section_name -> list of body lines (excluding the header itself).
    sections: dict[str, list[str]] = {name: [] for name in _CANONICAL_SECTIONS}
    current: str = SECTION_INSIGHT  # default bucket if body starts without a header
    seen_any_header = False

    for line in lines:
        m = _SECTION_HEADER_RE.match(line)
        if m:
            name = m.group(1).strip()
            seen_any_header = True
            if name in _CANONICAL_SECTIONS:
                current = name
            else:
                # Unknown section — fold into 学习进展 (the lower-stakes
                # bucket). Putting renegade content into 已掌握的认知
                # would silently promote unverified material to
                # "claims of understanding"; putting it in 学习进展
                # only mis-attributes activity reports — recoverable
                # by the next extraction pass.
                current = SECTION_PROGRESS
                logger.info(
                    "knowledge_doc: folding unknown section %r into %r",
                    name, SECTION_PROGRESS,
                )
            continue
        if not seen_any_header and not line.strip():
            continue  # skip leading blanks
        sections[current].append(line)

    parts: list[str] = []
    for name in _CANONICAL_SECTIONS:
        parts.append(f"## {name}")
        # Trim each section's leading/trailing blanks but keep internal ones.
        bucket = sections[name]
        # strip leading blanks
        while bucket and not bucket[0].strip():
            bucket = bucket[1:]
        # strip trailing blanks
        while bucket and not bucket[-1].strip():
            bucket = bucket[:-1]
        if bucket:
            parts.append("")
            parts.extend(bucket)
        parts.append("")  # blank between sections

    # Drop trailing blank.
    while parts and not parts[-1].strip():
        parts.pop()
    return "\n".join(parts) + "\n"


_BULLET_RE = re.compile(r"^\s*-\s+")


def _recompute_index_fields(body: str) -> tuple[str, str, int]:
    """Heuristic index recompute when the LLM didn't provide explicit
    values. Returns (one_liner, mastery_level, fact_count).

    one_liner: first non-empty bullet in 已掌握的认知, truncated.
    mastery_level: "unknown" — we don't try to infer mastery from body
                   text without an LLM. The LLM should pass mastery
                   explicitly when it has signal; otherwise we leave
                   whatever was there.
    fact_count: total bullet lines across both sections.
    """
    insight_bullets: list[str] = []
    progress_bullets: list[str] = []

    current_bucket: list[str] | None = None
    for line in (body or "").splitlines():
        m = _SECTION_HEADER_RE.match(line)
        if m:
            name = m.group(1).strip()
            if name == SECTION_INSIGHT:
                current_bucket = insight_bullets
            elif name == SECTION_PROGRESS:
                current_bucket = progress_bullets
            else:
                current_bucket = None
            continue
        if _BULLET_RE.match(line) and current_bucket is not None:
            # Strip exactly one leading "- " (or "-") not all leading
            # dashes — a bullet like "- --x" should preserve "--x".
            stripped = line.lstrip()
            if stripped.startswith("- "):
                bullet_text = stripped[2:].strip()
            elif stripped.startswith("-"):
                bullet_text = stripped[1:].strip()
            else:
                bullet_text = stripped.strip()
            current_bucket.append(bullet_text)

    first = insight_bullets[0] if insight_bullets else (progress_bullets[0] if progress_bullets else "")
    one_liner = first[:_ONE_LINER_MAX]
    fact_count = len(insight_bullets) + len(progress_bullets)
    # Mastery: don't guess from text. Caller should pass explicit value
    # when extracted; otherwise keep "unknown" as a deliberate signal.
    mastery = "unknown"
    return one_liner, mastery, fact_count


def _summarise_patch_result(result: PatchResult, was_new: bool) -> str:
    if was_new:
        return f"created (applied={result.applied}, dropped={result.dropped})"
    return f"applied={result.applied}, dropped={result.dropped}, skipped={result.skipped}"


__all__ = [
    "SECTION_INSIGHT",
    "SECTION_PROGRESS",
    "apply_patches",
    "delete_topic",
    "list_index_lines",
    "load",
    "load_all",
    "upsert_user_edit",
]
