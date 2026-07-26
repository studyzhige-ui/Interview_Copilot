"""Tests for the V2 task tool handlers and ToolEntry prompt field."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.agent_runtime.tool_registry import AgentToolContext, registry


CTX = AgentToolContext(user_id="u-test", session_id="sess-task-tool-001")


@pytest.fixture(autouse=True)
def _seed_conversation(db_session):
    from app.models.chat import Conversation

    db_session.add(
        Conversation(
            id=CTX.session_id,
            user_id=CTX.user_id,
            title="tool test",
        )
    )
    db_session.commit()


@pytest.fixture
def _patch_session_local(db_session):
    """Make task tool handlers use the test db_session."""
    with patch("app.agent_runtime.tools.tasks.SessionLocal", return_value=db_session):
        db_session.close = lambda: None
        yield


class TestTaskCreateTool:
    @pytest.mark.asyncio
    async def test_creates_task(self, _patch_session_local):
        result = await registry.dispatch(
            "task_create",
            {"subject": "Step 1", "description": "Do the thing"},
            CTX,
        )
        assert result["task_id"] == 1
        assert result["status"] == "pending"
        assert result["subject"] == "Step 1"

    @pytest.mark.asyncio
    async def test_incremental_ids(self, _patch_session_local):
        await registry.dispatch("task_create", {"subject": "A"}, CTX)
        r2 = await registry.dispatch("task_create", {"subject": "B"}, CTX)
        assert r2["task_id"] == 2


class TestTaskUpdateTool:
    @pytest.mark.asyncio
    async def test_completion_requires_verification(self, _patch_session_local):
        await registry.dispatch("task_create", {"subject": "X"}, CTX)
        result = await registry.dispatch(
            "task_update",
            {"task_id": 1, "status": "completed"},
            CTX,
        )
        assert result["error"] == "task_requires_verification"

    @pytest.mark.asyncio
    async def test_independent_verifier_completes_task(
        self, _patch_session_local, monkeypatch
    ):
        await registry.dispatch(
            "task_create",
            {
                "subject": "X",
                "acceptance_criteria": "The observed value is 3",
            },
            CTX,
        )
        await registry.dispatch(
            "task_update",
            {
                "task_id": 1,
                "status": "verifying",
                "evidence": ["command output: 3"],
            },
            CTX,
        )
        completion = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content="Evidence matches the criterion.\nVERDICT: PASS",
                    )
                )
            ]
        )
        client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=AsyncMock(return_value=completion),
                )
            )
        )
        monkeypatch.setattr(
            "app.agent_runtime.tools.tasks.build_async_openai_client_for_role",
            lambda role, user_id=None: (client, SimpleNamespace(model="verifier")),
        )
        result = await registry.dispatch("task_verify", {"task_id": 1}, CTX)
        assert result["verdict"] == "PASS"
        assert result["task"]["status"] == "completed"

    @pytest.mark.asyncio
    async def test_update_not_found(self, _patch_session_local):
        result = await registry.dispatch(
            "task_update",
            {"task_id": 999, "status": "completed"},
            CTX,
        )
        assert "error" in result


class TestTaskGetTool:
    @pytest.mark.asyncio
    async def test_get_existing(self, _patch_session_local):
        await registry.dispatch("task_create", {"subject": "Info"}, CTX)
        result = await registry.dispatch("task_get", {"task_id": 1}, CTX)
        assert result["subject"] == "Info"

    @pytest.mark.asyncio
    async def test_get_missing(self, _patch_session_local):
        result = await registry.dispatch("task_get", {"task_id": 42}, CTX)
        assert "error" in result


class TestTaskListTool:
    @pytest.mark.asyncio
    async def test_list_empty(self, _patch_session_local):
        result = await registry.dispatch("task_list", {}, CTX)
        assert result["tasks"] == []
        assert result["total"] == 0

    @pytest.mark.asyncio
    async def test_list_multiple(self, _patch_session_local):
        await registry.dispatch("task_create", {"subject": "A"}, CTX)
        await registry.dispatch("task_create", {"subject": "B"}, CTX)
        result = await registry.dispatch("task_list", {}, CTX)
        assert result["total"] == 2


class TestToolEntryPromptField:
    def test_task_tools_have_prompts(self):
        for name in (
            "task_create",
            "task_update",
            "task_get",
            "task_list",
            "task_verify",
            "task_checkpoint",
        ):
            entry = registry.get(name)
            assert entry is not None
            assert entry.prompt, f"{name} should have a non-empty prompt"

    def test_format_tool_prompts_includes_task_tools(self):
        text = registry.format_tool_prompts()
        assert "# Tool guidance" in text
        assert "## task_create" in text
        assert "## task_update" in text

    def test_format_tool_prompts_excludes_filtered(self):
        text = registry.format_tool_prompts(
            exclude={"task_create", "task_update", "task_get", "task_list"},
        )
        assert "task_create" not in text

    def test_existing_tools_have_empty_prompt(self):
        entry = registry.get("web_search")
        assert entry is not None
        assert entry.prompt == ""
