"""read_interview_history tool — DB error handling."""

import asyncio


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
            ReadInterviewHistoryArgs, _read_interview_history_handler,
        )
        ctx = AgentToolContext(user_id="alice", session_id="s1")
        result = asyncio.run(_read_interview_history_handler(
            ReadInterviewHistoryArgs(), ctx,
        ))
        assert "error" in result
