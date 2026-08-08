"""Adversarial cross-tenant probe for the RAG evaluation corpus."""

from __future__ import annotations

from typing import Any

from app.rag.contracts import SearchIntent
from app.rag.retriever import query_knowledge_base

ISOLATION_USER = "eval_user_b"
ISOLATION_DOCUMENT_ID = "kdoc_eval_tenant_isolation_probe"
ISOLATION_MARKER = "ICOP_TENANT_B_CANARY_7F3A9D"
ISOLATION_TEXT = (
    f"Tenant isolation marker: {ISOLATION_MARKER}. "
    "This evidence belongs exclusively to evaluation user B and must never be "
    "returned to evaluation user A."
)
ISOLATION_QUERY = f"What is the tenant isolation marker {ISOLATION_MARKER}?"


async def run_tenant_isolation_probe(
    *,
    owner_user: str = ISOLATION_USER,
    foreign_user: str,
) -> dict[str, Any]:
    intent = SearchIntent.from_query(ISOLATION_QUERY)
    owner = await query_knowledge_base(
        intents=[intent],
        user_id=owner_user,
        min_score=0.0,
    )
    foreign = await query_knowledge_base(
        intents=[intent],
        user_id=foreign_user,
        min_score=0.0,
    )
    owner_ids = {str(chunk.get("document_id") or "") for chunk in owner.chunks}
    foreign_ids = {str(chunk.get("document_id") or "") for chunk in foreign.chunks}
    owner_hit = ISOLATION_DOCUMENT_ID in owner_ids
    foreign_leak = ISOLATION_DOCUMENT_ID in foreign_ids
    if not owner_hit:
        raise RuntimeError(
            "Tenant isolation probe is missing for eval_user_b; prepare the "
            "evaluation corpus before running retrieval benchmarks"
        )
    if foreign_leak:
        raise RuntimeError("Tenant isolation probe leaked across users")
    return {
        "passed": True,
        "owner_hit": owner_hit,
        "foreign_leak": foreign_leak,
        "probe_document_id": ISOLATION_DOCUMENT_ID,
    }


__all__ = [
    "ISOLATION_DOCUMENT_ID",
    "ISOLATION_MARKER",
    "ISOLATION_QUERY",
    "ISOLATION_TEXT",
    "ISOLATION_USER",
    "run_tenant_isolation_probe",
]
