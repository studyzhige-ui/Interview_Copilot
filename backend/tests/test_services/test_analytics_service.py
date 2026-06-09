"""Tests for diagnostics_report_service report generation.

The diagnostic input now comes from the active ``memory_ability_states`` via
``_extract_ability_records(db, user_id)`` (topic mastery + summary); we patch
that extractor (and the LLM) so these tests cover the report-assembly logic,
not the data source.
"""
import json

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

_SVC = "app.services.analytics.diagnostics_report_service"


@pytest.mark.asyncio
async def test_generate_report_empty_when_no_ability_records():
    with patch(f"{_SVC}._extract_ability_records", return_value=[]):
        from app.services.analytics.diagnostics_report_service import generate_comprehensive_report
        result = await generate_comprehensive_report(limit=20, user_id="u1")
        assert result["status"] == "empty"


@pytest.mark.asyncio
async def test_generate_report_empty_when_no_user():
    from app.services.analytics.diagnostics_report_service import generate_comprehensive_report
    result = await generate_comprehensive_report(limit=20, user_id=None)
    assert result["status"] == "empty"


@pytest.mark.asyncio
async def test_generate_report_successful_json_parse():
    memories = [{"content": "我在 Redis 分布式锁上得了 3 分", "score": 3.0, "time": "2026-01-01T00:00:00"}]
    report_json = json.dumps({
        "overall_evaluation": "技术薄弱",
        "strengths": [],
        "weaknesses": [{"topic": "Redis", "flaw": "概念混乱", "plan": "重读源码"}],
        "skill_radar": {"算法": 5.0},
    })
    mock_response = MagicMock()
    mock_response.text = report_json

    with patch(f"{_SVC}._extract_ability_records", return_value=memories), \
         patch(f"{_SVC}.agent_fast_llm") as llm_mock:
        llm_mock.acomplete = AsyncMock(return_value=mock_response)
        from app.services.analytics.diagnostics_report_service import generate_comprehensive_report
        result = await generate_comprehensive_report(limit=20, user_id="u1")

    assert result["status"] == "success"
    assert result["overall_evaluation"] == "技术薄弱"
    assert any(w["k"] == "Redis" for w in result["weaknesses"])


@pytest.mark.asyncio
async def test_generate_report_strips_markdown_codeblock():
    memories = [{"content": "test", "score": 5.0, "time": "2026-01-01"}]
    raw = '```json\n{"overall_evaluation": "OK", "strengths": [], "weaknesses": [], "skill_radar": {}}\n```'
    mock_response = MagicMock()
    mock_response.text = raw

    with patch(f"{_SVC}._extract_ability_records", return_value=memories), \
         patch(f"{_SVC}.agent_fast_llm") as llm_mock:
        llm_mock.acomplete = AsyncMock(return_value=mock_response)
        from app.services.analytics.diagnostics_report_service import generate_comprehensive_report
        result = await generate_comprehensive_report(limit=20, user_id="u1")

    assert result["status"] == "success"


@pytest.mark.asyncio
async def test_generate_report_fallback_on_invalid_json():
    memories = [{"content": "test", "score": 5.0, "time": "2026-01-01"}]
    mock_response = MagicMock()
    mock_response.text = "这不是合法的 JSON 格式"

    with patch(f"{_SVC}._extract_ability_records", return_value=memories), \
         patch(f"{_SVC}.agent_fast_llm") as llm_mock:
        llm_mock.acomplete = AsyncMock(return_value=mock_response)
        from app.services.analytics.diagnostics_report_service import generate_comprehensive_report
        result = await generate_comprehensive_report(limit=20, user_id="u1")

    assert result["status"] == "fallback"
    assert "raw_text" in result
