"""测试 interview API 的异步分析任务下发与状态查询逻辑。

直接调用路由 handler 函数，Mock Celery task 和 storage。
"""
import pytest
from unittest.mock import MagicMock, patch, AsyncMock


def _make_user(username="interviewuser"):
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

    with patch(
        "app.api.interview.upload_file_to_owned_key",
        return_value="s3://bucket/uploads/interviewuser/upl_x/interview.wav",
    ) as mock_s3:
        result = await upload_audio(file=mock_file, db=db_session, current_user=_make_user())

    assert result["status"] == "success"
    assert result["upload_id"].startswith("upl_")
    assert "s3://" in result["storage_uri"]
    mock_s3.assert_called_once()


@pytest.mark.asyncio
async def test_analyze_dispatches_orchestrator(db_session):
    """analyze_interview_endpoint 应创建 InterviewRecord 并 dispatch Celery orchestrator."""
    from app.api.interview import analyze_interview_endpoint, AnalyzeRequest
    from app.models.upload import UserUpload

    mock_task = MagicMock()
    mock_task.id = "celery-task-abc"

    resume_upload = UserUpload(
        user_id="interviewuser",
        purpose="interview_resume",
        original_filename="resume.pdf",
        storage_uri="s3://bucket/uploads/interviewuser/upl_resume/resume.pdf",
        object_key="uploads/interviewuser/upl_resume/resume.pdf",
        status="uploaded",
    )
    audio_upload = UserUpload(
        user_id="interviewuser",
        purpose="interview_audio",
        original_filename="test.wav",
        storage_uri="s3://bucket/uploads/interviewuser/upl_test/test.wav",
        object_key="uploads/interviewuser/upl_test/test.wav",
        status="uploaded",
    )
    db_session.add_all([resume_upload, audio_upload])
    db_session.flush()

    with patch("app.api.interview.process_interview_analysis") as mock_process, \
         patch("app.api.interview._extract_resume_snapshot", return_value="resume text"):
        mock_process.delay.return_value = mock_task

        request = AnalyzeRequest(
            upload_id=audio_upload.id,
            resume_upload_id=resume_upload.id,
        )
        result = await analyze_interview_endpoint(
            request=request, db=db_session, current_user=_make_user()
        )

    assert result["status"] == "processing"
    assert result["task_id"] == "celery-task-abc"
    assert result["record_id"].startswith("ir_")
    mock_process.delay.assert_called_once_with(result["record_id"])


@pytest.mark.asyncio
async def test_analytics_report_delegates_to_service(db_session):
    """get_analytics_report 应调用 generate_comprehensive_report。"""
    from app.api.interview import get_analytics_report

    mock_report = {"status": "success", "report": {"overall_evaluation": "good"}}

    with patch(
        "app.api.interview.generate_comprehensive_report",
        new_callable=AsyncMock,
        return_value=mock_report,
    ):
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
        tags=["Redis", "分布式"],
    )

    with patch("app.api.interview.ingest_text", new_callable=AsyncMock) as mock_ingest:
        result = await save_personal_memory(request=request, current_user=_make_user())

    assert result["status"] == "success"
    mock_ingest.assert_called_once()
