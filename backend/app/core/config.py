import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


load_dotenv()

logger = logging.getLogger(__name__)


def _default_app_data_dir() -> str:
    configured = os.getenv("APP_DATA_DIR")
    if configured:
        return configured
    # Keep runtime data under the project-level data directory by default.
    return str((Path(__file__).resolve().parents[3] / "data").resolve())


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        # Pydantic-settings reads env vars case-insensitively by default.
    )

    PROJECT_NAME: str = "Interview Copilot API"
    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/interview_copilot"
    DEEPSEEK_API_KEY: str = ""
    NVIDIA_API_KEY: str = ""
    HF_ENDPOINT: str = "https://hf-mirror.com"
    LLAMA_CLOUD_API_KEY: str = ""

    # Runtime data paths
    APP_DATA_DIR: str = _default_app_data_dir()

    # Database and vector-store data
    DB_DIR: str = ""
    CHROMA_DB_DIR: str = ""
    DOCSTORE_DIR: str = ""
    MILVUS_URI: str = "http://localhost:19530"
    MILVUS_COLLECTION: str = "interview_copilot_rag"
    MILVUS_SIMILARITY_METRIC: str = "IP"
    MILVUS_DENSE_INDEX_TYPE: str = "HNSW"
    MILVUS_HNSW_M: int = 16
    MILVUS_HNSW_EF_CONSTRUCTION: int = 200
    MILVUS_HNSW_EF_SEARCH: int = 64

    # Hugging Face, model, and framework caches
    CACHE_DIR: str = ""

    # Logs and telemetry
    LOG_DIR: str = ""
    LOG_LEVEL: str = "INFO"

    # Evaluation datasets and result files
    EVAL_DIR: str = ""

    # Local upload backups and object-storage staging
    STORAGE_DIR: str = ""

    EMBEDDING_DEVICE: str = "auto"
    EMBEDDING_MODEL_ID: str = "BAAI/bge-m3"
    EMBEDDING_DIM: int = 1024
    RERANKER_MODEL_ID: str = "BAAI/bge-reranker-base"
    WHISPER_MODEL_ID: str = "Systran/faster-whisper-large-v2"
    DIARIZATION_MODEL_ID: str = "pyannote-community/speaker-diarization-community-1"
    AGENT_MAX_STEPS: int = 25
    AGENT_TOOL_TIMEOUT_SECONDS: int = 30
    AGENT_TEMPERATURE: float = 0.2
    AGENT_MAX_RUNTIME_SECONDS: int = 180
    AGENT_MAX_TOTAL_TOKENS: int = 200000  # observability only, not a hard stop
    AGENT_MAX_RESPONSE_TOKENS: int = 4096
    AGENT_MAX_TOOL_CALLS: int = 50  # observability only, not a hard stop
    AGENT_MAX_CALLS_PER_TOOL: int = 8
    AGENT_TOOL_SCHEMA_STRICT: bool = True
    AGENT_MAX_TOOL_ARG_CHARS: int = 4000
    # Tool result persistence thresholds (Hermes/Claude Code pattern)
    AGENT_PERSIST_THRESHOLD: int = 30_000      # per-result: persist if > 30K chars
    AGENT_TURN_BUDGET_CHARS: int = 100_000     # per-turn aggregate: spill largest until < 100K
    AGENT_PERSIST_PREVIEW_SIZE: int = 1_500    # preview size in persisted-output block
    VECTOR_TOP_K: int = 8
    BM25_TOP_K: int = 8
    FUSION_TOP_K: int = 6
    RERANK_TOP_N: int = 5
    RAG_MIN_SCORE: float = 0.5
    RAG_FALLBACK_MIN_SCORE: float = 0.02
    RAG_LEXICAL_FALLBACK_MIN_OVERLAP: float = 0.35
    MEMORY_MILVUS_COLLECTION: str = "interview_copilot_memory"
    MEMORY_VECTOR_TOP_K: int = 8
    MEMORY_LEXICAL_TOP_K: int = 12
    MEMORY_FINAL_TOP_K: int = 3
    MEMORY_BACKFILL_ON_STARTUP: bool = True
    RESUME_MILVUS_COLLECTION: str = "interview_copilot_resume"
    TTS_DEFAULT_VOICE: str = "zh-CN-YunxiNeural"
    ANALYSIS_CHUNK_TOKEN_LIMIT: int = 12000
    LEVER_API_BASE: str = "https://api.lever.co/v0"
    LEVER_SITES: str = "openai"
    LEVER_DEFAULT_LIMIT: int = 30
    NVIDIA_API_BASE: str = "https://integrate.api.nvidia.com/v1"
    NVIDIA_CHAT_MODEL: str = "meta/llama-3.1-70b-instruct"

    # Security and JWT
    SECRET_KEY: str = "change-me-for-local-development"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days

    # CORS — comma-separated origins, default allows local Vite dev server.
    CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173"

    # Redis and Celery
    REDIS_URL: str = "redis://localhost:6379/0"

    # S3-compatible object storage. Defaults are for local MinIO development.
    AWS_ACCESS_KEY_ID: str = "minioadmin"
    AWS_SECRET_ACCESS_KEY: str = "minioadmin"
    AWS_REGION: str = "us-east-1"
    AWS_ENDPOINT_URL: str = "http://localhost:9000"
    S3_BUCKET_NAME: str = "interview-copilot-bucket"

    # Database connection pool
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_RECYCLE: int = 1800  # seconds

    @field_validator(
        "DB_DIR", "CHROMA_DB_DIR", "DOCSTORE_DIR",
        "CACHE_DIR", "LOG_DIR", "EVAL_DIR", "STORAGE_DIR",
        mode="before",
    )
    @classmethod
    def _fill_data_subdirs(cls, v: str, info) -> str:
        """Fill empty sub-directory settings with APP_DATA_DIR-based defaults."""
        if v:
            return v
        # Resolve APP_DATA_DIR from already-validated values or env/default.
        app_data = info.data.get("APP_DATA_DIR") or _default_app_data_dir()
        field_to_subdir = {
            "DB_DIR": "databases",
            "CHROMA_DB_DIR": str(Path("databases") / "chroma"),
            "DOCSTORE_DIR": "docstore",
            "CACHE_DIR": "cache",
            "LOG_DIR": "logs",
            "EVAL_DIR": "evaluation",
            "STORAGE_DIR": "storage",
        }
        subdir = field_to_subdir.get(info.field_name, info.field_name.lower())
        return str(Path(app_data) / subdir)


def _validate_secret_key(key: str) -> None:
    """Warn loudly if the SECRET_KEY is a well-known placeholder."""
    insecure_defaults = {
        "change-me-for-local-development",
        "super-secret-key-for-interview-copilot-dev",
        "your-secret-key",
        "",
    }
    if key in insecure_defaults:
        logger.warning(
            "⚠️  SECRET_KEY is set to an insecure default ('%s'). "
            "This is acceptable for local development but MUST be changed "
            "before any production deployment.",
            key[:20] + "..." if len(key) > 20 else key,
        )


settings = Settings()
_validate_secret_key(settings.SECRET_KEY)
