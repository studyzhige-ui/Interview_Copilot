"""L1 QA pipeline — multi-turn dialogue with memory + RAG.

Renamed from ``app.agent`` to disambiguate from ``app.agent_runtime``
(the L2 ReAct tool-using agent).  This package handles the everyday
question-answering loop: query rewriting/planning, memory recall,
RAG retrieval, and answer generation.
"""
