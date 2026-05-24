"""Single-shot RAG retrieval facade.

Wraps :func:`app.rag.retriever.query_knowledge_base` so the conversation
engine and the L2 agent's knowledge tool can call retrieval the same
way. After the planner-merge refactor we no longer split by
``source_type`` — the BGE reranker is the authoritative relevance
filter and a pre-rerank metadata split was a heuristic that mostly got
in the way (a user asking about Redis avalanche may benefit from both
interview-question and official-docs chunks).
"""
from dataclasses import dataclass, field
from typing import Any

from app.rag.retriever import query_knowledge_base


@dataclass
class KnowledgeRetrievalResult:
    context_text: str = ""
    chunks: list[dict[str, Any]] = field(default_factory=list)
    sources: list[dict[str, Any]] = field(default_factory=list)
    retrieval_hit: bool = False


class KnowledgeRetriever:
    async def retrieve(
        self,
        *,
        dense_query: str,
        sparse_query: str,
        user_id: str,
        source_type: str | None = None,
    ) -> KnowledgeRetrievalResult:
        """Run one retrieval pass against the user's knowledge corpus.

        ``source_type=None`` (the default) searches every source the
        user has — the reranker decides which chunks survive. Pass an
        explicit ``source_type`` only when a caller has a hard reason
        to scope to one corpus (e.g. an admin tool inspecting just the
        official-docs index).
        """
        query = sparse_query or dense_query
        result = await query_knowledge_base(
            query_str=query,
            source_type=source_type,
            user_id=user_id,
        )
        context_text = result.get("context_text") or result.get("answer") or ""
        chunks: list[dict[str, Any]] = []
        for chunk in result.get("chunks", []):
            if source_type and not chunk.get("source_type"):
                chunk["source_type"] = source_type
            chunks.append(chunk)
        return KnowledgeRetrievalResult(
            context_text=context_text,
            chunks=chunks,
            sources=result.get("sources", []),
            retrieval_hit=(
                "[SYSTEM_EMPTY_WARNING]" not in context_text
                if context_text else False
            ),
        )


knowledge_retriever = KnowledgeRetriever()
