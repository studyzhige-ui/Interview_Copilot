"""测试 app.core.config.Settings 的路径计算逻辑。"""
import os
from pathlib import Path


def test_settings_has_required_attributes():
    """Settings 单例应包含所有必需的配置属性。"""
    from app.core.config import settings

    required = [
        "DATABASE_URL", "APP_DATA_DIR", "DB_DIR", "CHROMA_DB_DIR",
        "DOCSTORE_DIR", "CACHE_DIR", "LOG_DIR", "EVAL_DIR", "STORAGE_DIR",
        "EMBEDDING_MODEL_ID", "RERANKER_MODEL_ID", "SECRET_KEY",
        "REDIS_URL", "S3_BUCKET_NAME",
    ]
    for attr in required:
        assert hasattr(settings, attr), f"Settings 缺少属性: {attr}"


def test_default_app_data_dir_points_to_project_root():
    """默认 APP_DATA_DIR 应指向项目根目录下的 data/ 文件夹。"""
    from app.core.config import _default_app_data_dir

    # 清除环境变量覆盖，让函数走默认路径
    old = os.environ.pop("APP_DATA_DIR", None)
    try:
        result = _default_app_data_dir()
        assert result.endswith("data"), f"期望以 'data' 结尾，实际: {result}"
        assert Path(result).is_absolute(), "路径应为绝对路径"
    finally:
        if old is not None:
            os.environ["APP_DATA_DIR"] = old


def test_app_data_dir_respects_env_override():
    """APP_DATA_DIR 应优先使用环境变量。"""
    from app.core.config import _default_app_data_dir

    os.environ["APP_DATA_DIR"] = "/custom/test/path"
    try:
        assert _default_app_data_dir() == "/custom/test/path"
    finally:
        del os.environ["APP_DATA_DIR"]


def test_sub_dirs_are_children_of_app_data_dir():
    """所有子目录（DB_DIR, CACHE_DIR 等）都应是 APP_DATA_DIR 的子路径。"""
    from app.core.config import settings

    base = Path(settings.APP_DATA_DIR)
    for attr in ["DB_DIR", "CACHE_DIR", "LOG_DIR", "EVAL_DIR", "STORAGE_DIR"]:
        child = Path(getattr(settings, attr))
        # 检查子路径关系（兼容不同 OS 的路径分隔符）
        assert str(child).startswith(str(base)), \
            f"{attr}={child} 不是 APP_DATA_DIR={base} 的子路径"


def test_rag_score_thresholds_are_valid():
    """RAG 相关的数值配置应为合理值。"""
    from app.core.config import settings

    assert 0 < settings.RAG_MIN_SCORE <= 1.0
    assert settings.VECTOR_TOP_K > 0
    assert settings.BM25_TOP_K > 0
    assert settings.FUSION_TOP_K > 0
    assert settings.RERANK_TOP_N > 0
