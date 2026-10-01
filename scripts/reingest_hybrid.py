"""Plan or execute a bounded canonical-fact pgvector rebuild.

Default is READ ONLY: no model load, no provider call, no index deletion.
Use --execute after reviewing the plan, --after to continue its stable cursor.
Old external vector stores are never read or deleted. Historical source facts,
user data and old semantic generations are preserved.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_root = Path(__file__).resolve().parents[1]
sys.path.insert(
    0, str(_root / "backend" if (_root / "backend/app").is_dir() else _root)
)

from sqlalchemy import select  # noqa: E402
from app.db.database import SessionLocal  # noqa: E402
from app.models.knowledge import KnowledgeDocument  # noqa: E402
from app.rag.index.identity import current_index_identity  # noqa: E402


def reingest_knowledge(
    *,
    user_id: int | None = None,
    category: str | None = None,
    document_ids: list[str] | None = None,
    limit: int = 100,
    after: str | None = None,
    execute: bool = False,
) -> dict:
    if type(limit) is not int or not 1 <= limit <= 1000:
        raise ValueError("limit must be 1..1000")
    if user_id is not None and (type(user_id) is not int or user_id <= 0):
        raise ValueError("user must be a positive canonical ID")
    if category and user_id is None:
        raise ValueError("category requires a user scope")
    if document_ids is not None and (not document_ids or len(document_ids) > 1000):
        raise ValueError("explicit document scope must be nonempty and bounded")
    d = KnowledgeDocument
    stmt = select(d.id, d.user_id).where(
        d.deleted_at.is_(None),
        d.status.in_(["ready", "processing", "failed"]),
        d.source_kind != "chat_attachment",
        d.conversation_id.is_(None),
    )
    if user_id is not None:
        stmt = stmt.where(d.user_id == user_id)
    if category is not None:
        stmt = stmt.where(d.category == category)
    if document_ids is not None:
        stmt = stmt.where(d.id.in_(document_ids))
    if after is not None:
        stmt = stmt.where(d.id > after)
    with SessionLocal() as db:
        selected = list(db.execute(stmt.order_by(d.id).limit(limit + 1)))
    more = len(selected) > limit
    selected = selected[:limit]
    report = {
        "mode": "execute" if execute else "plan",
        "index_fingerprint": current_index_identity().fingerprint,
        "documents": [{"id": item.id, "owner": item.user_id} for item in selected],
        "has_more": more,
        "next_cursor": selected[-1].id if selected and more else None,
        "indexed_chunks": 0,
        "completed_documents": [],
    }
    if not execute or not selected:
        return report
    from llama_index.core import Settings
    from app.rag.embedding_registry import build_embedding
    from app.rag import hybrid_index
    from app.rag.index.knowledge import reindex_document

    hybrid_index.validate_index_storage()
    Settings.embed_model = build_embedding()
    for document in selected:
        # Per-document preparation rechecks ownership, version and liveness.
        # Failure is propagated, never reported as a successful empty corpus.
        report["indexed_chunks"] += reindex_document(document.id)
        report["completed_documents"].append(document.id)
    return report


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user", type=int)
    parser.add_argument("--category")
    parser.add_argument("--document", action="append", dest="documents")
    parser.add_argument("--after")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="explicitly authorize model work and projection writes",
    )
    args = parser.parse_args(argv)
    print(
        json.dumps(
            reingest_knowledge(
                user_id=args.user,
                category=args.category,
                document_ids=args.documents,
                after=args.after,
                limit=args.limit,
                execute=args.execute,
            ),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
