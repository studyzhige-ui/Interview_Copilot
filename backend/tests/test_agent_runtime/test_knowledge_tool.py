"""search_knowledge tool — retrieval error handling."""

import asyncio


class TestKnowledgeErrorHandling:
    """search_knowledge must catch retrieval errors."""

    def test_retrieval_error_returns_error_dict(self, monkeypatch):
        async def _boom(**kw):
            raise RuntimeError("Milvus connection lost")

        monkeypatch.setattr(
            "app.rag.knowledge_retriever.knowledge_retriever.retrieve",
            lambda **kw: _boom(**kw),
        )

        from app.agent_runtime.tool_registry import AgentToolContext
        from app.agent_runtime.tools.knowledge import (
            SearchKnowledgeArgs, _search_knowledge_handler,
        )
        ctx = AgentToolContext(user_id="alice", session_id="s1")
        result = asyncio.run(_search_knowledge_handler(
            SearchKnowledgeArgs(query="redis"), ctx,
        ))
        assert "error" in result
        assert "redis" in result["query"]
