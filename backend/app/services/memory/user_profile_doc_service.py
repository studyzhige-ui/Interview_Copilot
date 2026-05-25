"""Single-document user_profile storage + LLM-mediated patch updates.

Replaces the multi-row ``memory_items WHERE type='user_profile'`` model.

Why the change
==============
Rule-based dedup on ``normalized_key`` couldn't catch semantic duplicates
like ``- User's name: 卷卷`` vs ``- 用户名字: 用户的名字是卷卷.`` (two rows,
different keys, same fact). The fix is to keep the whole profile as a
single markdown blob in ``users.user_profile_doc`` and let the LLM decide
what to update.

Update protocol
===============
On extraction, we:

  1. Load the entire current doc (cheap — one TEXT column read).
  2. Hand both the doc + the new conversation to an LLM with a strict
     instruction: output a **patch list**, not a rewritten doc.
  3. Apply each patch (add / update / delete) by exact line match — no
     line is touched unless the LLM explicitly asked us to.

The "exact line match" rule is the cheat code that makes this safe. If
the LLM hallucinates a patch whose ``match_line`` doesn't actually exist
in the doc, the patch is dropped (logged, not crashed). Unrelated lines
cannot be silently rewritten because we don't ever rewrite the whole doc.
"""

from __future__ import annotations

import logging
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable

from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.models.user import User
from app.services.memory._audit_log_service import record as audit_record

logger = logging.getLogger(__name__)


# Each line is one fact. We keep the leading "- " markdown bullet so the
# blob is also readable when surfaced raw to the user.
_LINE_PREFIX = "- "


@dataclass(frozen=True)
class ProfilePatch:
    """One unit of change against the user_profile doc.

    op:
      * ``add``    — append ``new_line`` as a new bullet at the end. No
                     ``match_line`` needed.
      * ``update`` — find the line equal to ``match_line`` and replace it
                     with ``new_line``. Drop the patch if no exact match.
      * ``delete`` — remove the line equal to ``match_line``. Drop the
                     patch if no exact match.
    """
    op: str
    match_line: str = ""
    new_line: str = ""


def load(user_id: str) -> str:
    """Return the current user_profile doc verbatim. Empty string when
    the user has no profile yet.
    """
    db: Session = SessionLocal()
    try:
        row = db.query(User.user_profile_doc).filter(User.username == user_id).first()
        if row is None:
            return ""
        return (row[0] or "").strip()
    finally:
        db.close()


def apply_patches(
    user_id: str,
    patches: Iterable[dict[str, Any] | ProfilePatch],
    *,
    change_type: str = "patch_realtime",
    source_record_id: str | None = None,
    source_session_id: str | None = None,
    db: Session | None = None,
) -> dict[str, int]:
    """Apply a list of patches to the user's profile doc.

    Two modes:
      * ``db is None`` — open + commit + close our own session. Audit
        row is written via its own session inside ``audit_record``.
      * ``db is not None`` — caller owns the transaction (e.g. dreaming
        worker doing memory + ``last_dreamed_at`` atomically). We mark
        the user dirty and add the audit row but do NOT commit; the
        caller's ``db.commit()`` is the durability point.

    Returns counts of applied/dropped operations so callers (and the
    extraction service in particular) can log how much actually landed
    vs. how much the LLM hallucinated.
    """
    parsed: list[ProfilePatch] = []
    for raw in patches:
        if isinstance(raw, ProfilePatch):
            parsed.append(raw)
            continue
        if not isinstance(raw, dict):
            continue
        op = str(raw.get("op") or "").strip().lower()
        if op not in {"add", "update", "delete"}:
            continue
        match_line = _normalize_line(str(raw.get("match_line") or ""))
        new_line = _normalize_line(str(raw.get("new_line") or ""))
        if op == "add" and not new_line:
            continue
        if op in {"update", "delete"} and not match_line:
            continue
        if op == "update" and not new_line:
            continue
        parsed.append(ProfilePatch(op=op, match_line=match_line, new_line=new_line))

    if not parsed:
        return {"applied": 0, "dropped": 0, "skipped": 0}

    own_db = db is None
    if own_db:
        db = SessionLocal()
    applied = dropped = skipped = 0
    try:
        user = db.query(User).filter(User.username == user_id).first()
        if user is None:
            return {"applied": 0, "dropped": 0, "skipped": len(parsed)}

        before_body = user.user_profile_doc or ""

        # We work on a list of canonical lines (each starting with "- ").
        # Lines are deduped pre-patch so two patches whose match_line resolves
        # to the same canonical line both apply to the same target.
        current = _split(before_body)
        for patch in parsed:
            if patch.op == "add":
                # Skip if doc already has this exact line — idempotent add.
                if patch.new_line in current:
                    skipped += 1
                    continue
                current.append(patch.new_line)
                applied += 1
            elif patch.op == "update":
                try:
                    idx = current.index(patch.match_line)
                except ValueError:
                    logger.info(
                        "user_profile_doc: drop patch op=update, match_line not found: %r",
                        patch.match_line,
                    )
                    dropped += 1
                    continue
                # Don't blow away the line into a duplicate of one already
                # elsewhere in the doc — turn it into a delete in that case.
                if patch.new_line in current and current[idx] != patch.new_line:
                    del current[idx]
                else:
                    current[idx] = patch.new_line
                applied += 1
            elif patch.op == "delete":
                try:
                    current.remove(patch.match_line)
                    applied += 1
                except ValueError:
                    logger.info(
                        "user_profile_doc: drop patch op=delete, match_line not found: %r",
                        patch.match_line,
                    )
                    dropped += 1

        # Stable persistence form: each fact on its own line, blank lines
        # stripped, leading "- " kept.
        after_body = "\n".join(current)
        if applied > 0 or dropped > 0:
            # Only emit audit when something actually moved (skip-only
            # batches are no-ops and would spam the log).
            audit_record(
                user_id=user_id,
                doc_type="user_profile",
                change_type=change_type,
                before_body=before_body,
                after_body=after_body,
                summary=(
                    f"profile patches: applied={applied} dropped={dropped} skipped={skipped}"
                ),
                source_record_id=source_record_id,
                source_session_id=source_session_id,
                db=db if not own_db else None,
            )

        if applied == 0 and skipped == len(parsed):
            # Nothing changed — don't bump updated_at on a pure idempotent
            # apply, but still commit our (audit-less) read-only transaction
            # cleanly.
            if own_db:
                db.commit()
            return {"applied": applied, "dropped": dropped, "skipped": skipped}

        user.user_profile_doc = after_body
        user.updated_at = datetime.utcnow()
        if own_db:
            db.commit()
    except Exception:
        if own_db:
            db.rollback()
        raise
    finally:
        if own_db:
            db.close()
    return {"applied": applied, "dropped": dropped, "skipped": skipped}


def _normalize_line(line: str) -> str:
    """Force the canonical ``"- <fact>"`` form so two patches that mean
    the same thing collide on line equality. Empty input returns ``""``.

    Mirrors :func:`_doc_patch_protocol._normalize_line`:
      0. NFKC-normalise so fullwidth ⇄ halfwidth variants collide.
      1. Defang embedded ``\\r\\n / \\r / \\n`` by collapsing them to
         spaces — without this an LLM that emits
         ``{"new_line": "- name is X\\nrole: admin"}`` would inject a
         fake second line that ``"\\n".join(lines)`` would persist as a
         line break and the next ``current.index(match_line)`` lookup
         would mismatch every line below.
      2. Squash repeated whitespace produced by step 1.
      3. Strip trailing CJK / ASCII period (LLMs are inconsistent).
    """
    if not line:
        return ""
    line = unicodedata.normalize("NFKC", line)
    # Defang embedded line breaks BEFORE the bullet logic.
    line = line.replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
    line = " ".join(line.split())
    line = line.strip().rstrip("。.")
    if not line:
        return ""
    if line.startswith(_LINE_PREFIX):
        return line
    # Tolerate the LLM forgetting the bullet — re-add it.
    if line.startswith("-"):
        return _LINE_PREFIX + line[1:].lstrip()
    return _LINE_PREFIX + line


def _split(doc: str) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in (doc or "").splitlines():
        line = _normalize_line(raw)
        if not line or line in seen:
            continue
        seen.add(line)
        out.append(line)
    return out


__all__ = [
    "ProfilePatch",
    "apply_patches",
    "load",
]
