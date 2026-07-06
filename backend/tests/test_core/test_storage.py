"""测试 app.core.storage 的 S3 上传与本地降级逻辑。

UP-8/UP-10 之后的契约：降级写盘统一返回 ``local://`` URI（不再返回绝对
路径）；legacy 的 ``upload_file_to_s3`` 已删除，业务统一走
``upload_file_to_owned_key``。
"""
from io import BytesIO
from unittest.mock import patch


def test_fallback_local_save_returns_local_uri(tmp_path):
    """_fallback_local_save 应写入本地并返回 local:// URI（供读取方解析）。"""
    with patch("app.core.storage.settings") as mock_settings:
        mock_settings.STORAGE_DIR = str(tmp_path)

        from app.core.storage import _fallback_local_save, parse_local_uri

        content = b"test audio data 12345"
        file_obj = BytesIO(content)
        relative = "uploads/test_file.wav"

        result_uri = _fallback_local_save(file_obj, relative)

        assert result_uri == "local://uploads/test_file.wav"
        saved = parse_local_uri(result_uri)
        assert saved.is_file()
        assert saved.read_bytes() == content


def test_fallback_local_save_creates_nested_dirs(tmp_path):
    """_fallback_local_save 应自动创建不存在的父目录。"""
    with patch("app.core.storage.settings") as mock_settings:
        mock_settings.STORAGE_DIR = str(tmp_path)

        from app.core.storage import _fallback_local_save, parse_local_uri

        file_obj = BytesIO(b"data")
        result_uri = _fallback_local_save(file_obj, "a/b/c/deep_file.bin")

        assert result_uri == "local://a/b/c/deep_file.bin"
        assert parse_local_uri(result_uri).is_file()


def test_upload_owned_key_falls_back_on_client_error(tmp_path):
    """当 S3 upload_fileobj 抛出 ClientError 时，应降级到本地存储并返回
    实际落点的 local:// URI —— 调用方必须持久化这个返回值（UP-8）。"""
    from botocore.exceptions import ClientError

    with patch("app.core.storage.s3_client") as mock_s3, \
         patch("app.core.storage.settings") as mock_settings:
        mock_settings.STORAGE_DIR = str(tmp_path)
        mock_s3.upload_fileobj.side_effect = ClientError(
            {"Error": {"Code": "NoSuchBucket", "Message": "test"}}, "PutObject"
        )

        from app.core.storage import upload_file_to_owned_key

        result = upload_file_to_owned_key(BytesIO(b"data"), "uploads/1/fa_x/file.wav")

        assert result == "local://uploads/1/fa_x/file.wav"


def test_upload_owned_key_success_returns_s3_uri():
    """S3 上传成功时应返回 s3:// URI。"""
    with patch("app.core.storage.s3_client") as mock_s3:
        mock_s3.upload_fileobj.return_value = None  # 成功不抛异常

        from app.core.storage import upload_file_to_owned_key

        result = upload_file_to_owned_key(BytesIO(b"data"), "uploads/1/fa_x/rec.wav")

        assert result.startswith("s3://")
        assert result.endswith("uploads/1/fa_x/rec.wav")
