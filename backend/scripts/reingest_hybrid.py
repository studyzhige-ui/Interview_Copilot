"""Drop + reingest the three Milvus 2.6 hybrid collections from the Postgres
fact sources. Use after deploying the hybrid migration so no stale dense-only
metadata/schema survives.

    python backend/scripts/reingest_hybrid.py --drop                # all 3
    python backend/scripts/reingest_hybrid.py --drop --only resume  # one
    python backend/scripts/reingest_hybrid.py --document <id>       # one knowledge doc
    python backend/scripts/reingest_hybrid.py --user <id>           # a user's docs
    python backend/scripts/reingest_hybrid.py --user <id> --category <name>

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


def reingest_knowledge(
    *, document_ids: list[str] | None = None, user_id: int | None = None,
    category: str | None = None,
) -> int:
    """Rebuild knowledge Milvus rows from the Postgres facts, at the requested
    granularity (plan §4.6.3): a single ``document_ids`` set, all of a
    ``user_id``'s documents (optionally a ``category`` within it), or — when no
    filter is given — every live document (disaster recovery).

    All granularities funnel through ``ingestion.reindex_document`` (one rebuild-
    from-facts path, not a second one): it reads each document's LIVE chunks
    (soft-deleted excluded — so a deleted document is never re-indexed),
    re-embeds with dim/count validation, replaces that document's rows, and flips
    its chunks to ``indexed``. Targets are resolved from ``knowledge_documents``
    (``deleted_at IS NULL``); ``category`` is read from there, not from Milvus.
    A document is the unit, so the defensive document-less (NULL) chunk path is
    intentionally out of scope here.

    Embedding is per-document (not one whole-collection batch) so this can reuse
    the single rebuild path; the throughput trade-off is fine for a low-frequency
    ops / disaster-recovery tool. Progress is printed per document.
    """
    from app.models.knowledge import KnowledgeDocument
    from app.rag.ingestion import reindex_document

    db = SessionLocal()
    try:
        if document_ids is None:
            q = db.query(KnowledgeDocument.id).filter(KnowledgeDocument.deleted_at.is_(None))
            if user_id is not None:
                q = q.filter(KnowledgeDocument.user_id == user_id)
            if category is not None:
                q = q.filter(KnowledgeDocument.category == category)
            document_ids = [r[0] for r in q.all()]
        total = 0
        for i, doc_id in enumerate(document_ids, 1):
            n = reindex_document(db, doc_id)
            total += n
            print(f"    [{i}/{len(document_ids)}] {doc_id}: {n} chunk(s)")
        return total
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
    # Knowledge-only subset reingest (plan §4.6.3 document/user/category dims).
    p.add_argument("--document", help="reingest one knowledge document by id")
    p.add_argument("--user", type=int, help="reingest all of a user's live knowledge documents")
    p.add_argument("--category", help="with --user, restrict to this knowledge category")
    args = p.parse_args()

    # --category only filters within a --user scope; reject it alone so an
    # operator never silently triggers a full reingest when they meant a subset.
    if args.category and args.user is None:
        p.error("--category requires --user")

    # Subset reingest targets only the knowledge collection from Postgres facts;
    # it never drops a collection (that's the full disaster-recovery path).
    if args.document or args.user is not None:
        print("Loading embedding model...")
        Settings.embed_model = build_embedding()
        if args.document:
            n = reingest_knowledge(document_ids=[args.document])
            print(f"reingested document {args.document}: {n} chunk(s)")
        else:
            n = reingest_knowledge(user_id=args.user, category=args.category)
            scope = f"user {args.user}" + (f" / category {args.category}" if args.category else "")
            print(f"reingested {scope}: {n} chunk(s)")
        print("\nDone.")
        return

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
