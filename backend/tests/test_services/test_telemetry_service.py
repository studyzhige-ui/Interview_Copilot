"""测试 telemetry_service 的 JSONL 写入与异常容错。"""
import json
import pytest
from unittest.mock import patch


@pytest.mark.asyncio
async def test_log_interaction_writes_jsonl(tmp_path):
    """log_interaction_metrics 应向 JSONL 文件追加一行合法 JSON。"""
    log_file = tmp_path / "metrics.jsonl"

    with patch("app.services.analytics.telemetry_service.LOG_FILE", log_file):
        from app.services.analytics.telemetry_service import log_interaction_metrics

        await log_interaction_metrics(
            session_id="s1",
            user_id="u1",
            latency=0.5,
            prompt_tokens=100,
            completion_tokens=50,
            retrieval_attempted=True,
            retrieval_hit=True,
            planner_failed=True,
            fallback_used=True,
            empty_reason="all_below_threshold",
        )

    assert log_file.exists()
    lines = log_file.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 1

    data = json.loads(lines[0])
    assert data["session_id"] == "s1"
    assert data["total_tokens"] == 150
    assert data["retrieval_hit"] is True
    # RAG degradation signals are persisted for online aggregation.
    assert data["planner_failed"] is True
    assert data["fallback_used"] is True
    assert data["empty_reason"] == "all_below_threshold"


@pytest.mark.asyncio
async def test_log_interaction_rag_fields_default_false(tmp_path):
    """A non-RAG turn omits the degradation kwargs → defaults, not missing keys."""
    log_file = tmp_path / "metrics.jsonl"
    with patch("app.services.analytics.telemetry_service.LOG_FILE", log_file):
        from app.services.analytics.telemetry_service import log_interaction_metrics

        await log_interaction_metrics(
            session_id="s3", user_id="u3", latency=0.1,
            prompt_tokens=1, completion_tokens=1,
            retrieval_attempted=False, retrieval_hit=False,
        )
    data = json.loads(log_file.read_text(encoding="utf-8").strip())
    assert data["planner_failed"] is False
    assert data["fallback_used"] is False
    assert data["empty_reason"] is None


@pytest.mark.asyncio
async def test_log_interaction_does_not_raise_on_write_error():
    """写入失败时，telemetry 不应抛出异常（旁路容错）。"""
    with patch("app.services.analytics.telemetry_service._write_log_sync", side_effect=PermissionError("denied")):
        from app.services.analytics.telemetry_service import log_interaction_metrics

        # 应静默失败，不抛异常
        await log_interaction_metrics(
            session_id="s2", user_id="u2", latency=1.0,
            prompt_tokens=0, completion_tokens=0,
            retrieval_attempted=False, retrieval_hit=False
        )
