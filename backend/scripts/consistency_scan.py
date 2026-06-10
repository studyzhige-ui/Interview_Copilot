"""Data-consistency scan (CLEANUP).

Read-only diagnostic that surfaces the cross-system drift the new architecture
can accumulate, per the RFC acceptance criterion "巡检脚本能输出可修复的问题清单":

  1. Orphan file assets        — uploaded/consumed ``file_assets`` no business
                                 row references, plus stale ``pending_upload``.
  2. Orphan document chunks    — ``document_chunks`` whose ``document_id`` points
                                 at a deleted ``knowledge_documents`` row, plus a
                                 best-effort node_id-level Postgres<->Milvus check
                                 (missing_in_milvus / stale_in_milvus /
                                 metadata_mismatch / dimension_mismatch).
  3. Subject-less conversations — ``conversations`` with a non-chat ``mode`` but
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

    # node_id-level Postgres <-> Milvus consistency (plan §4.6.3) — replaces the
    # old count-only drift so the two scan semantics don't coexist (INGEST-CLEANUP).
    findings.extend(_milvus_node_consistency(db))
    return findings


def _diff_pg_milvus(
    pg_indexed: dict[str, dict], milvus_rows: dict[str, dict], live_doc_ids: set,
) -> tuple[list[str], list[str], list[str]]:
    """Pure set/field diff (no I/O, so it's fully unit-testable).

    ``pg_indexed`` = the live *indexed* chunks that SHOULD be in Milvus, and
    ``milvus_rows`` = what IS in Milvus, both keyed by node_id with
    ``{document_id, user_id, source_kind}`` values. Returns
    ``(missing_in_milvus, stale_in_milvus, metadata_mismatch)`` node-id lists:
      * missing  — a live indexed chunk has no Milvus row.
      * stale    — a Milvus row whose document_id is no longer a live document.
      * mismatch — a node_id in both whose scope scalars disagree.
    A ``pending`` chunk (in the two-phase window / queued upsert) is not counted
    missing: only ``indexed`` chunks are expected in Milvus; and its Milvus row,
    if any, points at a live document so it isn't stale either.
    """
    pg_ids, mv_ids = set(pg_indexed), set(milvus_rows)
    missing = sorted(pg_ids - mv_ids)
    # A NULL document_id is intentionally stale (an ownerless vector): live
    # KNOWLEDGE rows always carry a document_id, so this only flags genuine junk.
    stale = sorted(mid for mid, r in milvus_rows.items() if r.get("document_id") not in live_doc_ids)
    mismatch = sorted(
        nid for nid in (pg_ids & mv_ids)
        if any(str(pg_indexed[nid].get(k)) != str(milvus_rows[nid].get(k))
               for k in ("document_id", "user_id", "source_kind"))
    )
    return missing, stale, mismatch


def _scan_milvus_rows(client) -> dict[str, dict]:
    """All knowledge Milvus rows keyed by id. Values are the raw pymilvus row
    objects (accessed via ``.get(...)``, so _diff_pg_milvus treats them and the
    plain-dict test fixtures the same). Paginates so a large collection is fully
    covered (not a sampled subset)."""
    from app.core.config import settings

    out: dict[str, dict] = {}
    iterator = client.query_iterator(
        collection_name=settings.MILVUS_COLLECTION,
        batch_size=1000,
        filter="user_id >= 0",  # matches every row (user_id is the int pk scope)
        output_fields=["id", "document_id", "user_id", "source_kind"],
    )
    try:
        while True:
            batch = iterator.next()
            if not batch:
                break
            for r in batch:
                out[str(r.get("id"))] = r
    finally:
        iterator.close()
    return out


def _collection_dim_finding(client) -> Finding:
    """dimension_mismatch: an existing collection's dense dim vs EMBEDDING_DIM."""
    from app.core.config import settings

    desc = client.describe_collection(settings.MILVUS_COLLECTION)
    dim = None
    for f in (desc.get("fields", []) if isinstance(desc, dict) else []):
        if f.get("name") == "dense":
            dim = (f.get("params") or {}).get("dim")
            break
    if dim is not None and int(dim) != settings.EMBEDDING_DIM:
        return Finding(
            "dimension_mismatch", 1,
            note=f"milvus dim={int(dim)} != EMBEDDING_DIM={settings.EMBEDDING_DIM} — rebuild required",
        )
    return Finding("dimension_mismatch", 0, note=f"dim matches EMBEDDING_DIM={settings.EMBEDDING_DIM}")


def _milvus_node_consistency(db: Session) -> list[Finding]:
    """node_id-level Postgres<->Milvus checks: missing_in_milvus / stale_in_milvus
    / metadata_mismatch / dimension_mismatch (plan §4.6.3). Baseline is the live
    *indexed* chunks under live documents — what Milvus should mirror."""
    from app.core.config import settings

    pg_rows = _rows(db, """
        SELECT dc.node_id, dc.document_id, dc.user_id, dc.source_kind
        FROM document_chunks dc
        JOIN knowledge_documents kd ON dc.document_id = kd.id
        WHERE dc.index_status = 'indexed' AND dc.deleted_at IS NULL
          AND kd.deleted_at IS NULL AND dc.node_id IS NOT NULL
    """)
    pg_indexed = {
        str(r[0]): {"document_id": r[1], "user_id": r[2], "source_kind": r[3]} for r in pg_rows
    }
    live_doc_ids = {
        r[0] for r in _rows(db, "SELECT id FROM knowledge_documents WHERE deleted_at IS NULL")
    }

    names = ("missing_in_milvus", "stale_in_milvus", "metadata_mismatch", "dimension_mismatch")
    try:
        from app.rag import milvus_hybrid

        client = milvus_hybrid._get_client()
        if not client.has_collection(settings.MILVUS_COLLECTION):
            return [Finding(n, 0, note="knowledge collection not created yet") for n in names]
        dim_finding = _collection_dim_finding(client)
        milvus_rows = _scan_milvus_rows(client)
    except Exception as exc:  # noqa: BLE001 — Milvus optional for the scan
        return [Finding(n, 0, note=f"skipped (Milvus unreachable: {exc})") for n in names]

    missing, stale, mismatch = _diff_pg_milvus(pg_indexed, milvus_rows, live_doc_ids)
    return [
        Finding("missing_in_milvus", len(missing), missing[:_SAMPLE],
                note="live indexed chunk has no Milvus row"),
        Finding("stale_in_milvus", len(stale), stale[:_SAMPLE],
                note="Milvus row -> non-live document (orphan vector)"),
        Finding("metadata_mismatch", len(mismatch), mismatch[:_SAMPLE],
                note="Milvus scope scalar != Postgres chunk"),
        dim_finding,
    ]


# ── 3. Subject-less conversations ────────────────────────────────────────


def scan_subjectless_conversations(db: Session) -> list[Finding]:
    rows = _rows(db, """
        SELECT id FROM conversations
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
    "conversation_message": "conversation_messages",
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
            # conversation_messages.id is Integer — a non-numeric ref id would
            # error the query (and on Postgres poison the transaction). Skip it
            # as unverifiable rather than sink the whole check.
            if table == "conversation_messages" and not str(rid).lstrip("-").isdigit():
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
