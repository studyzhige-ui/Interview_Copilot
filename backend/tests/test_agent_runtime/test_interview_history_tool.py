"""read_interview_history tool — DB error handling."""

import asyncio
import json
from types import SimpleNamespace


class TestInterviewHistoryErrorHandling:
    """read_interview_history must catch DB errors."""

    def test_db_error_returns_error_dict(self, monkeypatch):
        def _boom(*a, **kw):
            raise RuntimeError("DB connection refused")

        monkeypatch.setattr(
            "app.services.interview.interview_record_service.interview_record_service.list_by_user",
            _boom,
        )

        from app.agent_runtime.tool_registry import AgentToolContext
        from app.agent_runtime.tools.interview_history import (
            ReadInterviewHistoryArgs,
            _read_interview_history_handler,
        )

        ctx = AgentToolContext(user_id="alice", session_id="s1")
        result = asyncio.run(
            _read_interview_history_handler(
                ReadInterviewHistoryArgs(),
                ctx,
            )
        )
        assert "error" in result


def test_reads_multiple_question_details_in_one_call():
    from app.agent_runtime.tool_registry import AgentToolContext
    from app.agent_runtime.tools.interview_history import (
        ReadInterviewHistoryArgs,
        _read_single_record,
    )

    record = SimpleNamespace(
        id="ir_1",
        source="mock",
        title="模拟面试",
        status="review_ready",
        created_at=None,
        analysis_json=json.dumps({"overall": {"score": 7, "summary": "整体"}}),
    )
    qa_rows = [
        SimpleNamespace(
            order_idx=1,
            phase="technical",
            question="为什么使用索引？",
            answer="为了加速查询。",
            score=6.0,
            critique="缺少代价分析。",
            improved_answer="索引以写入和空间换读取性能。",
            key_points_json='["数据库索引"]',
        ),
        SimpleNamespace(
            order_idx=4,
            phase="project",
            question="如何处理超时？",
            answer="设置超时并重试。",
            score=None,
            critique="需要说明幂等性。",
            improved_answer="设置分层超时，并仅对幂等操作重试。",
            key_points_json='["超时", "幂等"]',
        ),
    ]
    service = SimpleNamespace(
        get=lambda *_: record,
        list_qa=lambda *_: qa_rows,
    )
    result = _read_single_record(
        ReadInterviewHistoryArgs(record_id="ir_1", question_indexes=[5, 2, 9, 2]),
        AgentToolContext(user_id="alice", session_id="s1"),
        service,
    )

    assert [item["index"] for item in result["question_details"]] == [5, 2]
    assert result["question_details"][1]["answer"] == "为了加速查询。"
    assert result["question_details"][1]["tags"] == ["数据库索引"]
    assert result["missing_question_indexes"] == [9]
