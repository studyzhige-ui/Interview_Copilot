import os
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()


def _default_app_data_dir() -> str:
    configured = os.getenv("APP_DATA_DIR")
    if configured:
        return configured
    # Keep runtime data under the project-level data directory by default.
    return str((Path(__file__).resolve().parents[3] / "data").resolve())


class Settings:
    PROJECT_NAME: str = "Interview Copilot API"
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "postgresql://postgres:postgres@localhost:5432/interview_copilot",
    )
    DEEPSEEK_API_KEY: str = os.getenv("DEEPSEEK_API_KEY", "")
    NVIDIA_API_KEY: str = os.getenv("NVIDIA_API_KEY", "")
    HF_ENDPOINT: str = os.getenv("HF_ENDPOINT", "https://hf-mirror.com")
    LLAMA_CLOUD_API_KEY: str = os.getenv("LLAMA_CLOUD_API_KEY", "")

    # Runtime data paths
    APP_DATA_DIR: str = _default_app_data_dir()

    # Database and vector-store data
    DB_DIR: str = os.getenv("DB_DIR", str(Path(APP_DATA_DIR) / "databases"))
    CHROMA_DB_DIR: str = os.getenv("CHROMA_DB_DIR", str(Path(DB_DIR) / "chroma"))
    DOCSTORE_DIR: str = os.getenv("DOCSTORE_DIR", str(Path(APP_DATA_DIR) / "docstore"))
    MILVUS_URI: str = os.getenv("MILVUS_URI", "http://localhost:19530")
    MILVUS_COLLECTION: str = os.getenv("MILVUS_COLLECTION", "interview_copilot_rag")
    MILVUS_SIMILARITY_METRIC: str = os.getenv("MILVUS_SIMILARITY_METRIC", "IP")
    MILVUS_DENSE_INDEX_TYPE: str = os.getenv("MILVUS_DENSE_INDEX_TYPE", "HNSW")
    MILVUS_HNSW_M: int = int(os.getenv("MILVUS_HNSW_M", "16"))
    MILVUS_HNSW_EF_CONSTRUCTION: int = int(os.getenv("MILVUS_HNSW_EF_CONSTRUCTION", "200"))
    MILVUS_HNSW_EF_SEARCH: int = int(os.getenv("MILVUS_HNSW_EF_SEARCH", "64"))

    # Hugging Face, model, and framework caches
    CACHE_DIR: str = os.getenv("CACHE_DIR", str(Path(APP_DATA_DIR) / "cache"))

    # Logs and telemetry
    LOG_DIR: str = os.getenv("LOG_DIR", str(Path(APP_DATA_DIR) / "logs"))

    # Evaluation datasets and result files
    EVAL_DIR: str = os.getenv("EVAL_DIR", str(Path(APP_DATA_DIR) / "evaluation"))

    # Local upload backups and object-storage staging
    STORAGE_DIR: str = os.getenv("STORAGE_DIR", str(Path(APP_DATA_DIR) / "storage"))

    EMBEDDING_DEVICE: str = os.getenv("EMBEDDING_DEVICE", "auto")
    EMBEDDING_MODEL_ID: str = os.getenv("EMBEDDING_MODEL_ID", "BAAI/bge-small-zh-v1.5")
    RERANKER_MODEL_ID: str = os.getenv("RERANKER_MODEL_ID", "BAAI/bge-reranker-base")
    WHISPER_MODEL_ID: str = os.getenv("WHISPER_MODEL_ID", "Systran/faster-whisper-large-v2")
    DIARIZATION_MODEL_ID: str = os.getenv(
        "DIARIZATION_MODEL_ID",
        "pyannote-community/speaker-diarization-community-1",
    )
    AGENT_MAX_STEPS: int = int(os.getenv("AGENT_MAX_STEPS", "8"))
    AGENT_TOOL_TIMEOUT_SECONDS: int = int(os.getenv("AGENT_TOOL_TIMEOUT_SECONDS", "20"))
    AGENT_OBSERVATION_CHAR_LIMIT: int = int(os.getenv("AGENT_OBSERVATION_CHAR_LIMIT", "6000"))
    AGENT_TEMPERATURE: float = float(os.getenv("AGENT_TEMPERATURE", "0.2"))
    AGENT_MAX_RUNTIME_SECONDS: int = int(os.getenv("AGENT_MAX_RUNTIME_SECONDS", "90"))
    AGENT_MAX_TOTAL_TOKENS: int = int(os.getenv("AGENT_MAX_TOTAL_TOKENS", "32000"))
    AGENT_MAX_RESPONSE_TOKENS: int = int(os.getenv("AGENT_MAX_RESPONSE_TOKENS", "2048"))
    AGENT_MAX_TOOL_CALLS: int = int(os.getenv("AGENT_MAX_TOOL_CALLS", "16"))
    AGENT_MAX_CALLS_PER_TOOL: int = int(os.getenv("AGENT_MAX_CALLS_PER_TOOL", "6"))
    AGENT_TOOL_SCHEMA_STRICT: bool = os.getenv("AGENT_TOOL_SCHEMA_STRICT", "true").lower() == "true"
    AGENT_MAX_TOOL_ARG_CHARS: int = int(os.getenv("AGENT_MAX_TOOL_ARG_CHARS", "4000"))
    VECTOR_TOP_K: int = int(os.getenv("VECTOR_TOP_K", "8"))
    BM25_TOP_K: int = int(os.getenv("BM25_TOP_K", "8"))
    FUSION_TOP_K: int = int(os.getenv("FUSION_TOP_K", "6"))
    RERANK_TOP_N: int = int(os.getenv("RERANK_TOP_N", "5"))
    RAG_MIN_SCORE: float = float(os.getenv("RAG_MIN_SCORE", "0.5"))
    ANALYSIS_CHUNK_TOKEN_LIMIT: int = int(os.getenv("ANALYSIS_CHUNK_TOKEN_LIMIT", "12000"))
    LEVER_API_BASE: str = os.getenv("LEVER_API_BASE", "https://api.lever.co/v0")
    LEVER_SITES: str = os.getenv("LEVER_SITES", "openai")
    LEVER_DEFAULT_LIMIT: int = int(os.getenv("LEVER_DEFAULT_LIMIT", "30"))
    NVIDIA_API_BASE: str = os.getenv("NVIDIA_API_BASE", "https://integrate.api.nvidia.com/v1")
    NVIDIA_CHAT_MODEL: str = os.getenv("NVIDIA_CHAT_MODEL", "meta/llama-3.1-70b-instruct")

    # Security and JWT
    SECRET_KEY: str = os.getenv("SECRET_KEY", "change-me-for-local-development")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days

    # Redis and Celery
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    # S3-compatible object storage. Defaults are for local MinIO development.
    AWS_ACCESS_KEY_ID: str = os.getenv("AWS_ACCESS_KEY_ID", "minioadmin")
    AWS_SECRET_ACCESS_KEY: str = os.getenv("AWS_SECRET_ACCESS_KEY", "minioadmin")
    AWS_REGION: str = os.getenv("AWS_REGION", "us-east-1")
    AWS_ENDPOINT_URL: str = os.getenv("AWS_ENDPOINT_URL", "http://localhost:9000")
    S3_BUCKET_NAME: str = os.getenv("S3_BUCKET_NAME", "interview-copilot-bucket")


settings = Settings()
