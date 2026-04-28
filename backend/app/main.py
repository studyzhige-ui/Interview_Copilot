import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Set a default Hugging Face mirror without overriding the user's .env value.
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

from app.db.database import Base, engine
import app.models.agent_trace
import app.models.chat
import app.models.interview  # Ensure models are registered before table creation.
import app.models.interview_state
import app.models.memory
import app.models.user
from app.rag.embeddings import init_rag_settings
from app.rag.retriever import init_reranker

logger = logging.getLogger("interview.copilot.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize shared resources once during the FastAPI lifecycle."""
    logger.info("====== Interview Copilot startup sequence begins ======")

    logger.info(">>> [1/4] Verifying database schema...")
    Base.metadata.create_all(bind=engine)

    logger.info(">>> [2/4] Initializing LlamaIndex LLM and embedding settings...")
    init_rag_settings()

    logger.info(">>> [3/4] Initializing reranker...")
    init_reranker()

    logger.info(">>> [4/4] Whisper and diarization models are loaded by Celery workers.")
    logger.info("====== Interview Copilot startup sequence complete ======")
    yield

    logger.info("====== Interview Copilot shutdown sequence complete ======")


app = FastAPI(
    title="Interview Copilot API",
    description="Agent + RAG Backend for Interview Copilot",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from app.api import agent, auth, chat, interview, model_runtime, rag_api

app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(chat.router, prefix="/api/v1")
app.include_router(interview.router, prefix="/api/v1")
app.include_router(rag_api.router, prefix="/api/v1")
app.include_router(agent.router, prefix="/api/v1")
app.include_router(model_runtime.router, prefix="/api/v1")


@app.get("/ping")
async def ping():
    return {"status": "ok"}
