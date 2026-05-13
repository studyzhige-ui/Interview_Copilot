import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.background_tasks import cancel_and_wait_all

# Set a default Hugging Face mirror without overriding the user's .env value.
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

from app.db.database import engine
import app.models.agent_trace
import app.models.chat
import app.models.interview_qa  # Ensure models are registered before table creation.
import app.models.interview_record
import app.models.knowledge
import app.models.memory
import app.models.mock_interview_session
import app.models.resume_section
import app.models.upload
import app.models.user
from app.rag.embeddings import init_rag_settings
from app.rag.retriever import init_reranker
from app.services.memory.vector_service import memory_vector_service
from app.core.config import settings

# ─── Structured logging ──────────────────────────────────────────────────
_LOG_FORMAT = "%(asctime)s [%(name)s] %(levelname)s %(message)s"
_LOG_DATEFMT = "%Y-%m-%d %H:%M:%S"

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format=_LOG_FORMAT,
    datefmt=_LOG_DATEFMT,
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

    if settings.MEMORY_BACKFILL_ON_STARTUP:
        logger.info(">>> [3/5] Backfilling memory embeddings...")
        try:
            memory_vector_service.backfill_pending()
        except Exception as exc:  # noqa: BLE001
            logger.error("Memory embedding backfill degraded: %s", exc)
    else:
        logger.info(">>> [3/5] Memory embedding backfill disabled.")

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
    allow_methods=["*"],
    allow_headers=["*"],
)

from app.api import agent, auth, chat, interview, model_runtime, rag

app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(chat.router, prefix="/api/v1")
app.include_router(interview.router, prefix="/api/v1")
app.include_router(rag.router, prefix="/api/v1")
app.include_router(agent.router, prefix="/api/v1")
app.include_router(model_runtime.router, prefix="/api/v1")


@app.get("/ping")
async def ping():
    return {"status": "ok"}
