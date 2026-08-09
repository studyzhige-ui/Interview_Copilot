"""One application entry point shared by Chat, Agent, API, and evaluation."""

from __future__ import annotations

from app.rag.domain.models import RetrievalResult, SearchIntent
from app.rag.retrieval.pipeline import knowledge_retrieval_pipeline


class RagService:
    def initialize(self) -> None:
        knowledge_retrieval_pipeline.initialize()

    async def retrieve(
        self,
        *,
        intents: list[SearchIntent | dict],
        user_id: str,
        source_kind: str | None = None,
        planner_failed: bool = False,
        min_score: float | None = None,
        include_diagnostics: bool = False,
    ) -> RetrievalResult:
        result = await knowledge_retrieval_pipeline.retrieve(
            intents=intents,
            user_id=user_id,
            source_kind=source_kind,
            min_score=min_score,
            include_diagnostics=include_diagnostics,
        )
        result.state.planner_failed = planner_failed
        return result


rag_service = RagService()


__all__ = ["RagService", "rag_service"]
