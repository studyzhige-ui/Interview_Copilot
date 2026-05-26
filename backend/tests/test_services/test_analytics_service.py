"""测试 diagnostics_report_service 的报告生成逻辑。

核心依赖（SimpleDocumentStore、agent_fast_llm）全部 Mock。
"""
import json
import pytest
from unittest.mock import patch, MagicMock, AsyncMock


@pytest.mark.asyncio
async def test_generate_report_empty_when_no_docstore():
    """当 DOCSTORE_DIR 不存在时，应返回 empty 状态。"""
    with patch("app.services.analytics.diagnostics_report_service.os.path.exists", return_value=False):
        from app.services.analytics.diagnostics_report_service import generate_comprehensive_report
        result = await generate_comprehensive_report(limit=20, user_id="u1")
        assert result["status"] == "empty"


@pytest.mark.asyncio
async def test_generate_report_empty_when_no_personal_memories():
    """Docstore 存在但没有属于该用户的 personal_memory 时，应返回 empty。"""
    mock_docstore = MagicMock()
    mock_docstore.docs = {}  # 空文档库

    with patch("app.services.analytics.diagnostics_report_service.os.path.exists", return_value=True), \
         patch("app.services.analytics.diagnostics_report_service.SimpleDocumentStore.from_persist_dir", return_value=mock_docstore):
        from app.services.analytics.diagnostics_report_service import generate_comprehensive_report
        result = await generate_comprehensive_report(limit=20, user_id="u1")
        assert result["status"] == "empty"


@pytest.mark.asyncio
async def test_generate_report_successful_json_parse():
    """LLM 返回合法 JSON 时，报告应成功解析。"""
    # 构造 Mock 文档
    mock_doc = MagicMock()
    mock_doc.text = "我在 Redis 分布式锁上得了 3 分"
    mock_doc.metadata = {
        "source_type": "personal_memory",
        "user_id": "u1",
        "original_score": 3.0,
        "last_accessed": "2026-01-01T00:00:00"
    }
    mock_docstore = MagicMock()
    mock_docstore.docs = {"doc1": mock_doc}

    report_json = json.dumps({
        "overall_evaluation": "技术薄弱",
        "strengths": [],
        "weaknesses": [{"topic": "Redis", "flaw": "概念混乱", "plan": "重读源码"}],
        "skill_radar": {"算法": 5.0}
    })

    mock_response = MagicMock()
    mock_response.text = report_json

    with patch("app.services.analytics.diagnostics_report_service.os.path.exists", return_value=True), \
         patch("app.services.analytics.diagnostics_report_service.SimpleDocumentStore.from_persist_dir", return_value=mock_docstore), \
         patch("app.services.analytics.diagnostics_report_service.agent_fast_llm") as llm_mock:
        llm_mock.acomplete = AsyncMock(return_value=mock_response)

        from app.services.analytics.diagnostics_report_service import generate_comprehensive_report
        result = await generate_comprehensive_report(limit=20, user_id="u1")

        assert result["status"] == "success"
        # _normalize_report flattens overall_evaluation to the top level.
        assert result["overall_evaluation"] == "技术薄弱"
        # weaknesses are normalized — topic → k, flaw → why
        assert any(w["k"] == "Redis" for w in result["weaknesses"])


@pytest.mark.asyncio
async def test_generate_report_strips_markdown_codeblock():
    """LLM 返回被 ```json 包裹的结果时，应正确清洗后解析。"""
    mock_doc = MagicMock()
    mock_doc.text = "test"
    mock_doc.metadata = {
        "source_type": "personal_memory", "user_id": "u1",
        "original_score": 5.0, "last_accessed": "2026-01-01"
    }
    mock_docstore = MagicMock()
    mock_docstore.docs = {"d1": mock_doc}

    # LLM 返回带 markdown 包裹的 JSON
    raw = '```json\n{"overall_evaluation": "OK", "strengths": [], "weaknesses": [], "skill_radar": {}}\n```'
    mock_response = MagicMock()
    mock_response.text = raw

    with patch("app.services.analytics.diagnostics_report_service.os.path.exists", return_value=True), \
         patch("app.services.analytics.diagnostics_report_service.SimpleDocumentStore.from_persist_dir", return_value=mock_docstore), \
         patch("app.services.analytics.diagnostics_report_service.agent_fast_llm") as llm_mock:
        llm_mock.acomplete = AsyncMock(return_value=mock_response)

        from app.services.analytics.diagnostics_report_service import generate_comprehensive_report
        result = await generate_comprehensive_report(limit=20, user_id="u1")

        assert result["status"] == "success"


@pytest.mark.asyncio
async def test_generate_report_fallback_on_invalid_json():
    """LLM 返回无法解析的文本时，应返回 fallback 状态。"""
    mock_doc = MagicMock()
    mock_doc.text = "test"
    mock_doc.metadata = {
        "source_type": "personal_memory", "user_id": "u1",
        "original_score": 5.0, "last_accessed": "2026-01-01"
    }
    mock_docstore = MagicMock()
    mock_docstore.docs = {"d1": mock_doc}

    mock_response = MagicMock()
    mock_response.text = "这不是合法的 JSON 格式"

    with patch("app.services.analytics.diagnostics_report_service.os.path.exists", return_value=True), \
         patch("app.services.analytics.diagnostics_report_service.SimpleDocumentStore.from_persist_dir", return_value=mock_docstore), \
         patch("app.services.analytics.diagnostics_report_service.agent_fast_llm") as llm_mock:
        llm_mock.acomplete = AsyncMock(return_value=mock_response)

        from app.services.analytics.diagnostics_report_service import generate_comprehensive_report
        result = await generate_comprehensive_report(limit=20, user_id="u1")

        assert result["status"] == "fallback"
        assert "raw_text" in result
