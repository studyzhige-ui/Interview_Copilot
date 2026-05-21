"""Shared single-doc-per-user service factory.

``strategy_doc`` and ``habit_doc`` are structurally identical — one row
per user, two-section markdown body, same patch protocol, same audit
hooks. The only differences are:

  * the SQLAlchemy model class
  * the canonical section names
  * the audit ``doc_type`` label

We factor out the common write/read paths here so a single bug fix or
contract change lands once, not twice.

Why not subclass / inheritance
------------------------------
The model classes already exist. Composition is simpler than building
a generic base class that has to dodge SQLAlchemy's declarative quirks.
Each concrete service (``strategy_doc_service``, ``habit_doc_service``)
holds an instance of ``SingleDocService`` configured with the right
model + sections.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.services.memory._audit_log_service import record as audit_record
from app.services.memory._doc_patch_protocol import PatchResult, apply_patches as patch_body

logger = logging.getLogger(__name__)


_SECTION_HEADER_RE = re.compile(r"^\s*##\s+(.+?)\s*$")


@dataclass(frozen=True)
class SingleDocConfig:
    """Static config for one single-doc-per-user type."""

    model_cls: Any                       # SQLAlchemy declarative model
    doc_type: str                        # for audit log: "strategy" / "habit"
    canonical_sections: tuple[str, ...]  # section names, in display order
    default_fold_section: str            # bucket for unknown sections


class SingleDocService:
    """All write/read paths for a single-doc-per-user type.

    Construct one per concrete type and call its methods.
    """

    def __init__(self, config: SingleDocConfig):
        self.cfg = config

    # ── reads ──────────────────────────────────────────────────────

    def load(self, user_id: str) -> str:
        """Return the doc body (empty string if no row yet)."""
        db: Session = SessionLocal()
        try:
            row = (
                db.query(self.cfg.model_cls)
                .filter(self.cfg.model_cls.user_id == user_id)
                .first()
            )
            return (row.body if row else "") or ""
        finally:
            db.close()

    def load_as_lines(self, user_id: str) -> list[str]:
        """Doc split into non-empty lines, convenient for prompt rendering."""
        body = self.load(user_id)
        return [line for line in (l.rstrip() for l in body.splitlines()) if line]

    # ── writes ─────────────────────────────────────────────────────

    def apply_patches(
        self,
        user_id: str,
        patches: Iterable[dict[str, Any]],
        *,
        change_type: str,
        source_record_id: str | None = None,
        source_session_id: str | None = None,
        db: Session | None = None,
    ) -> PatchResult:
        """Apply patches with audit. Auto-creates the row if missing.

        ``db`` lets the caller share their transaction (e.g. dreaming
        worker doing memory + ``last_dreamed_at`` atomically). When
        ``db`` is None we own a session and commit. When it's passed
        we ``add`` only and leave commit to the caller.

        Refuses to materialise a new row when no patches landed —
        same defence as ``knowledge_doc_service.apply_patches``,
        prevents pollution from LLM hallucination.

        Concurrency: ``user_id`` carries a UNIQUE constraint
        (one strategy/habit doc per user). Two concurrent realtime
        extractions racing on the FIRST write will both observe
        ``row is None``, both try to ``INSERT`` and one will raise
        ``IntegrityError``. We catch it once and retry on a fresh
        session — the row exists now, so the second pass goes through
        the update branch. This is the same defence
        ``knowledge_doc_service.apply_patches`` uses; required because
        ``user_memory_lock`` degrades to no-op on Redis outage.
        """
        own_db = db is None
        if own_db:
            db = SessionLocal()
        try:
            result = self._apply_inner(
                db=db,
                user_id=user_id,
                patches=patches,
                change_type=change_type,
                source_record_id=source_record_id,
                source_session_id=source_session_id,
            )
            if own_db:
                db.commit()
            return result
        except IntegrityError:
            # Another worker created the (user_id) row between our SELECT
            # and INSERT. Rollback + retry once on a fresh session — the
            # row exists now so the second pass falls through the update
            # branch.
            if not own_db:
                # Caller owns the transaction; they decide what to do.
                raise
            db.rollback()
            db.close()
            db = SessionLocal()
            try:
                result = self._apply_inner(
                    db=db,
                    user_id=user_id,
                    patches=patches,
                    change_type=change_type,
                    source_record_id=source_record_id,
                    source_session_id=source_session_id,
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

    def _apply_inner(
        self,
        *,
        db: Session,
        user_id: str,
        patches: Iterable[dict[str, Any]],
        change_type: str,
        source_record_id: str | None,
        source_session_id: str | None,
    ) -> PatchResult:
        row = (
            db.query(self.cfg.model_cls)
            .filter(self.cfg.model_cls.user_id == user_id)
            .first()
        )
        was_new = row is None

        # Refuse to create an empty row when LLM hallucinated all
        # patches (applied == 0). Same guard knowledge_doc has.
        if was_new:
            working = self._canonicalise(self._empty_body())
            result = patch_body(working, patches)
            new_body = self._canonicalise(result.body)
            if result.applied == 0:
                return result
            row = self.cfg.model_cls(user_id=user_id, body=new_body)
            db.add(row)
            db.flush()
            before_body = ""
        else:
            before_body = row.body or ""
            working = self._canonicalise(before_body)
            result = patch_body(working, patches)
            new_body = self._canonicalise(result.body)

            if new_body == before_body:
                if result.applied or result.dropped:
                    logger.info(
                        "%s.apply_patches: net no-op for user=%s "
                        "(applied=%d dropped=%d skipped=%d)",
                        self.cfg.doc_type, user_id,
                        result.applied, result.dropped, result.skipped,
                    )
                return result

            row.body = new_body

        row.updated_at = datetime.utcnow()
        db.add(row)

        audit_record(
            user_id=user_id,
            doc_type=self.cfg.doc_type,
            change_type=change_type,
            before_body=before_body,
            after_body=new_body,
            summary=self._summarise(result, was_new),
            source_record_id=source_record_id,
            source_session_id=source_session_id,
            db=db,
        )
        return result

    def upsert_user_edit(self, user_id: str, new_body: str) -> str:
        """Persist a user-edited body verbatim (subject to canonical
        section normalisation). Returns the final stored body."""
        db: Session = SessionLocal()
        try:
            row = (
                db.query(self.cfg.model_cls)
                .filter(self.cfg.model_cls.user_id == user_id)
                .first()
            )
            was_new = row is None
            if row is None:
                row = self.cfg.model_cls(user_id=user_id)
                db.add(row)

            before_body = row.body or ""
            canon = self._canonicalise(new_body or "")
            row.body = canon
            row.updated_at = datetime.utcnow()

            audit_record(
                user_id=user_id,
                doc_type=self.cfg.doc_type,
                change_type="user_edit",
                before_body=before_body,
                after_body=canon,
                summary=("created via user edit" if was_new else "user edit"),
                db=db,
            )
            db.commit()
            return canon
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    # ── canonical body ─────────────────────────────────────────────

    def _empty_body(self) -> str:
        parts: list[str] = []
        for name in self.cfg.canonical_sections:
            parts.append(f"## {name}")
            parts.append("")
        return "\n".join(parts).rstrip() + "\n"

    def _canonicalise(self, body: str) -> str:
        sections: dict[str, list[str]] = {n: [] for n in self.cfg.canonical_sections}
        current = self.cfg.canonical_sections[0]
        seen_any_header = False

        for line in (body or "").splitlines():
            m = _SECTION_HEADER_RE.match(line)
            if m:
                name = m.group(1).strip()
                seen_any_header = True
                if name in sections:
                    current = name
                else:
                    current = self.cfg.default_fold_section
                    logger.info(
                        "%s: folding unknown section %r into %r",
                        self.cfg.doc_type, name, self.cfg.default_fold_section,
                    )
                continue
            if not seen_any_header and not line.strip():
                continue
            sections[current].append(line)

        parts: list[str] = []
        for name in self.cfg.canonical_sections:
            parts.append(f"## {name}")
            bucket = sections[name]
            while bucket and not bucket[0].strip():
                bucket = bucket[1:]
            while bucket and not bucket[-1].strip():
                bucket = bucket[:-1]
            if bucket:
                parts.append("")
                parts.extend(bucket)
            parts.append("")

        while parts and not parts[-1].strip():
            parts.pop()
        return "\n".join(parts) + "\n"

    @staticmethod
    def _summarise(result: PatchResult, was_new: bool) -> str:
        if was_new:
            return f"created (applied={result.applied}, dropped={result.dropped})"
        return f"applied={result.applied}, dropped={result.dropped}, skipped={result.skipped}"


__all__ = ["SingleDocConfig", "SingleDocService"]
