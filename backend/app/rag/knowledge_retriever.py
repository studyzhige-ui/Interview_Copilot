"""Thin facade shared by conversation and agent retrieval."""

from app.rag.contracts import SearchIntent
from app.rag.retrieval_state import RetrievalResult
from app.rag.retriever import query_knowledge_base


class KnowledgeRetriever:
    async def retrieve(
        self,
        *,
        intents: list[SearchIntent | dict],
        user_id: str,
        source_kind: str | None = None,
        planner_failed: bool = False,
    ) -> RetrievalResult:
        """Run one retrieval pass and attach planner provenance."""
        result = await query_knowledge_base(
            intents=intents,
            user_id=user_id,
            source_kind=source_kind,
        )
        result.state.planner_failed = planner_failed
        return result


knowledge_retriever = KnowledgeRetriever()
