import logging
import os
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import Field, SecretStr, field_validator, model_validator
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
    CLOUD_PARSE_TIER: Literal["fast", "cost_effective", "agentic", "agentic_plus"] = (
        "cost_effective"
    )
    CLOUD_PARSE_VERSION: str = Field("latest", min_length=1, max_length=80)
    CLOUD_PARSE_MAX_PAGES: int = Field(500, ge=1, le=10000)
    CLOUD_PARSE_MAX_INPUT_BYTES: int = Field(
        50 * 1024 * 1024, ge=1, le=500 * 1024 * 1024
    )
    CLOUD_PARSE_MAX_OUTPUT_BYTES: int = Field(20_000_000, ge=1, le=100_000_000)
    CLOUD_PARSE_DEADLINE_SECONDS: float = Field(300.0, gt=0, le=3600)

    # Runtime data paths
    APP_DATA_DIR: str = _default_app_data_dir()

    # One PostgreSQL store; all new indexes use pgvector and scoped BM25.
    RAG_SIMILARITY_METRIC: Literal["IP", "COSINE", "L2"] = "IP"
    RAG_INDEX_NAMESPACE: str = "interview_copilot_rag"
    RAG_INDEX_STATEMENT_TIMEOUT_MS: int = Field(5000, ge=100, le=60000)
    RAG_INDEX_LOCK_TIMEOUT_MS: int = Field(3000, ge=100, le=60000)
    RAG_INDEX_MAX_DOCUMENT_CHUNKS: int = Field(10000, ge=1, le=100000)
    # Hugging Face, model, and framework caches
    CACHE_DIR: str = ""
    # Optional read-only weights shared from a Windows data drive into WSL.
    # Framework metadata/locks remain under writable CACHE_DIR.
    MODEL_ROOT_DIR: str = ""
    MODEL_REVISIONS_JSON: dict[str, str] = Field(default_factory=dict)
    LOCAL_MODELS_OFFLINE: bool = False
    AUXILIARY_MODEL_POLICY: Literal["configured", "local_only"] = "configured"

    # One local inference broker; API/worker never load local RAG weights.
    LOCAL_INFERENCE_SOCKET: str = ""
    LOCAL_INFERENCE_TIMEOUT_SECONDS: float = Field(120, gt=0, le=600)
    LOCAL_EMBED_MAX_TOKENS: int = Field(8192, ge=1, le=32768)
    LOCAL_EMBED_QUERY_PREFIX: str = Field("", max_length=2048)
    LOCAL_EMBED_TEXT_PREFIX: str = Field("", max_length=2048)

    # Logs and telemetry
    LOG_DIR: str = ""
    LOG_LEVEL: str = "INFO"

    # Local upload backups and object-storage staging
    STORAGE_DIR: str = ""

    # Parser device policy. RAG weights use the independently configured broker;
    # its device is explicit and never initializes CUDA in this process.
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
    #   building a new generation from the retained source facts.

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
    TRANSCRIPTION_PROVIDER: str = "local_whisperx"
    TRANSCRIPTION_MODEL: str = "deepdml/faster-whisper-large-v3-turbo-ct2"
    TRANSCRIPTION_ALIGNMENT_MODEL: str = (
        "jonatasgrosman/wav2vec2-large-xlsr-53-chinese-zh-cn"
    )

    # Speaker diarization (separates "who said what"). Three modes:
    #   "auto"     — bundled when TRANSCRIPTION_PROVIDER=local_whisperx;
    #                off otherwise.
    #   "pyannote" — force local Pyannote even when ASR is remote (hybrid:
    #                remote ASR returns word timestamps → Pyannote labels
    #                speakers → we align). Needs the ~1GB Pyannote download
    #                AND a remote ASR provider that supports word-level
    #                timestamps (e.g. openai/whisper-1).
    #   "none"     — never diarize; transcripts come back single-speaker.
    DIARIZATION_MODE: str = "auto"
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
    # Transport cap, not an authorization to give every tool a larger payload.
    # Only a trusted built-in definition may opt into a larger decoded budget.
    AGENT_MAX_TOOL_WIRE_ARG_CHARS: int = 640_000
    LLM_REQUEST_TIMEOUT_SECONDS: int = 60
    # UTC-day account-wide dispatch/token limits. Historical names are retained
    # for deployment compatibility; all model, speech and tool meters share the
    # ledger. Money uses exact frozen operator rates, never guessed prices.
    MODEL_DAILY_CALL_LIMIT: int = Field(default=500, ge=1, le=1_000_000)
    MODEL_DAILY_TOKEN_LIMIT: int = Field(default=2_000_000, ge=1, le=2_000_000_000)
    # Global consumption envelope. Missing prices are visible as unpriced; a
    # monetary ceiling rejects unpriced work rather than treating it as free.
    USAGE_CURRENCY: str = Field(default="USD", pattern=r"^[A-Z]{3}$")
    USAGE_DAILY_COST_LIMIT_MICROS: int | None = Field(default=None, ge=1, le=10**12)
    USAGE_RATE_CARD_JSON: str = "{}"
    USAGE_DAILY_UNITS_JSON: str = '{"audio_ms":14400000,"characters":2000000,"documents":50000,"pages":5000,"bytes":1073741824,"external_requests":2000,"tool_invocations":1000}'
    USAGE_AUDIO_MAX_BYTES: int = Field(500 * 1024 * 1024, ge=1, le=2**31 - 1)
    USAGE_AUDIO_MAX_MS: int = Field(3_600_000, ge=1, le=86_400_000)
    USAGE_AUDIO_PROBE_SECONDS: float = Field(30.0, gt=0, le=300)
    USAGE_TTS_MAX_BYTES: int = Field(10_000_000, ge=1, le=100_000_000)
    USAGE_MAX_UNRESOLVED: int = Field(default=100, ge=1, le=100000)
    MODEL_STREAM_DEADLINE_SECONDS: float = Field(default=180, gt=0, le=3600)
    MODEL_STREAM_MAX_BYTES: int = Field(default=2_000_000, ge=1024, le=50_000_000)
    # Anthropic native Messages prompt caching. Disabling it changes only
    # latency/cost; the adapter still sends the complete semantic request.
    ANTHROPIC_PROMPT_CACHE_ENABLED: bool = True
    ANTHROPIC_PROMPT_CACHE_TTL: str = "5m"
    TURN_HEARTBEAT_SECONDS: int = 10
    TURN_RECOVERY_BATCH_SIZE: int = Field(default=100, ge=1, le=1000)
    TURN_RECOVERY_MAX_ATTEMPTS: int = Field(default=3, ge=0, le=10)
    TURN_STALE_SECONDS: int = 60
    # Delay before the single automatic Memory producer rechecks that a
    # completed source Turn's Conversation is idle. Contribution remains
    # opt-in and the task is a no-op when controls or source state changed.
    AGENT_MEMORY_IDLE_SECONDS: int = 600
    # Release gate: turn on only after the versioned Stage 5 owner/privacy/
    # deletion/relevance evaluation passes. User controls cannot bypass it.
    AGENT_MEMORY_PRODUCER_ENABLED: bool = False
    AGENT_MEMORY_SCAN_LIMIT: int = 100
    AGENT_MEMORY_MAX_INPUTS: int = 40
    AGENT_MEMORY_MAX_AGE_DAYS: int = 90
    AGENT_MEMORY_MAX_UNUSED_DAYS: int = 60
    AGENT_MEMORY_LEASE_SECONDS: int = 300
    AGENT_MEMORY_MODEL_TIMEOUT_SECONDS: int = 120
    AGENT_MEMORY_RECALL_TIMEOUT_SECONDS: int = 12
    AGENT_MEMORY_CONSOLIDATION_INPUT_TOKENS: int = 16000
    # Model-visible Tool-result projection thresholds. The canonical redacted
    # result remains on AgentToolCall and is paged by exact call identity.
    AGENT_RESULT_INLINE_THRESHOLD: int = 50_000
    AGENT_TURN_BUDGET_CHARS: int = (
        200_000  # per-turn aggregate: project largest until < 200K
    )
    AGENT_RESULT_PREVIEW_SIZE: int = (
        2_000  # preview size (chars) in canonical Tool-result reference
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
    RAG_DENSE_WEIGHT: float = 1.0
    RAG_SPARSE_WEIGHT: float = 1.0
    RAG_RRF_K: int = 60
    RAG_SEARCH_TIMEOUT_SECONDS: float = 8.0
    RAG_RERANK_TIMEOUT_SECONDS: float = 30.0
    # Per-process bounds. Queue permits survive cancellation of the async waiter.
    # Reranker defaults to one worker: model instances need not be thread-safe.
    RAG_STORAGE_WORKERS: int = Field(default=4, ge=1, le=32)
    RAG_STORAGE_QUEUE: int = Field(default=8, ge=0, le=128)
    RAG_SEARCH_WORKERS: int = Field(default=4, ge=1, le=32)
    RAG_SEARCH_QUEUE: int = Field(default=16, ge=0, le=128)
    RAG_EMBEDDING_WORKERS: int = Field(default=2, ge=1, le=16)
    RAG_EMBEDDING_QUEUE: int = Field(default=8, ge=0, le=128)
    RAG_RERANK_WORKERS: int = Field(default=1, ge=1, le=8)
    RAG_RERANK_QUEUE: int = Field(default=8, ge=0, le=128)
    RAG_OUTPUT_TOKEN_RESERVE: int = 4_096
    CONTEXT_TOOL_OUTPUT_TOKENS: int = 10_000
    CONTEXT_AUTO_COMPACT_TOKEN_LIMIT: int = 0
    CONTEXT_AUTO_COMPACT_SCOPE: Literal["total", "body_after_prefix"] = "total"
    RAG_CONTEXT_SAFETY_MARGIN: int = 1_024
    RAG_RETRIEVED_CONTEXT_TOKENS: int = 8_000
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
    # engine (rapidocr) is importable — if it isn't, Docling is built
    # with do_ocr=False so text PDFs still parse instead of failing on a missing
    # engine. Set False to disable OCR globally even where the engine is present.
    RAG_OCR_ENABLED: bool = True
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

    # Gmail's first real cloud Connector.  The adapter is callable only when
    # all four OAuth/product-return values and SECRET_KEY are configured.
    # Partial settings fail closed and never register a model-visible Tool.
    GMAIL_GOOGLE_OAUTH_CLIENT_ID: str = ""
    GMAIL_GOOGLE_OAUTH_CLIENT_SECRET: SecretStr = SecretStr("")
    GMAIL_GOOGLE_OAUTH_REDIRECT_URI: str = ""
    GMAIL_OAUTH_PRODUCT_RETURN_URI: str = ""
    # Gmail tokens never enter the application database. Community/local
    # deployments must explicitly configure this independent encrypted file
    # broker and recovery key. Cloud ignores the file setting and requires an
    # externally injected GmailCredentialStore implementation.
    GMAIL_CREDENTIAL_STORE_FILE: str = ""
    GMAIL_CREDENTIAL_STORE_KEY: SecretStr = SecretStr("")
    GMAIL_OAUTH_STATE_TTL_SECONDS: int = 600
    GMAIL_PROVIDER_TIMEOUT_SECONDS: float = 15.0

    # Marketplace-native Canva and Notion OAuth connectors. Both providers
    # share only the private credential-store port and product return page;
    # their identities, scopes and adapters remain provider-specific.
    PLUGIN_OAUTH_PRODUCT_RETURN_URI: str = ""
    PLUGIN_CREDENTIAL_STORE_FILE: str = ""
    PLUGIN_CREDENTIAL_STORE_KEY: SecretStr = SecretStr("")
    PLUGIN_OAUTH_STATE_TTL_SECONDS: int = 600
    PLUGIN_PROVIDER_TIMEOUT_SECONDS: float = 15.0
    CANVA_OAUTH_CLIENT_ID: str = ""
    CANVA_OAUTH_CLIENT_SECRET: SecretStr = SecretStr("")
    CANVA_OAUTH_REDIRECT_URI: str = ""
    NOTION_OAUTH_CLIENT_ID: str = ""
    NOTION_OAUTH_CLIENT_SECRET: SecretStr = SecretStr("")
    NOTION_OAUTH_REDIRECT_URI: str = ""

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

    @field_validator("USAGE_RATE_CARD_JSON")
    @classmethod
    def _usage_rates_valid(cls, value: str) -> str:
        from app.usage.pricing import rate_catalog

        rate_catalog(value)
        return value

    @field_validator("USAGE_DAILY_UNITS_JSON")
    @classmethod
    def _usage_limits_valid(cls, value: str) -> str:
        import json
        from app.usage.pricing import quantities

        limits = quantities(json.loads(value))
        if any(v <= 0 for v in limits.values()):
            raise ValueError("resource allowances must be positive")
        return value

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
        if self.EMBEDDING_DIM <= 0:
            raise ValueError("EMBEDDING_DIM must be positive")
        if (
            min(
                self.RAG_CANDIDATE_COUNT,
                self.RAG_FINAL_COUNT,
                self.RAG_MAX_INTENTS,
                self.RAG_RRF_K,
                self.RAG_OUTPUT_TOKEN_RESERVE,
                self.RAG_RETRIEVED_CONTEXT_TOKENS,
            )
            <= 0
        ):
            raise ValueError("RAG counts and token budgets must be positive")
        if self.RAG_CANDIDATE_COUNT < self.RAG_FINAL_COUNT:
            raise ValueError("RAG_CANDIDATE_COUNT must be >= RAG_FINAL_COUNT")
        if self.RAG_DENSE_WEIGHT <= 0 or self.RAG_SPARSE_WEIGHT <= 0:
            raise ValueError("RAG fusion weights must be positive")
        if self.RAG_SEARCH_TIMEOUT_SECONDS <= 0 or self.RAG_RERANK_TIMEOUT_SECONDS <= 0:
            raise ValueError("RAG stage timeouts must be positive")
        if self.RAG_CONTEXT_SAFETY_MARGIN < 0:
            raise ValueError("RAG_CONTEXT_SAFETY_MARGIN cannot be negative")
        if not 0 <= self.RAG_MIN_SCORE <= 1:
            raise ValueError("RAG_MIN_SCORE must be between 0 and 1")
        if self.RAG_SCORE_MARGIN is not None and not 0 <= self.RAG_SCORE_MARGIN <= 1:
            raise ValueError("RAG_SCORE_MARGIN must be between 0 and 1")
        if not 60 <= self.GMAIL_OAUTH_STATE_TTL_SECONDS <= 900:
            raise ValueError("GMAIL_OAUTH_STATE_TTL_SECONDS must be between 60 and 900")
        if not 1 <= self.GMAIL_PROVIDER_TIMEOUT_SECONDS <= 60:
            raise ValueError("GMAIL_PROVIDER_TIMEOUT_SECONDS must be between 1 and 60")
        if not 60 <= self.PLUGIN_OAUTH_STATE_TTL_SECONDS <= 900:
            raise ValueError(
                "PLUGIN_OAUTH_STATE_TTL_SECONDS must be between 60 and 900"
            )
        if not 1 <= self.PLUGIN_PROVIDER_TIMEOUT_SECONDS <= 60:
            raise ValueError("PLUGIN_PROVIDER_TIMEOUT_SECONDS must be between 1 and 60")
        if self.ANTHROPIC_PROMPT_CACHE_TTL not in {"5m", "1h"}:
            raise ValueError("ANTHROPIC_PROMPT_CACHE_TTL must be 5m or 1h")
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
# Apply before any optional HF/Transformers import. Download commands opt into a
# separate online setup process; changing policy in a running process is unsupported.
if settings.LOCAL_MODELS_OFFLINE or settings.AUXILIARY_MODEL_POLICY == "local_only":
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
_validate_production_safety(settings)
