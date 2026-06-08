"""Data-consistency scan (CLEANUP).

Read-only diagnostic that surfaces the cross-system drift the new architecture
can accumulate, per the RFC acceptance criterion "巡检脚本能输出可修复的问题清单":

  1. Orphan file assets        — uploaded/consumed ``file_assets`` no business
                                 row references, plus stale ``pending_upload``.
  2. Orphan document chunks    — ``document_chunks`` whose ``document_id`` points
                                 at a deleted ``knowledge_documents`` row, and a
                                 best-effort Postgres-vs-Milvus count drift check.
  3. Subject-less conversations — ``chat_sessions`` with a non-chat ``mode`` but
                                 no ``subject_type`` / ``subject_id`` binding.
  4. Dangling memory evidence  — ``memory_ability_states.evidence_refs_json``
                                 pointing at deleted interview QA / records /
                                 conversation messages.

NOTHING is mutated — the script only reports ids so an operator (or a future
repair job) can act. Run from the ``backend/`` directory:
``PYTHONPATH=. python -m scripts.consistency_scan``.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.database import SessionLocal

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
    rows = _rows(db, """
        SELECT fa.id FROM file_assets fa
        WHERE fa.purpose = 'resume'
          AND fa.deleted_at IS NULL
          AND fa.upload_status IN ('uploaded', 'consumed')
          AND NOT EXISTS (SELECT 1 FROM resumes r WHERE r.file_asset_id = fa.id)
    """)
    ids = [r[0] for r in rows]
    findings.append(Finding(
        "orphan_resume_file_assets", len(ids), ids[:_SAMPLE],
        note="resume asset with no referencing resumes row",
    ))

    # Stale pending uploads (presign issued, bytes never confirmed) older than 24h.
    rows = _rows(db, """
        SELECT id FROM file_assets
        WHERE upload_status = 'pending_upload'
          AND deleted_at IS NULL
          AND created_at < (NOW() - INTERVAL '24 hours')
    """)
    ids = [r[0] for r in rows]
    findings.append(Finding(
        "stale_pending_uploads", len(ids), ids[:_SAMPLE],
        note="pending_upload older than 24h — never confirmed",
    ))
    return findings


# ── 2. Orphan document chunks ────────────────────────────────────────────


def scan_orphan_chunks(db: Session) -> list[Finding]:
    findings: list[Finding] = []

    # Knowledge chunks whose parent knowledge_documents row is gone. These are
    # also orphan vectors in Milvus (the chunk is the fact source for the index).
    rows = _rows(db, """
        SELECT dc.id FROM document_chunks dc
        WHERE dc.document_id IS NOT NULL
          AND NOT EXISTS (
            SELECT 1 FROM knowledge_documents kd WHERE kd.id = dc.document_id
          )
    """)
    ids = [r[0] for r in rows]
    findings.append(Finding(
        "orphan_knowledge_chunks", len(ids), ids[:_SAMPLE],
        note="document_chunks.document_id -> deleted knowledge_documents",
    ))

    # Best-effort: Postgres chunk count vs Milvus entity count. A positive drift
    # (Milvus > Postgres) suggests deleted-but-still-indexed vectors.
    findings.append(_milvus_drift(db))
    return findings


def _milvus_drift(db: Session) -> Finding:
    try:
        from pymilvus import Collection, connections, utility

        from app.core.config import settings

        pg_count = _rows(db, "SELECT COUNT(*) FROM document_chunks")[0][0]
        connections.connect(alias="scan", uri=settings.MILVUS_URI)
        try:
            if not utility.has_collection(settings.MILVUS_COLLECTION, using="scan"):
                return Finding("milvus_chunk_drift", 0, note="knowledge collection not created yet")
            col = Collection(settings.MILVUS_COLLECTION, using="scan")
            col.flush()
            milvus_count = col.num_entities
        finally:
            connections.disconnect("scan")
        drift = milvus_count - pg_count
        return Finding(
            "milvus_chunk_drift", max(0, drift),
            note=f"milvus={milvus_count} postgres={pg_count} "
                 f"(positive drift -> likely orphan vectors)",
        )
    except Exception as exc:  # noqa: BLE001 — Milvus optional for the scan
        return Finding("milvus_chunk_drift", 0, note=f"skipped (Milvus unreachable: {exc})")


# ── 3. Subject-less conversations ────────────────────────────────────────


def scan_subjectless_conversations(db: Session) -> list[Finding]:
    rows = _rows(db, """
        SELECT id FROM chat_sessions
        WHERE mode IS NOT NULL AND mode <> 'chat'
          AND (subject_type IS NULL OR subject_id IS NULL)
    """)
    ids = [r[0] for r in rows]
    return [Finding(
        "subjectless_conversations", len(ids), ids[:_SAMPLE],
        note="non-chat mode but no subject_type/subject_id binding",
    )]


# ── 4. Dangling memory evidence ──────────────────────────────────────────

_EVIDENCE_TABLE = {
    "interview_qa": "interview_qa",
    "interview_record": "interview_records",
    "conversation_message": "chat_messages",
    "chat_message": "chat_messages",
}


def scan_dangling_evidence(db: Session) -> list[Finding]:
    rows = _rows(db, """
        SELECT id, evidence_refs_json FROM memory_ability_states
        WHERE evidence_refs_json IS NOT NULL AND archived_at IS NULL
    """)
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
            # chat_messages.id is Integer — a non-numeric ref id would error the
            # query (and on Postgres poison the transaction). Skip it as
            # unverifiable rather than sink the whole check.
            if table == "chat_messages" and not str(rid).lstrip("-").isdigit():
                continue
            key = (table, str(rid))
            if key not in exists_cache:
                hit = _rows(db, f"SELECT 1 FROM {table} WHERE id = :rid LIMIT 1", rid=rid)
                exists_cache[key] = bool(hit)
            if not exists_cache[key]:
                dangling.append(state_id)
                break
    return [Finding(
        "dangling_memory_evidence", len(dangling), dangling[:_SAMPLE],
        note="ability state evidence_refs -> deleted business record",
    )]


# ── Runner ───────────────────────────────────────────────────────────────


def run_scan() -> list[Finding]:
    findings: list[Finding] = []
    with SessionLocal() as db:
        for scan in (
            scan_orphan_file_assets,
            scan_orphan_chunks,
            scan_subjectless_conversations,
            scan_dangling_evidence,
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
