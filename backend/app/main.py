# ruff: noqa: E402
# ^ This entrypoint deliberately runs setup code (HF mirror default +
# the LangSmith monkey-patch via _setup_llm_tracing) BEFORE importing
# any llama_index-backed modules, so those imports cannot sit at the
# very top of the file. See the block comment by _setup_llm_tracing()
# below for why the ordering is load-bearing. Suppressing E402 file-wide
# is correct here rather than scattering ~25 inline noqa comments.
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.background_tasks import cancel_and_wait_all

# Set a default Hugging Face mirror without overriding the user's .env value.
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

# ─── LangSmith monkey-patch MUST happen before any module imports llama_index ───
# llama_index's ``llama_index.llms.openai.base`` does ``from openai import
# AsyncOpenAI`` at module-load time. That binding is FROZEN once the module
# is imported — subsequent monkey-patches on ``openai.AsyncOpenAI`` don't
# affect llama_index's local reference. So we must patch the openai module
# BEFORE the first import of llama_index transitively happens (which used
# to be triggered by ``from app.rag.embeddings import init_rag_settings``
# below). Without this ordering, chat-path traces silently vanish from
# LangSmith while Celery-side transcript traces still appear (because the
# Celery worker process patches before importing llama_index — see
# ``app/worker/celery_app.py::init_worker_models``).
from app.core.llm_tracing import setup_llm_tracing as _setup_llm_tracing
_setup_llm_tracing()

from app.db.database import engine
import app.models.chat
import app.models.document_chunk
import app.models.habit_doc
import app.models.interview_qa  # Ensure models are registered before table creation.
import app.models.interview_record
import app.models.knowledge
import app.models.knowledge_doc
import app.models.memory_audit_log
import app.models.mock_interview_runtime
import app.models.mock_interview_session
import app.models.file_asset
import app.models.outbox_job
import app.models.resume
import app.models.resume_section
import app.models.strategy_doc
import app.models.upload
import app.models.user
from app.rag.embeddings import init_rag_settings
from app.rag.retriever import init_reranker
from app.core.config import settings

# ─── Structured logging ──────────────────────────────────────────────────
# The ``%(request_id)s`` field is populated by
# ``RequestIdFormatter`` (see ``app.core.request_id``) from a
# contextvar set by the middleware below. Outside a request the
# default ``"-"`` keeps the column aligned.
_LOG_FORMAT = "%(asctime)s [req=%(request_id)s] [%(name)s] %(levelname)s %(message)s"
_LOG_DATEFMT = "%Y-%m-%d %H:%M:%S"

from app.core.request_id import RequestIdFormatter, new_request_id, set_request_id  # noqa: E402

# ``logging.basicConfig`` writes a default Formatter; replace the
# handler's formatter with our request-id-aware variant so every log
# line — including the third-party ones we keep — carries the
# correlation column.
_root_handler = logging.StreamHandler()
_root_handler.setFormatter(RequestIdFormatter(_LOG_FORMAT, _LOG_DATEFMT))
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    handlers=[_root_handler],
    force=True,
)
# Quiet noisy third-party loggers
for _quiet in ("httpx", "httpcore", "urllib3", "openai", "milvus"):
    logging.getLogger(_quiet).setLevel(logging.WARNING)

logger = logging.getLogger("interview.copilot.main")
PROJECT_ROOT = Path(__file__).resolve().parents[2]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize shared resources once during the FastAPI lifecycle."""
    logger.info("====== Interview Copilot startup sequence begins ======")

    # LangSmith tracing was already activated at module top — before any
    # llama_index / openai import. Calling it again here is idempotent and
    # ensures the startup banner appears once when the lifespan starts.
    _setup_llm_tracing()

    logger.info(">>> [1/5] Verifying database schema migration state...")
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    if "alembic_version" not in inspector.get_table_names():
        raise RuntimeError(
            "Database is not migrated. Run `alembic upgrade head` before starting the API."
        )
    with engine.connect() as connection:
        current_version = connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
    script = ScriptDirectory.from_config(Config(str(PROJECT_ROOT / "alembic.ini")))
    head_version = script.get_current_head()
    if current_version != head_version:
        raise RuntimeError(
            f"Database migration is out of date ({current_version} != {head_version}). "
            "Run `alembic upgrade head` before starting the API."
        )

    logger.info(">>> [2/5] Initializing LlamaIndex LLM and embedding settings...")
    init_rag_settings()

    # v3 memory is markdown docs, not Milvus vectors — no startup
    # backfill needed. (The retired v2 ``memory_items`` path used a
    # ``MEMORY_BACKFILL_ON_STARTUP`` setting + a ``memory_vector_service``
    # priming step here; both were removed in the audit cleanup.)
    logger.info(">>> [3/5] (v3 memory needs no startup backfill — skipping)")

    logger.info(">>> [4/5] Initializing reranker...")
    init_reranker()

    logger.info(">>> [5/5] Whisper and diarization models are loaded by Celery workers.")
    logger.info("====== Interview Copilot startup sequence complete ======")
    yield

    logger.info("Draining background tasks before shutdown...")
    await cancel_and_wait_all(timeout=10.0)
    logger.info("====== Interview Copilot shutdown sequence complete ======")


app = FastAPI(
    title="Interview Copilot API",
    description="Agent + RAG Backend for Interview Copilot",
    version="1.0.0",
    lifespan=lifespan,
)

# ─── Reverse-proxy headers (must come BEFORE rate-limit / lockout reads) ─
# When ``TRUSTED_PROXIES`` is set, ProxyHeadersMiddleware reads the
# X-Forwarded-For header from the trusted proxy and rewrites
# ``request.client.host`` to the real client IP. Without this, every
# request behind nginx/ALB looks like it came from the proxy IP —
# slowapi's per-IP key_func and verification_code_service's IP-lockout
# both degrade to a single global counter, and one attacker burns the
# quota for everyone.
#
# Default empty = dev direct-connect, no rewrite — same behaviour as
# before. Must be configured in prod for the rate-limit P0 to actually
# bite.
_trusted_proxies = [
    p.strip()
    for p in settings.TRUSTED_PROXIES.split(",")
    if p.strip()
]
if _trusted_proxies:
    from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
    # trusted_hosts accepts a list or comma-string; we pass the parsed
    # list so a typo in TRUSTED_PROXIES surfaces at startup, not later.
    app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=_trusted_proxies)
    logger.info(
        "ProxyHeadersMiddleware enabled (trusted_hosts=%s) — request.client.host "
        "will be rewritten from X-Forwarded-For",
        _trusted_proxies,
    )

# CORS Configuration — read allowed origins from settings (comma-separated).
_cors_origins = [
    origin.strip()
    for origin in settings.CORS_ORIGINS.split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    # Explicit allowlist instead of "*" so credentialed cross-origin requests
    # can't be coerced into arbitrary verbs from an attacker-controlled origin
    # that happens to be in CORS_ORIGINS by accident.
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Requested-With"],
    expose_headers=["X-Request-ID"],
    max_age=600,
)


# ─── Local-fallback static files (avatars only) ──────────────────────────
# When S3 / MinIO is unreachable an avatar upload falls back to writing the
# bytes under ``STORAGE_DIR/avatars/...`` (see storage_service.save_blob_to_local).
# Those files need to be browser-readable; we mount JUST the avatars/
# sub-tree as a public static route. Other STORAGE_DIR contents (resumes,
# JDs, knowledge documents) stay off-bus — they're private and only the
# backend should touch them.
from fastapi.staticfiles import StaticFiles  # noqa: E402

_avatar_local_dir = Path(settings.STORAGE_DIR) / "avatars"
_avatar_local_dir.mkdir(parents=True, exist_ok=True)
app.mount(
    "/api/v1/static/avatars",
    StaticFiles(directory=str(_avatar_local_dir)),
    name="local-avatars",
)


# ─── Catch-all exception logger ─────────────────────────────────────────
# FastAPI / Starlette swallows bare exceptions and returns a 500 body with
# no log line by default — meaning a NullPointerException or AttributeError
# in business code shows up only on the client side. Force a full traceback
# to the structured log so on-call has something to look at.
import traceback as _tb

from fastapi import Request as _Request
from fastapi.responses import JSONResponse as _JSONResponse


@app.exception_handler(Exception)
async def unhandled_exception_logger(request: _Request, exc: Exception):
    logging.getLogger("unhandled").error(
        "Unhandled %s on %s %s: %s\n%s",
        type(exc).__name__,
        request.method,
        request.url.path,
        exc,
        _tb.format_exc(),
    )
    # Explicitly attach X-Request-ID. Starlette's ServerErrorMiddleware
    # short-circuits past our middleware chain on exception, so the
    # ``request_id_middleware`` doesn't get to stamp the header on
    # the response. Stamping it here keeps client↔server correlation
    # working even on 500s — the user reporting a bug + the on-call
    # log line share one searchable token. ``get_request_id`` returns
    # the contextvar's current value (or "-" if somehow unset).
    from app.core.request_id import get_request_id
    return _JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
        headers={"X-Request-ID": get_request_id()},
    )


# ─── Request-ID middleware ──────────────────────────────────────────────
# Generate (or pick up) a correlation id per request and stuff it into
# the contextvar so every log line emitted between here and the
# response carries it. The id also rides back via ``X-Request-ID``
# (already in CORS's expose_headers) so a user reporting a bug can
# share it and we can grep one string to find every line for that
# request.
@app.middleware("http")
async def request_id_middleware(request, call_next):
    incoming = request.headers.get("x-request-id", "").strip()
    rid = incoming if incoming else new_request_id()
    set_request_id(rid)
    response = await call_next(request)
    response.headers["X-Request-ID"] = rid
    return response


# ─── Security response headers ───────────────────────────────────────────
# Baseline hardening headers applied to every response. HSTS is conditional —
# we only emit it when the request actually came in over HTTPS (or the
# X-Forwarded-Proto header from a TLS-terminating reverse proxy says so)
# so dev / curl-over-http traffic doesn't pin browsers to a wrong scheme.
@app.middleware("http")
async def add_security_headers(request, call_next):
    response = await call_next(request)
    headers = response.headers
    headers.setdefault("X-Frame-Options", "DENY")
    headers.setdefault("X-Content-Type-Options", "nosniff")
    headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(self), camera=()")
    fwd_proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    if fwd_proto == "https":
        headers.setdefault(
            "Strict-Transport-Security",
            "max-age=31536000; includeSubDomains",
        )
    return response

# ─── Rate limiting (Redis-backed slowapi) ────────────────────────────────
# Tiered per-endpoint limits live in app.core.rate_limit; this is just the
# wiring: register the limiter so decorators activate, and install the
# default 429 handler so quota breaches return a clean JSON response.
try:
    from slowapi import _rate_limit_exceeded_handler
    from slowapi.errors import RateLimitExceeded
    from slowapi.middleware import SlowAPIMiddleware

    from app.core.rate_limit import limiter as _rate_limiter

    app.state.limiter = _rate_limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)
except ImportError:
    logging.getLogger(__name__).warning(
        "slowapi not installed — rate limiting disabled. "
        "Run: pip install slowapi"
    )

from app.api import auth, chat, file_assets, interview, memory, model_runtime, rag, resumes

app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(chat.router, prefix="/api/v1")
app.include_router(file_assets.router, prefix="/api/v1")
app.include_router(interview.router, prefix="/api/v1")
app.include_router(memory.router, prefix="/api/v1")
app.include_router(rag.router, prefix="/api/v1")
app.include_router(model_runtime.router, prefix="/api/v1")
app.include_router(resumes.router, prefix="/api/v1")


@app.get("/ping")
async def ping():
    return {"status": "ok"}
