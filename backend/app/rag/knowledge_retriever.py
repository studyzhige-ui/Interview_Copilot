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
        source_types: list[str],
        user_id: str,
    ) -> KnowledgeRetrievalResult:
        if not source_types:
            return KnowledgeRetrievalResult()

        chunks: list[dict[str, Any]] = []
        sources: list[dict[str, Any]] = []
        context_parts: list[str] = []

        for source_type in source_types:
            query = sparse_query or dense_query
            result = await query_knowledge_base(
                query_str=query,
                source_type=source_type,
                user_id=user_id,
            )
            context_text = result.get("context_text") or result.get("answer") or ""
            if context_text:
                context_parts.append(f"=== [{source_type.upper()}] ===\n{context_text}")
            for chunk in result.get("chunks", []):
                chunk.setdefault("source_type", source_type)
                chunks.append(chunk)
            sources.extend(result.get("sources", []))

        context_text = "\n".join(context_parts)
        return KnowledgeRetrievalResult(
            context_text=context_text,
            chunks=chunks,
            sources=sources,
            retrieval_hit="[SYSTEM_EMPTY_WARNING]" not in context_text if context_text else False,
        )


knowledge_retriever = KnowledgeRetriever()
