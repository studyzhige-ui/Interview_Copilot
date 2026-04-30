"""测试 interview API 的异步分析任务下发与状态查询逻辑。

直接调用路由 handler 函数，Mock Celery task 和 storage。
"""
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from fastapi import HTTPException


def _make_user(username="interviewuser"):
    """构造一个 Mock User 对象。"""
    user = MagicMock()
    user.username = username
    return user


@pytest.mark.asyncio
async def test_upload_audio_calls_s3(db_session):
    """upload_audio 应创建用户归属上传记录并写入 owned key。"""
    from app.api.interview import upload_audio

    mock_file = MagicMock()
    mock_file.file = MagicMock()
    mock_file.filename = "interview.wav"
    mock_file.content_type = "audio/wav"

    with patch("app.api.interview.upload_file_to_owned_key", return_value="s3://bucket/uploads/interviewuser/upl_x/interview.wav") as mock_s3:
        result = await upload_audio(file=mock_file, db=db_session, current_user=_make_user())

    assert result["status"] == "success"
    assert result["upload_id"].startswith("upl_")
    assert "s3://" in result["storage_uri"]
    mock_s3.assert_called_once()


@pytest.mark.asyncio
async def test_analyze_dispatches_celery_task(db_session):
    """analyze_interview_endpoint 应创建 Interview 记录并下发 Celery 任务。"""
    from app.api.interview import analyze_interview_endpoint, AnalyzeRequest

    mock_task = MagicMock()
    mock_task.id = "celery-task-abc"

    with patch("app.api.interview.process_interview_analysis") as mock_process:
        mock_process.delay.return_value = mock_task

        from app.models.upload import UserUpload

        upload = UserUpload(
            user_id="interviewuser",
            purpose="interview_audio",
            original_filename="test.wav",
            storage_uri="s3://bucket/uploads/interviewuser/upl_test/test.wav",
            object_key="uploads/interviewuser/upl_test/test.wav",
            status="uploaded",
        )
        db_session.add(upload)
        db_session.flush()

        request = AnalyzeRequest(upload_id=upload.id)
        result = await analyze_interview_endpoint(
            request=request, db=db_session, current_user=_make_user()
        )

    assert result["status"] == "processing"
    assert result["task_id"] == "celery-task-abc"
    assert "interview_id" in result
    mock_process.delay.assert_called_once_with(result["interview_id"])


@pytest.mark.asyncio
async def test_check_status_not_found(db_session):
    """查询不存在的 interview_id 应返回 404。"""
    from app.api.interview import check_analysis_status

    with pytest.raises(HTTPException) as exc_info:
        await check_analysis_status(
            interview_id=99999, db=db_session, current_user=_make_user()
        )
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_check_status_returns_pending(db_session):
    """对刚创建的 Interview，应返回 PENDING 状态。"""
    from app.api.interview import check_analysis_status
    from app.models.interview import Interview

    interview = Interview(user_id="interviewuser", status="PENDING")
    db_session.add(interview)
    db_session.flush()

    result = await check_analysis_status(
        interview_id=interview.id, db=db_session, current_user=_make_user()
    )
    assert result["status"] == "PENDING"
    assert result["interview_id"] == interview.id


@pytest.mark.asyncio
async def test_analytics_report_delegates_to_service(db_session):
    """get_analytics_report 应调用 generate_comprehensive_report。"""
    from app.api.interview import get_analytics_report

    mock_report = {"status": "success", "report": {"overall_evaluation": "good"}}

    with patch("app.api.interview.generate_comprehensive_report",
               new_callable=AsyncMock, return_value=mock_report):
        result = await get_analytics_report(limit=20, current_user=_make_user())

    assert result["status"] == "success"


@pytest.mark.asyncio
async def test_save_personal_memory(db_session):
    """save_personal_memory 应调用 ingest_text。"""
    from app.api.interview import save_personal_memory, MemorySaveRequest

    request = MemorySaveRequest(
        question="什么是分布式锁？",
        improved_answer="Redisson watch dog 机制",
        original_score=4.0,
        tags=["Redis", "分布式"]
    )

    with patch("app.api.interview.ingest_text", new_callable=AsyncMock) as mock_ingest:
        result = await save_personal_memory(request=request, current_user=_make_user())

    assert result["status"] == "success"
    mock_ingest.assert_called_once()
