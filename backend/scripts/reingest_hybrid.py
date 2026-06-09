"""Drop + reingest the three Milvus 2.6 hybrid collections from the Postgres
fact sources. Use after deploying the hybrid migration so no stale dense-only
metadata/schema survives.

    python backend/scripts/reingest_hybrid.py --drop                # all 3
    python backend/scripts/reingest_hybrid.py --drop --only resume  # one

Fact sources (Postgres is authoritative — this NEVER reads the old Milvus rows):
  * knowledge → document_chunks            (id=node_id, text, source_kind, document_id)
  * resume    → resume_sections            (id, content, resume_id, section_type, title)
  * ability   → memory_ability_states      (id, search_text|topic+..+summary), archived_at IS NULL

``--drop`` recreates the collection from scratch (clean schema). Safe on an empty
DB: 0 fact rows -> 0 inserts, no error. The embedding model is loaded directly
(no model-catalog dependency).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Make the backend package importable when run as a standalone script.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from llama_index.core import Settings  # noqa: E402

from app.db.database import SessionLocal  # noqa: E402
from app.rag import milvus_hybrid  # noqa: E402
from app.rag.embedding_registry import build_embedding  # noqa: E402


def _drop(coll: milvus_hybrid.HybridCollection) -> None:
    client = milvus_hybrid._get_client()
    if client.has_collection(coll.name):
        client.drop_collection(coll.name)
        milvus_hybrid._ensured.discard(coll.name)
        print(f"  dropped {coll.name}")
    else:
        print(f"  {coll.name} absent (nothing to drop)")


def reingest_knowledge() -> int:
    from app.models.document_chunk import DocumentChunk

    db = SessionLocal()
    try:
        chunks = db.query(DocumentChunk).all()
        rows = []
        for ch in chunks:
            text = (ch.text or "").strip()
            if not text:
                continue
            rows.append({
                "id": str(ch.node_id or ch.id),
                "user_id": int(ch.user_id),
                "source_kind": ch.source_kind or "",
                "document_id": ch.document_id,
                "text": text,
            })
        if not rows:
            return 0
        embs = Settings.embed_model.get_text_embedding_batch(
            [r["text"] for r in rows], show_progress=True,
        )
        for r, e in zip(rows, embs):
            r["dense"] = e
        milvus_hybrid.insert(milvus_hybrid.KNOWLEDGE, rows)
        return len(rows)
    finally:
        db.close()


def reingest_resume() -> int:
    from app.models.resume_section import ResumeSection
    from app.services.resume.resume_vector_service import resume_vector_service

    db = SessionLocal()
    count = 0
    try:
        for sec in db.query(ResumeSection).all():
            if not (sec.content or "").strip():
                continue
            resume_vector_service.upsert_section(sec, db=db)
            count += 1
        db.commit()
        return count
    finally:
        db.close()


def reingest_ability() -> int:
    from app.models.memory_ability_state import MemoryAbilityState
    from app.services.memory import ability_index

    db = SessionLocal()
    count = 0
    try:
        rows = (
            db.query(MemoryAbilityState)
            .filter(MemoryAbilityState.archived_at.is_(None))
            .all()
        )
        for st in rows:
            ability_index.upsert_ability(
                st.id,
                user_id=int(st.user_id),
                search_text=st.search_text or "",
                topic=st.topic or "",
                skill_type=st.skill_type or "",
                mastery_level=st.mastery_level or "",
                summary=st.summary,
            )
            count += 1
        return count
    finally:
        db.close()


_TARGETS = {
    "knowledge": (milvus_hybrid.KNOWLEDGE, reingest_knowledge),
    "resume": (milvus_hybrid.RESUME, reingest_resume),
    "ability": (milvus_hybrid.ABILITY, reingest_ability),
}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--drop", action="store_true", help="drop + recreate the collection(s) first")
    p.add_argument("--only", choices=sorted(_TARGETS), help="reingest just one collection")
    args = p.parse_args()

    targets = [args.only] if args.only else list(_TARGETS)
    print("Loading embedding model...")
    Settings.embed_model = build_embedding()

    for name in targets:
        coll, fn = _TARGETS[name]
        print(f"\n=== {name} ({coll.name}) ===")
        if args.drop:
            _drop(coll)
        n = fn()
        print(f"  reingested {n} row(s) from Postgres")
    print("\nDone.")


if __name__ == "__main__":
    main()
