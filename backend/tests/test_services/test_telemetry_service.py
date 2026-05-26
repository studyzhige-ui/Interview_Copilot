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
            retrieval_hit=True
        )

    assert log_file.exists()
    lines = log_file.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 1

    data = json.loads(lines[0])
    assert data["session_id"] == "s1"
    assert data["total_tokens"] == 150
    assert data["retrieval_hit"] is True


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
