"""Knowledge tool: search_knowledge.

Wraps :func:`app.rag.knowledge_retriever.KnowledgeRetriever.retrieve`
for the L2 agent. Since the planner-merge refactor RAG no longer
splits by ``source_type`` — the BGE reranker is authoritative — so
the tool has a single ``query`` argument and searches everything.
"""

from typing import Any

from pydantic import BaseModel, Field

from app.agent_runtime.tool_registry import AgentToolContext, ToolEntry, registry


class SearchKnowledgeArgs(BaseModel):
    query: str = Field(
        ..., min_length=1, max_length=500,
        description="Search query for the knowledge base.",
    )


async def _search_knowledge_handler(
    args: SearchKnowledgeArgs, ctx: AgentToolContext,
) -> dict[str, Any]:
    from app.rag.knowledge_retriever import knowledge_retriever

    result = await knowledge_retriever.retrieve(
        dense_query=args.query,
        sparse_query=args.query,
        user_id=ctx.user_id,
    )

    chunks = []
    if result and result.chunks:
        for chunk in result.chunks[:5]:
            chunks.append({
                "text": chunk.get("text", "")[:1500],
                "source": chunk.get("source_type", "knowledge"),
                "score": (
                    round(float(chunk.get("score", 0)), 3)
                    if chunk.get("score") is not None else None
                ),
            })

    return {
        "query": args.query,
        "count": len(chunks),
        "retrieval_hit": bool(result and result.retrieval_hit),
        "chunks": chunks,
    }


registry.register(ToolEntry(
    name="search_knowledge",
    description=(
        "Search the user's knowledge corpus (interview Q&A bank, "
        "uploaded official docs, anything they've ingested) for "
        "technical concepts, algorithms, system design topics, etc. "
        "Reranker decides which chunks are most relevant — no source "
        "filtering needed at call time."
    ),
    args_model=SearchKnowledgeArgs,
    handler=_search_knowledge_handler,
    max_result_chars=10000,
    emoji="📚",
))
