"""测试 storage_service 的 S3 上传与本地降级逻辑。"""
import os
from io import BytesIO
from unittest.mock import patch, MagicMock


def test_fallback_local_save_creates_file(tmp_path):
    """_fallback_local_save 应将文件正确写入本地目录。"""
    with patch("app.services.storage_service.settings") as mock_settings:
        mock_settings.STORAGE_DIR = str(tmp_path)

        from app.services.storage_service import _fallback_local_save

        content = b"test audio data 12345"
        file_obj = BytesIO(content)
        relative = "uploads/test_file.wav"

        result_path = _fallback_local_save(file_obj, relative)

        assert os.path.exists(result_path)
        with open(result_path, "rb") as f:
            assert f.read() == content


def test_fallback_local_save_creates_nested_dirs(tmp_path):
    """_fallback_local_save 应自动创建不存在的父目录。"""
    with patch("app.services.storage_service.settings") as mock_settings:
        mock_settings.STORAGE_DIR = str(tmp_path)

        from app.services.storage_service import _fallback_local_save

        file_obj = BytesIO(b"data")
        result_path = _fallback_local_save(file_obj, "a/b/c/deep_file.bin")

        assert os.path.exists(result_path)
        assert "a" in result_path
        assert "deep_file.bin" in result_path


def test_upload_to_s3_falls_back_on_client_error():
    """当 S3 upload_fileobj 抛出 ClientError 时，应降级到本地存储。"""
    from botocore.exceptions import ClientError

    with patch("app.services.storage_service.s3_client") as mock_s3, \
         patch("app.services.storage_service._fallback_local_save", return_value="/local/path/file.wav") as mock_fallback:
        # 模拟 S3 抛出错误
        mock_s3.upload_fileobj.side_effect = ClientError(
            {"Error": {"Code": "NoSuchBucket", "Message": "test"}}, "PutObject"
        )

        from app.services.storage_service import upload_file_to_s3

        result = upload_file_to_s3(BytesIO(b"data"), "test.wav")

        mock_fallback.assert_called_once()
        assert result == "/local/path/file.wav"


def test_upload_to_s3_success_returns_s3_url():
    """S3 上传成功时应返回 s3:// URL。"""
    with patch("app.services.storage_service.s3_client") as mock_s3:
        mock_s3.upload_fileobj.return_value = None  # 成功不抛异常

        from app.services.storage_service import upload_file_to_s3

        result = upload_file_to_s3(BytesIO(b"data"), "recording.wav")

        assert result.startswith("s3://")
        assert ".wav" in result
