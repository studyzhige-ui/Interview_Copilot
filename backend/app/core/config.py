import logging
import os
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import field_validator, model_validator
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
    APP_EDITION: Literal["cloud", "community"] = "community"
    DATABASE_URL: str = (
        "postgresql://postgres:postgres@localhost:5432/interview_copilot"
    )
    LLAMA_CLOUD_API_KEY: str = ""

    # Runtime data paths
    APP_DATA_DIR: str = _default_app_data_dir()

    # Database and vector-store data
    MILVUS_URI: str = "http://localhost:19530"
    MILVUS_COLLECTION: str = "interview_copilot_rag"
    MILVUS_SIMILARITY_METRIC: str = "IP"
    MILVUS_DENSE_INDEX_TYPE: str = "HNSW"
    MILVUS_HNSW_M: int = 16
    MILVUS_HNSW_EF_CONSTRUCTION: int = 200
    MILVUS_HNSW_EF_SEARCH: int = 64
    # MEMORY-V3 ability-state hybrid collection — a SEPARATE Milvus collection
    # from the knowledge RAG one, populated via outbox index jobs and queried
    # for topic-relevant ability states (parallel to, but distinct from,
    # knowledge retrieval).
    MEMORY_ABILITY_MILVUS_COLLECTION: str = "interview_copilot_memory_ability"
    MEMORY_ABILITY_TOP_K: int = 5

    # Hugging Face, model, and framework caches
    CACHE_DIR: str = ""

    # Logs and telemetry
    LOG_DIR: str = ""
    LOG_LEVEL: str = "INFO"

    # Local upload backups and object-storage staging
    STORAGE_DIR: str = ""

    # One device choice for the local RAG stack (Docling, embedding, reranker).
    # Every component supports CPU; ``auto`` uses CUDA when available.
    RAG_DEVICE: str = "auto"
    # ── Model selection: provider + free-form model name ───────────────────
    # Two axes per role:
    #   *_PROVIDER  — picks an entry from the small PROVIDERS dict in the
    #                 corresponding registry module (5-10 stable choices).
    #   *_MODEL     — any model name that provider exposes. Adding new model
    #                 variants needs ZERO code change; just edit this var.
    # See docs/providers.md for recommended combinations.
    #
    # ⚠ EMBEDDING_DIM must match the model's actual output dimension.
    #   Switching to a different-dim model after data is indexed requires
    #   dropping the Milvus collection and re-ingesting.

    # Platform-owned internal LLM. End users cannot select this model or
    # supply its credential; both latency-sensitive routing and background
    # model work use the deployment's provider key.
    INTERNAL_LLM_PROVIDER: str = "deepseek"
    INTERNAL_LLM_MODEL: str = "deepseek-v4-flash"

    # Embedding (RAG vector store)
    EMBEDDING_PROVIDER: str = (
        "siliconflow"  # local | openai | siliconflow | jina | dashscope | zhipu
    )
    EMBEDDING_MODEL: str = "BAAI/bge-m3"
    EMBEDDING_DIM: int = 1024

    # Reranker (RAG cross-encoder)
    RERANKER_PROVIDER: str = "siliconflow"
    RERANKER_MODEL: str = "BAAI/bge-reranker-v2-m3"
    # Shared ingestion/retrieval policy. Defaults remain benchmark inputs until
    # the CPU/GPU ablation selects the release profile.
    RAG_CHUNK_TOKENS: int = 384
    RAG_CHUNK_OVERLAP: int = 64
    RAG_RERANK_INPUT_TOKENS: int = 512
    RAG_QUERY_TOKEN_RESERVE: int = 96

    # ASR (audio transcription)
    TRANSCRIPTION_PROVIDER: str = "siliconflow"
    TRANSCRIPTION_MODEL: str = "FunAudioLLM/SenseVoiceSmall"

    # Speaker diarization (separates "who said what"). Three modes:
    #   "auto"     — bundled when TRANSCRIPTION_PROVIDER=local_whisperx;
    #                off otherwise.
    #   "pyannote" — force local Pyannote even when ASR is remote (hybrid:
    #                remote ASR returns word timestamps → Pyannote labels
    #                speakers → we align). Needs the ~1GB Pyannote download
    #                AND a remote ASR provider that supports word-level
    #                timestamps (e.g. openai/whisper-1).
    #   "none"     — never diarize; transcripts come back single-speaker.
    DIARIZATION_MODE: str = "none"
    # Interview diarization speaker bounds. 1:1 interviews are the norm
    # (2/2); bump MAX for panel interviews. Hardcoding 2 forced every
    # 3-speaker recording to merge two voices into one.
    DIARIZATION_MIN_SPEAKERS: int = 2
    DIARIZATION_MAX_SPEAKERS: int = 2
    DIARIZATION_MODEL_ID: str = "pyannote-community/speaker-diarization-community-1"
    # Usage is observed per turn but does not determine task completion.
    # Cancellation, context limits, request/tool timeouts, and the worker
    # lifecycle provide the operational safety boundary.
    AGENT_TOOL_TIMEOUT_SECONDS: int = 30
    AGENT_TEMPERATURE: float = 0.2
    AGENT_MAX_RESPONSE_TOKENS: int = 4096
    AGENT_TOOL_SCHEMA_STRICT: bool = True
    AGENT_MAX_TOOL_ARG_CHARS: int = 4000
    LLM_REQUEST_TIMEOUT_SECONDS: int = 60
    TURN_HEARTBEAT_SECONDS: int = 10
    TURN_STALE_SECONDS: int = 60
    # Stage A — tool-result offload thresholds.
    AGENT_PERSIST_THRESHOLD: int = 50_000  # per-result: offload if > 50K chars
    AGENT_TURN_BUDGET_CHARS: int = (
        200_000  # per-turn aggregate: spill largest until < 200K
    )
    AGENT_PERSIST_PREVIEW_SIZE: int = (
        2_000  # preview size (chars) in persisted-output block
    )
    # User-managed MCP servers. stdio is disabled by default because it executes
    # a user-supplied command in the API process; private HTTP targets are opt-in
    # for trusted local/single-tenant deployments.
    MCP_ALLOW_STDIO: bool = False
    MCP_ALLOW_PRIVATE_NETWORKS: bool = False
    MCP_RUNTIME_IDLE_SECONDS: int = 600
    RAG_CANDIDATE_COUNT: int = 20
    RAG_FINAL_COUNT: int = 3
    RAG_MAX_INTENTS: int = 4
    # Reranker-score relevance threshold — reranker branch ONLY. Calibrated
    # for the default BAAI/bge-reranker-v2-m3 sigmoid score on the versioned
    # official-doc benchmark; other reranker models must be calibrated on
    # their own score distribution rather than inheriting this number. A
    # reranker transport failure fails closed because RRF scores use an
    # incompatible scale and cannot safely inherit this threshold.
    RAG_MIN_SCORE: float = 0.87
    # Single-intent evidence must also stay close to the best result. This
    # removes topically related tail chunks without suppressing independent
    # legs of an explicitly decomposed multi-intent query.
    RAG_SCORE_MARGIN: float | None = 0.01
    # Community defaults to local structured parsing. LlamaParse remains an
    # explicit optional primary; format-specific lightweight parsers are the
    # final fallback.
    PARSER_PROVIDER: str = "docling"
    # On-demand OCR for the Docling parser (plan §4.1.3/§4.1.4): scanned PDFs
    # (pages with no text layer) and image documents. Effective only when an OCR
    # engine (rapidocr-onnxruntime) is importable — if it isn't, Docling is built
    # with do_ocr=False so text PDFs still parse instead of failing on a missing
    # engine. Set False to disable OCR globally even where the engine is present.
    RAG_OCR_ENABLED: bool = True
    # Memory v2 settings (MEMORY_MILVUS_COLLECTION / MEMORY_*_TOP_K /
    # MEMORY_BACKFILL_ON_STARTUP) were removed in the audit cleanup —
    # the v3 memory architecture uses markdown docs, not vectors. See
    # ``app/services/memory/__init__.py`` for the live entry points.
    RESUME_MILVUS_COLLECTION: str = "interview_copilot_resume"
    TTS_DEFAULT_VOICE: str = "zh-CN-YunxiNeural"
    LEVER_API_BASE: str = "https://api.lever.co/v0"
    LEVER_SITES: str = "openai"

    # ── Deployment environment ──────────────────────────────────────────
    # Drives production-safety validation (see _validate_production_safety):
    # "staging" / "prod" / "production" turn a placeholder SECRET_KEY into a
    # fatal startup error and enable other prod-only checks. Default "local"
    # keeps dev convenient.
    ENVIRONMENT: str = "local"  # "local" / "staging" / "prod"

    # Security and JWT.
    # No in-code default — keys must come from .env (or environment). An empty
    # value is caught by _validate_secret_key() below and logged loudly so the
    # operator notices instead of silently inheriting a placeholder.
    SECRET_KEY: str = ""
    # Comma-separated list of OLD secrets retained during a key-rotation grace
    # period. Encrypted user_model_credentials ciphertexts encrypted under any of these
    # can still be decrypted (MultiFernet); new writes always use SECRET_KEY.
    # Move keys here when rotating, then drop them once all stored payloads
    # have been lazily re-encrypted (or after a hard cutoff).
    SECRET_KEYS_OLD: str = ""
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days

    # CORS — comma-separated origins, default allows local Vite dev server.
    CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173"

    # Reverse-proxy trust list (comma-separated IPs/hosts; "*" trusts all).
    # When non-empty, ProxyHeadersMiddleware rewrites ``request.client.host``
    # from the X-Forwarded-For header sent by trusted proxies. **Without
    # this set in prod, every per-IP rate-limit and login-lockout counter
    # collapses to a single global counter keyed by the nginx/ALB IP —
    # one attacker burns the quota for everyone.**
    # Default empty = dev direct-connect, no rewrite, ``request.client.host``
    # is the real socket peer. Set to e.g. ``"127.0.0.1"`` (nginx on same
    # host) or your ALB CIDR in prod.
    TRUSTED_PROXIES: str = ""

    # Redis and Celery
    REDIS_URL: str = "redis://localhost:6379/0"

    # SMTP — email verification codes. Leave SMTP_HOST empty to log codes to stdout
    # (dev fallback). Set all four to enable real email delivery.
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = "Interview Copilot <noreply@interview-copilot.local>"
    SMTP_USE_TLS: bool = True
    EMAIL_CODE_TTL_SECONDS: int = 600  # 10 minutes
    EMAIL_CODE_RESEND_COOLDOWN: int = 60  # min seconds between resend

    # S3-compatible object storage. Defaults are for local MinIO development.
    AWS_ACCESS_KEY_ID: str = "minioadmin"
    AWS_SECRET_ACCESS_KEY: str = "minioadmin"
    AWS_REGION: str = "us-east-1"
    AWS_ENDPOINT_URL: str = "http://localhost:9000"
    # Browser-facing endpoint used only to sign presigned URLs. Containers use
    # AWS_ENDPOINT_URL=http://minio:9000 for server I/O while browsers need a
    # host/public address such as http://localhost:9000.
    S3_PUBLIC_ENDPOINT_URL: str = ""
    S3_BUCKET_NAME: str = "interview-copilot-bucket"

    # Database connection pool — PER-WORKER limits.
    #
    # Hard math when running multi-worker:
    #
    #     uvicorn_workers * (DB_POOL_SIZE + DB_MAX_OVERFLOW)
    #     + celery_concurrency
    #     + headroom (replication / vacuum / psql)
    #     <= postgresql.conf max_connections
    #
    # Default Postgres `max_connections` is 100. With these values
    # (20 + 20 = 40 per process) you can safely run 2 uvicorn workers
    # plus a few Celery slots; for 4+ workers either bump
    # max_connections to 300+ or run pgbouncer in front.
    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_RECYCLE: int = 1800  # seconds

    # Redis connection pool — shared across verification codes, celery
    # broker/result, rate limiter, and ad-hoc app cache. Same per-worker
    # multiplication applies; Redis default maxclients is 10000 so this is
    # rarely the bottleneck.
    REDIS_POOL_SIZE: int = 50

    @field_validator(
        "CACHE_DIR",
        "LOG_DIR",
        "STORAGE_DIR",
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
            "CACHE_DIR": "cache",
            "LOG_DIR": "logs",
            "STORAGE_DIR": "storage",
        }
        subdir = field_to_subdir.get(info.field_name, info.field_name.lower())
        return str(Path(app_data) / subdir)

    @model_validator(mode="after")
    def _validate_rag_policy(self) -> "Settings":
        if self.RAG_DEVICE not in {"auto", "cpu", "cuda"}:
            raise ValueError("RAG_DEVICE must be auto, cpu, or cuda")
        if self.RAG_CHUNK_TOKENS <= self.RAG_CHUNK_OVERLAP:
            raise ValueError("RAG_CHUNK_TOKENS must exceed RAG_CHUNK_OVERLAP")
        if self.RAG_QUERY_TOKEN_RESERVE >= self.RAG_RERANK_INPUT_TOKENS:
            raise ValueError(
                "RAG_QUERY_TOKEN_RESERVE must be below RAG_RERANK_INPUT_TOKENS"
            )
        if self.RAG_CHUNK_TOKENS > (
            self.RAG_RERANK_INPUT_TOKENS - self.RAG_QUERY_TOKEN_RESERVE
        ):
            raise ValueError("RAG_CHUNK_TOKENS exceeds the reranker passage budget")
        return self


_INSECURE_SECRET_KEYS = {
    "change-me-for-local-development",
    "super-secret-key-for-interview-copilot-dev",
    "your-secret-key",
    "",
}


def _validate_production_safety(s: "Settings") -> None:
    """Audit settings for known-insecure defaults.

    Behaviour by ``ENVIRONMENT``:
      * ``local`` (default) — single INFO line listing bundled creds still
        in use. Dev convenience wins; SECRET_KEY still gets a WARNING
        because a placeholder key breaks JWT/Fernet even on localhost.
      * ``staging`` / ``prod`` / ``production`` — a placeholder
        ``SECRET_KEY`` is a **fatal startup error**. Refusing to boot is
        the only safe response: a known-default key lets anyone with
        access to the source code forge tokens and decrypt every stored
        user-API-key ciphertext. Other bundled creds (Postgres / MinIO)
        downgrade to ERROR-level logs — they're recoverable by network
        isolation, but SECRET_KEY isn't.

    Generate a real SECRET_KEY with::

        python scripts/generate_secret.py

    Then drop the printed value into ``.env`` as ``SECRET_KEY=...``.
    """
    is_prodlike = (s.ENVIRONMENT or "local").strip().lower() in {
        "staging",
        "prod",
        "production",
    }
    findings: list[tuple[str, str]] = []
    secret_finding: tuple[str, str] | None = None

    if (s.SECRET_KEY or "").strip() in _INSECURE_SECRET_KEYS:
        secret_finding = (
            "SECRET_KEY",
            "Generate one with: python scripts/generate_secret.py "
            '(or python -c "import secrets; print(secrets.token_urlsafe(48))")',
        )

    # Bundled-Postgres / MinIO well-known credentials. These are baked into
    # docker-compose's defaults; rotating them in production prevents anyone
    # who reads the public README from logging into your DB / object store.
    if "postgres:postgres@" in (s.DATABASE_URL or ""):
        findings.append(
            (
                "DATABASE_URL still uses bundled postgres/postgres",
                "Set POSTGRES_USER/POSTGRES_PASSWORD and DATABASE_URL in .env"
                " to matching non-default values.",
            )
        )
    if (s.AWS_ACCESS_KEY_ID or "").strip() == "minioadmin":
        findings.append(
            (
                "AWS_ACCESS_KEY_ID is bundled 'minioadmin'",
                "Rotate AWS_ACCESS_KEY_ID in .env; Docker Compose uses it for MinIO.",
            )
        )
    if (s.AWS_SECRET_ACCESS_KEY or "").strip() == "minioadmin":
        findings.append(
            (
                "AWS_SECRET_ACCESS_KEY is bundled 'minioadmin'",
                "Rotate AWS_SECRET_ACCESS_KEY in .env; Docker Compose uses it for MinIO.",
            )
        )

    # Prod-only: with TRUSTED_PROXIES empty, every request's
    # ``request.client.host`` collapses to the proxy IP (nginx / ALB)
    # so slowapi's per-IP rate-limit and the verification-code
    # IP-lockout both degrade to a single global counter — one
    # attacker can burn the 5/minute auth quota for the entire
    # deployment. Skipped in dev because direct-connect doesn't need
    # the rewrite.
    if is_prodlike and not (s.TRUSTED_PROXIES or "").strip():
        findings.append(
            (
                "TRUSTED_PROXIES is empty in production",
                "Set to the nginx/ALB IP(s) (e.g. '127.0.0.1' for same-host "
                "nginx) so ProxyHeadersMiddleware can rewrite client.host "
                "from X-Forwarded-For. Without it, per-IP rate-limit and "
                "login-lockout share one global counter.",
            )
        )

    # ── SECRET_KEY: hard stop in production, WARN elsewhere ─────────────
    if secret_finding is not None:
        name, hint = secret_finding
        if is_prodlike:
            # Refuse to start. Letting a prod process boot with a
            # default SECRET_KEY would let anyone with the source forge
            # JWTs and read every Fernet-encrypted user API key.
            raise RuntimeError(
                f"[FATAL] {name} is set to an insecure default in "
                f"production ({s.ENVIRONMENT!r}). Refusing to "
                f"start. {hint}"
            )
        logger.warning(
            "[security] %s is set to an insecure default. %s",
            name,
            hint,
        )

    if not findings:
        return

    if is_prodlike:
        # DB / MinIO defaults: ERROR level so the operator sees red in
        # the startup log, but don't refuse to start — those creds are
        # recoverable by network isolation and rotation, unlike
        # SECRET_KEY which is cryptographically catastrophic.
        for name, hint in findings:
            logger.error(
                "[PRODUCTION BLOCKER] Insecure default: %s. Hint: %s",
                name,
                hint,
            )
    else:
        items = "; ".join(name for name, _ in findings)
        logger.info(
            "[security] Using bundled dev credentials (%s). "
            "Safe for local-only; rotate before any non-local deploy.",
            items,
        )


settings = Settings()
_validate_production_safety(settings)
