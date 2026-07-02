"""Tests for the agent stop hook (incomplete-task reminder)."""
from unittest.mock import MagicMock, patch

import pytest

from app.conversation.agent_strategy import AgentLoopStrategy


class TestCheckIncompleteTasks:
    @pytest.mark.asyncio
    async def test_returns_empty_when_no_tasks(self):
        with patch(
            "app.db.database.SessionLocal",
        ) as mock_sl, patch(
            "app.services.task_service.list_incomplete",
            return_value=[],
        ):
            mock_sl.return_value.close = MagicMock()
            result = await AgentLoopStrategy._check_incomplete_tasks("sess-1")
            assert result == []

    @pytest.mark.asyncio
    async def test_returns_incomplete_tasks(self):
        incomplete = [
            {"task_id": 1, "subject": "Step A", "status": "pending"},
            {"task_id": 2, "subject": "Step B", "status": "in_progress"},
        ]
        with patch(
            "app.db.database.SessionLocal",
        ) as mock_sl, patch(
            "app.services.task_service.list_incomplete",
            return_value=incomplete,
        ):
            mock_sl.return_value.close = MagicMock()
            result = await AgentLoopStrategy._check_incomplete_tasks("sess-1")
            assert len(result) == 2
            assert result[0]["task_id"] == 1
