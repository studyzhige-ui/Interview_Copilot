"""Memory ability-state index — Milvus 2.6 native dense + server-side BM25
hybrid via the shared ``app.rag.milvus_hybrid`` abstraction.

Postgres ``memory_ability_states`` is the fact source; Milvus holds an
index-only copy (one row per ability state) scoped by the stable ``users.id``
pk. Maintained asynchronously via outbox jobs (``upsert_memory_ability_index`` /
``delete_memory_ability_index``) so a Milvus outage delays the index, never
blocks a memory write. Write helpers raise on failure (the outbox retries); the
read helper degrades to an empty list (never breaks a turn) and never issues an
unscoped query. No LlamaIndex vector store — search text is embedded directly
and BM25 is computed server-side by Milvus.
"""
from __future__ import annotations

import logging
from typing import Any

from llama_index.core import Settings

from app.core.config import settings
from app.rag import milvus_hybrid

logger = logging.getLogger(__name__)

_COLL = milvus_hybrid.ABILITY


def _index_text(
    *, search_text: str, topic: str, skill_type: str, mastery_level: str, summary: str | None,
) -> str:
    """Text indexed for BM25 + dense. Prefer the prebuilt ``search_text``;
    otherwise compose from the structured fields."""
    if (search_text or "").strip():
        return search_text.strip()
    parts = [topic, skill_type, mastery_level, summary]
    return "\n".join(str(p).strip() for p in parts if p and str(p).strip())


def upsert_ability(
    state_id: str,
    *,
    user_id: int,
    search_text: str,
    topic: str,
    skill_type: str,
    mastery_level: str,
    summary: str | None = None,
) -> None:
    """Index (or re-index) one ability state — delete-then-insert by ``state_id``.
    ``user_id`` is the stable users.id pk. Raises on failure so the outbox retries."""
    text = _index_text(
        search_text=search_text, topic=topic, skill_type=skill_type,
        mastery_level=mastery_level, summary=summary,
    )
    if not text:
        return
    milvus_hybrid.delete_by_field(_COLL, "id", state_id)
    milvus_hybrid.insert(_COLL, [{
        "id": state_id,
        "user_id": int(user_id),
        "topic": topic or "",
        "skill_type": skill_type or "",
        "mastery_level": mastery_level or "",
        "summary": summary or "",
        "text": text,
        "dense": Settings.embed_model.get_text_embedding(text),
    }])


def delete_ability(state_id: str) -> None:
    """Drop one ability state's index copy. Raises on failure (outbox retries)."""
    milvus_hybrid.delete_by_field(_COLL, "id", state_id)


def search_abilities(user_id: str, query: str, top_k: int | None = None) -> list[dict[str, Any]]:
    """Return the user's most topic-relevant ability states for ``query``.

    ``user_id`` is the username principal; it's resolved to the stable users.id
    pk (the Milvus scope key) before filtering. Read path — degrades to ``[]`` on
    any error (resolve / Milvus) so a turn never breaks, and never issues an
    unscoped query.
    """
    if not (query or "").strip():
        return []
    top_k = top_k or settings.MEMORY_ABILITY_TOP_K
    try:
        from app.core.user_identity import resolve_user_pk
        from app.db.database import SessionLocal

        with SessionLocal() as db:
            user_pk = resolve_user_pk(db, user_id)
        if user_pk is None:
            return []
        query_dense = Settings.embed_model.get_query_embedding(query)
        hits = milvus_hybrid.hybrid_search(
            _COLL, query_text=query, query_dense=query_dense, user_pk=user_pk, top_k=top_k,
        )
        out: list[dict[str, Any]] = []
        for h in hits:
            if h.get("user_id") != user_pk:  # defence-in-depth on the tenant filter
                continue
            out.append({
                "topic": h.get("topic", ""),
                "skill_type": h.get("skill_type", ""),
                "mastery_level": h.get("mastery_level", ""),
                "summary": h.get("summary", ""),
                "score": float(h.get("score", 0.0) or 0.0),
            })
        return out
    except Exception as exc:  # noqa: BLE001 — degrade safely, never break a turn
        logger.warning("ability search failed for %s: %s", user_id, exc)
        return []


__all__ = ["upsert_ability", "delete_ability", "search_abilities"]
