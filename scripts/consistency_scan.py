"""Data-consistency scan (CLEANUP).

Read-only diagnostic that surfaces the cross-system drift the new architecture
can accumulate, per the RFC acceptance criterion "巡检脚本能输出可修复的问题清单":

  1. Orphan file assets        — uploaded/consumed ``file_assets`` no business
                                 row references, plus stale ``pending_upload``.
  2. Orphan document chunks    — ``document_chunks`` whose ``document_id`` points
                                 at a deleted ``knowledge_documents`` row, plus a
                                 best-effort node_id-level Postgres facts/projection check
                                 (missing_in_index / stale_in_index /
                                 metadata_mismatch / dimension_mismatch).
  3. Subject-less conversations — ``conversations`` with a non-chat ``mode`` but
                                 no ``subject_type`` / ``subject_id`` binding.
  4. Legacy migration sources — ``memory_ability_states.evidence_refs_json``
                                 pointing at deleted interview QA / records /
                                 conversation messages; used only to decide
                                 which rows are safe to migrate in Stage 2.

NOTHING is mutated — the script only reports ids so an operator (or a future
repair job) can act. Run from the project root:
``python scripts/consistency_scan.py``.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Make the ``app`` package importable. Two layouts: repo (<root>/backend/app,
# script at <root>/scripts/) and docker image (/app/app, script at /app/scripts/).
_parent = Path(__file__).resolve().parents[1]
sys.path.insert(
    0, str(_parent / "backend" if (_parent / "backend" / "app").is_dir() else _parent)
)

from sqlalchemy import text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.db.database import SessionLocal  # noqa: E402

_SAMPLE = 20  # ids to show per finding


@dataclass
class Finding:
    name: str
    count: int
    sample_ids: list = field(default_factory=list)
    note: str = ""


def _rows(db: Session, sql: str, **params) -> list:
    return list(db.execute(text(sql), params))


# ── 1. Orphan file assets ────────────────────────────────────────────────


def scan_orphan_file_assets(db: Session) -> list[Finding]:
    findings: list[Finding] = []

    # A consumed/uploaded resume asset that no resume row points at. (resume is
    # the only purpose wired to file_assets today; other purposes are reported
    # as "no consumer yet" below rather than as orphans.)
    rows = _rows(
        db,
        """
        SELECT fa.id FROM file_assets fa
        WHERE fa.purpose = 'resume'
          AND fa.deleted_at IS NULL
          AND fa.upload_status IN ('uploaded', 'consumed')
          AND NOT EXISTS (SELECT 1 FROM resumes r WHERE r.file_asset_id = fa.id)
    """,
    )
    ids = [r[0] for r in rows]
    findings.append(
        Finding(
            "orphan_resume_file_assets",
            len(ids),
            ids[:_SAMPLE],
            note="resume asset with no referencing resumes row",
        )
    )

    # Stale pending uploads (presign issued, bytes never confirmed) older than 24h.
    rows = _rows(
        db,
        """
        SELECT id FROM file_assets
        WHERE upload_status = 'pending_upload'
          AND deleted_at IS NULL
          AND created_at < (NOW() - INTERVAL '24 hours')
    """,
    )
    ids = [r[0] for r in rows]
    findings.append(
        Finding(
            "stale_pending_uploads",
            len(ids),
            ids[:_SAMPLE],
            note="pending_upload older than 24h — never confirmed",
        )
    )
    return findings


# ── 2. Orphan document chunks ────────────────────────────────────────────


def scan_orphan_chunks(db: Session) -> list[Finding]:
    findings: list[Finding] = []

    # Knowledge chunks whose parent knowledge_documents row is gone. These are
    # also orphan retrieval entries (the chunk is the fact source for the index).
    rows = _rows(
        db,
        """
        SELECT dc.id FROM document_chunks dc
        WHERE dc.document_id IS NOT NULL
          AND NOT EXISTS (
            SELECT 1 FROM knowledge_documents kd WHERE kd.id = dc.document_id
          )
    """,
    )
    ids = [r[0] for r in rows]
    findings.append(
        Finding(
            "orphan_knowledge_chunks",
            len(ids),
            ids[:_SAMPLE],
            note="document_chunks.document_id -> deleted knowledge_documents",
        )
    )

    # node_id-level Postgres facts/projection consistency (plan §4.6.3) — replaces the
    # old count-only drift so the two scan semantics don't coexist (INGEST-CLEANUP).
    findings.extend(_retrieval_node_consistency(db))
    return findings


def _retrieval_node_consistency(db: Session) -> list[Finding]:
    """Read-only bounded-result checks over canonical facts and projection.

    Counts happen in SQL; only sample IDs cross the process boundary. Other
    generations are retained deliberately, not labelled orphan merely because
    a model configuration changed. Unavailable storage raises a diagnostic
    failure rather than pretending the unexecuted check found zero issues.
    """
    from sqlalchemy import select, func, or_, and_
    from app.models.document_chunk import DocumentChunk as C
    from app.models.knowledge import KnowledgeDocument as D
    from app.models.file_asset import FileAsset as A
    from app.models.retrieval_index import RetrievalEntry as E
    from app.rag.index.identity import current_index_identity
    from app.rag.hybrid_index import _limits

    if db.bind.dialect.name == "postgresql":
        _limits(db)
    fp = current_index_identity().fingerprint

    def finding(name, statement, note):
        sub = statement.subquery()
        count = db.scalar(select(func.count()).select_from(sub)) or 0
        sample = list(db.scalars(select(sub.c[0]).order_by(sub.c[0]).limit(_SAMPLE)))
        return Finding(name, count, sample, note)

    missing = (
        select(C.node_id)
        .join(D, D.id == C.document_id)
        .where(
            C.index_status == "indexed",
            C.deleted_at.is_(None),
            D.deleted_at.is_(None),
            D.status == "ready",
            D.index_fingerprint == fp,
            D.source_kind != "chat_attachment",
            D.conversation_id.is_(None),
            ~select(E.chunk_id).where(E.chunk_id == C.id, E.generation == fp).exists(),
        )
    )
    stale = (
        select(E.node_id)
        .outerjoin(C, C.id == E.chunk_id)
        .outerjoin(D, D.id == E.document_id)
        .where(
            E.generation == fp,
            or_(
                C.id.is_(None),
                D.id.is_(None),
                C.deleted_at.is_not(None),
                D.deleted_at.is_not(None),
                C.index_status != "indexed",
                D.status.in_(["deleted", "deleting", "stale"]),
                D.source_kind == "chat_attachment",
                D.conversation_id.is_not(None),
            ),
        )
    )
    mismatch = (
        select(E.node_id)
        .join(C, C.id == E.chunk_id)
        .join(D, D.id == E.document_id)
        .outerjoin(A, A.id == D.file_asset_id)
        .where(
            E.generation == fp,
            or_(
                E.user_id != C.user_id,
                E.user_id != D.user_id,
                E.node_id != C.node_id,
                E.document_id != C.document_id,
                E.source_kind != C.source_kind,
                E.source_kind != D.source_kind,
                E.source_hash != C.text_hash,
                C.text_hash.is_(None),
                and_(
                    D.file_asset_id.is_not(None),
                    or_(A.id.is_(None), A.user_id != D.user_id),
                ),
            ),
        )
    )
    generation = select(D.id).where(
        D.status == "ready",
        D.deleted_at.is_(None),
        D.source_kind != "chat_attachment",
        D.conversation_id.is_(None),
        or_(D.index_fingerprint.is_(None), D.index_fingerprint != fp),
    )
    return [
        finding(
            "missing_in_index",
            missing,
            "published canonical chunk missing current projection",
        ),
        finding("stale_in_index", stale, "projection no longer eligible for retrieval"),
        finding(
            "metadata_mismatch",
            mismatch,
            "projection/canonical ownership, source or hash mismatch",
        ),
        finding(
            "index_generation",
            generation,
            f"active fingerprint={fp}; rebuild from canonical facts",
        ),
    ]


# ── 3. Subject-less conversations ────────────────────────────────────────


def scan_subjectless_conversations(db: Session) -> list[Finding]:
    rows = _rows(
        db,
        """
        SELECT id FROM conversations
        WHERE mode IS NOT NULL AND mode <> 'chat'
          AND (subject_type IS NULL OR subject_id IS NULL)
    """,
    )
    ids = [r[0] for r in rows]
    return [
        Finding(
            "subjectless_conversations",
            len(ids),
            ids[:_SAMPLE],
            note="non-chat mode but no subject_type/subject_id binding",
        )
    ]


# ── 4. Dangling legacy migration sources ─────────────────────────────────

_EVIDENCE_TABLE = {
    "interview_qa": "interview_qa",
    "interview_record": "interview_records",
    "conversation_message": "conversation_messages",
}


def scan_legacy_migration_sources(db: Session) -> list[Finding]:
    rows = _rows(
        db,
        """
        SELECT id, evidence_refs_json FROM memory_ability_states
        WHERE evidence_refs_json IS NOT NULL AND archived_at IS NULL
    """,
    )
    dangling: list[str] = []
    # Cache existence checks so a big scan doesn't re-query per ref.
    exists_cache: dict[tuple, bool] = {}
    for state_id, raw in rows:
        try:
            refs = json.loads(raw) or []
        except (json.JSONDecodeError, TypeError):
            continue
        for ref in refs if isinstance(refs, list) else []:
            if not isinstance(ref, dict):
                continue
            table = _EVIDENCE_TABLE.get(str(ref.get("type") or ""))
            rid = ref.get("id")
            if not table or rid is None:
                continue
            # conversation_messages.id is Integer — a non-numeric ref id would
            # error the query (and on Postgres poison the transaction). Skip it
            # as unverifiable rather than sink the whole check.
            if table == "conversation_messages" and not str(rid).lstrip("-").isdigit():
                continue
            key = (table, str(rid))
            if key not in exists_cache:
                hit = _rows(
                    db, f"SELECT 1 FROM {table} WHERE id = :rid LIMIT 1", rid=rid
                )
                exists_cache[key] = bool(hit)
            if not exists_cache[key]:
                dangling.append(state_id)
                break
    return [
        Finding(
            "dangling_legacy_ability_sources",
            len(dangling),
            dangling[:_SAMPLE],
            note="legacy ability row references a deleted business record",
        )
    ]


# ── Runner ───────────────────────────────────────────────────────────────


def run_scan() -> list[Finding]:
    findings: list[Finding] = []
    with SessionLocal() as db:
        for scan in (
            scan_orphan_file_assets,
            scan_orphan_chunks,
            scan_subjectless_conversations,
            scan_legacy_migration_sources,
        ):
            try:
                findings.extend(scan(db))
            except Exception as exc:  # noqa: BLE001 — one check failing shouldn't abort the rest
                findings.append(Finding(scan.__name__, -1, note=f"scan error: {exc}"))
    return findings


def main() -> int:
    findings = run_scan()
    total = sum(f.count for f in findings if f.count > 0)
    print("=== consistency scan ===")
    for f in findings:
        flag = "OK " if f.count == 0 else ("ERR" if f.count < 0 else "!! ")
        print(f"[{flag}] {f.name}: {f.count}  - {f.note}")
        if f.sample_ids:
            print(f"        sample: {f.sample_ids}")
    print(f"=== {total} issue(s) flagged ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
