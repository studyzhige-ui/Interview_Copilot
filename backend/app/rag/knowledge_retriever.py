"""Single-shot RAG retrieval facade.

Wraps :func:`app.rag.retriever.query_knowledge_base` so the conversation
engine and the L2 agent's knowledge tool call retrieval the same way.
Deliberately thin: the dense/sparse pair are REAL separate inputs now
(dense drives the embedding, sparse drives BM25 — either falls back to the
other when blank, so a single-query caller passes the same string twice),
and the facade stamps planner state onto the returned
:class:`~app.rag.retrieval_state.RetrievalState`.

``source_kind=None`` (the default) searches every source the user has — the
reranker decides which chunks survive. Pass an explicit ``source_kind`` only
when a caller has a hard reason to scope to one corpus.
"""

from app.rag.retrieval_state import RetrievalResult
from app.rag.retriever import query_knowledge_base


class KnowledgeRetriever:
    async def retrieve(
        self,
        *,
        dense_query: str,
        sparse_query: str,
        user_id: str,
        source_kind: str | None = None,
        sub_queries: list[dict] | None = None,
        planner_failed: bool = False,
    ) -> RetrievalResult:
        """Run one retrieval pass against the user's knowledge corpus.

        ``sub_queries`` (planner multi-intent split) fan out into separate
        retrievals merged under one rerank — see ``query_knowledge_base``.
        ``planner_failed`` is the engine-side flag (planner LLM crashed →
        original-question fallback retrieval); the retriever itself can't
        know it, so the facade stamps it onto the state here.
        """
        result = await query_knowledge_base(
            dense_query=dense_query,
            sparse_query=sparse_query,
            user_id=user_id,
            source_kind=source_kind,
            sub_queries=sub_queries,
        )
        result.state.planner_failed = planner_failed
        return result


knowledge_retriever = KnowledgeRetriever()
