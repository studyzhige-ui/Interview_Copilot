import asyncio
import json


def test_query_planner_parses_dense_sparse_and_retrieval_plan(monkeypatch):
    from app.qa_pipeline import planner

    class FakeResponse:
        text = json.dumps(
            {
                "standalone_query": "Explain Redis cache avalanche for interviews.",
                "dense_query": "Redis cache avalanche interview explanation",
                "sparse_query": "Redis cache avalanche",
                "needs_memory_retrieval": True,
                "memory_types": ["interaction_preference"],
                "needs_knowledge_retrieval": True,
                "knowledge_sources": ["interview_qa"],
                "answer_mode": "knowledge_qa",
                "reasoning": "technical interview question",
            }
        )

    class FakeLLM:
        async def acomplete(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr(planner, "agent_fast_llm", FakeLLM())

    result = asyncio.run(planner.plan_query("那这个怎么答？", "Redis cache avalanche"))

    assert result.dense_query == "Redis cache avalanche interview explanation"
    assert result.sparse_query == "Redis cache avalanche"
    assert result.memory_types == ["interaction_preference"]
    assert result.knowledge_sources == ["interview_qa"]
