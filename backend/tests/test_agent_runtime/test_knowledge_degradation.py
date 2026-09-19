"""The Agent sees service failure as incomplete retrieval, not absent evidence."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.agent_runtime.tools import knowledge
from app.rag.domain.models import RetrievalResult, RetrievalState


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reason", ["capacity_exhausted", "retrieval_incomplete", "canonical_unavailable"]
)
async def test_tool_preserves_degraded_reason(monkeypatch, reason):
    monkeypatch.setattr(
        knowledge.rag_service,
        "retrieve",
        AsyncMock(
            return_value=RetrievalResult(
                state=RetrievalState(empty_reason=reason, fallback_used=True)
            )
        ),
    )
    monkeypatch.setattr(
        knowledge.grounding_builder,
        "build",
        lambda *_a, **_k: SimpleNamespace(
            included_chunks=[], sources=[], supported=False, missing_terms=[]
        ),
    )
    result = await knowledge._search_knowledge_handler(
        knowledge.SearchKnowledgeArgs(query="事务设计"),
        SimpleNamespace(user_id="alice"),
    )
    assert result["empty_reason"] == reason
    assert result["degraded"] is True
    assert result["count"] == 0
    assert result["evidence_supported"] is False
