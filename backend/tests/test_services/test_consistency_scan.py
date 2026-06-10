"""C4 / §4.6.3: node_id-level Postgres<->Milvus consistency scan.

The pure diff (_diff_pg_milvus) classifies missing/stale/mismatch deterministically;
_milvus_node_consistency wires the Postgres baseline (live INDEXED chunks under
live docs) to a Milvus row snapshot and degrades to 'skipped' when Milvus is down.
"""
from __future__ import annotations

from types import SimpleNamespace

from app.models.document_chunk import DocumentChunk
from app.models.knowledge import KnowledgeDocument

import scripts.consistency_scan as cs


# ── pure diff (no I/O) ───────────────────────────────────────────────────────


def test_diff_classifies_missing_and_stale():
    pg = {
        "n1": {"document_id": "d1", "user_id": 1, "source_kind": "user_upload"},
        "n2": {"document_id": "d1", "user_id": 1, "source_kind": "user_upload"},
    }
    milvus = {
        "n1": {"document_id": "d1", "user_id": 1, "source_kind": "user_upload"},   # match
        "n3": {"document_id": "ghost", "user_id": 1, "source_kind": "user_upload"},  # stale
    }
    missing, stale, mismatch = cs._diff_pg_milvus(pg, milvus, {"d1"})
    assert missing == ["n2"]   # indexed in PG, absent from Milvus
    assert stale == ["n3"]     # Milvus row -> non-live document
    assert mismatch == []


def test_diff_detects_metadata_mismatch():
    pg = {"n1": {"document_id": "d1", "user_id": 1, "source_kind": "user_upload"}}
    milvus = {"n1": {"document_id": "d1", "user_id": 2, "source_kind": "user_upload"}}
    missing, stale, mismatch = cs._diff_pg_milvus(pg, milvus, {"d1"})
    assert mismatch == ["n1"] and missing == [] and stale == []


def test_diff_clean_when_in_sync():
    pg = {"n1": {"document_id": "d1", "user_id": 1, "source_kind": "user_upload"}}
    milvus = {"n1": {"document_id": "d1", "user_id": 1, "source_kind": "user_upload"}}
    assert cs._diff_pg_milvus(pg, milvus, {"d1"}) == ([], [], [])


# ── orchestration (Milvus mocked) ────────────────────────────────────────────


def _seed_indexed(db, doc_id, node_ids):
    db.add(KnowledgeDocument(
        id=doc_id, user_id=1, title="t", source_kind="user_upload", status="ready",
    ))
    for i, nid in enumerate(node_ids):
        db.add(DocumentChunk(
            document_id=doc_id, node_id=nid, user_id=1, source_kind="user_upload",
            chunk_index=i, text="x", index_status="indexed",
        ))
    db.commit()


def test_node_consistency_reports_missing_and_stale(db_session, monkeypatch):
    _seed_indexed(db_session, "d1", ["n1", "n2"])  # both should be in Milvus

    monkeypatch.setattr("app.rag.milvus_hybrid._get_client",
                        lambda: SimpleNamespace(has_collection=lambda name: True))
    monkeypatch.setattr(cs, "_collection_dim_finding",
                        lambda client: cs.Finding("dimension_mismatch", 0, note="ok"))
    monkeypatch.setattr(cs, "_scan_milvus_rows", lambda client: {
        "n1": {"document_id": "d1", "user_id": 1, "source_kind": "user_upload"},  # ok
        "n_orphan": {"document_id": "ghost", "user_id": 1, "source_kind": "user_upload"},
    })

    f = {x.name: x for x in cs._milvus_node_consistency(db_session)}
    assert f["missing_in_milvus"].count == 1 and "n2" in f["missing_in_milvus"].sample_ids
    assert f["stale_in_milvus"].count == 1 and "n_orphan" in f["stale_in_milvus"].sample_ids
    assert f["metadata_mismatch"].count == 0


def test_node_consistency_skips_when_milvus_unreachable(db_session, monkeypatch):
    _seed_indexed(db_session, "d1", ["n1"])

    def _boom():
        raise RuntimeError("milvus down")
    monkeypatch.setattr("app.rag.milvus_hybrid._get_client", _boom)

    f = {x.name: x for x in cs._milvus_node_consistency(db_session)}
    names = ("missing_in_milvus", "stale_in_milvus", "metadata_mismatch", "dimension_mismatch")
    assert all(f[n].count == 0 and "skipped" in f[n].note for n in names)


def test_node_consistency_excludes_pending_from_missing(db_session, monkeypatch):
    """A 'pending' chunk (two-phase window / queued upsert) is NOT reported
    missing — only 'indexed' chunks are expected in Milvus."""
    db_session.add(KnowledgeDocument(
        id="d1", user_id=1, title="t", source_kind="user_upload", status="processing",
    ))
    db_session.add(DocumentChunk(
        document_id="d1", node_id="np", user_id=1, source_kind="user_upload",
        chunk_index=0, text="x", index_status="pending",
    ))
    db_session.commit()

    monkeypatch.setattr("app.rag.milvus_hybrid._get_client",
                        lambda: SimpleNamespace(has_collection=lambda name: True))
    monkeypatch.setattr(cs, "_collection_dim_finding",
                        lambda client: cs.Finding("dimension_mismatch", 0, note="ok"))
    monkeypatch.setattr(cs, "_scan_milvus_rows", lambda client: {})

    f = {x.name: x for x in cs._milvus_node_consistency(db_session)}
    assert f["missing_in_milvus"].count == 0  # pending np is not expected in Milvus
