# Interview Copilot

Interview Copilot is an AI-powered interview practice and analysis platform. It combines real-time voice mock interviews, interview recording analysis, RAG-based knowledge retrieval, resume-aware scoring, personal memory, and a modular Agent Harness for complex multi-step tasks.

## Architecture

The system uses a dual-link architecture:

- **Traditional RAG link**: deterministic knowledge Q&A routed by a query planner
- **Agent link**: user-initiated, tool-calling execution engine with web search, file I/O, memory management, and structured event streaming

Interview recording analysis uses a **three-stage MapReduce pipeline**:

1. **Stage 1**: Deterministic QA extraction from WhisperX transcript (zero fidelity loss) + LLM metadata annotation (phase tagging, follow-up chain detection)
2. **Stage 2**: Per-question parallel deep analysis with 3-question sliding context window, injecting resume and JD context
3. **Stage 3**: Global synthesis report with per-question scores, phase summaries, and skill radar

## Stack

- **API**: FastAPI + SQLAlchemy, Postgres for persistence, LlamaIndex Docstore
- **Async Jobs**: Redis + Celery for transcription, analysis, and document ingestion
- **Storage**: MinIO (S3-compatible) for audio, resume, and document uploads
- **Vector Search**: Milvus with BGE-M3 embeddings + BM25 hybrid retrieval
- **LLM**: DeepSeek / OpenAI-compatible clients via LlamaIndex and OpenAI SDK
- **Audio**: WhisperX + Pyannote for transcription and speaker diarization
- **Web Search**: Tavily API (optional, requires `TAVILY_API_KEY`)

## Repository Layout

```text
backend/
  app/                  FastAPI app, services, models, RAG, agent runtime
  tests/                Unit and API tests
  Dockerfile            Production multi-stage Docker image
alembic/                Database migrations (Alembic)
evaluation/             RAG, generation, and agent evaluation harness
scripts/                Developer utilities (model init, dev server, etc.)
docs/                   Project documentation
nginx/                  Local reverse proxy configuration
.github/workflows/      CI pipeline (lint + test)
```

## Local Setup

### 1. Create a virtual environment

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Linux/macOS:

```bash
python -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 2. Configure environment

```powershell
Copy-Item .env.example .env
Copy-Item .env.docker.example .env.docker
```

Set at least `DEEPSEEK_API_KEY` in `.env`. Optional providers (LlamaCloud, NVIDIA, Tavily) can stay as placeholders. Never commit `.env` or `.env.docker`.

Default model routing uses `deepseek-v4-flash` for chat/fast tasks and `deepseek-v4-pro` for agent workflows. Local retrieval defaults to `BAAI/bge-m3` embeddings and `BAAI/bge-reranker-base`.

### 3. Start local infrastructure

```powershell
docker compose up -d
```

This runs Postgres, Redis, MinIO, Milvus, and Nginx. The API and Celery worker run on the host during development.

### 4. Run database migrations

```powershell
alembic upgrade head
```

### 5. (Optional) Pre-download local models

```powershell
python scripts/init_models.py
```

### 6. Start the API server

```powershell
cd backend
uvicorn app.main:app --reload --port 8080
```

Open http://127.0.0.1:8080/docs for Swagger UI, or http://127.0.0.1/docs through Nginx.

### 7. Start the Celery worker

```powershell
cd backend
celery -A app.worker.celery_app.celery_app worker --loglevel=info --pool=solo
```

On Linux/macOS, omit `--pool=solo` if your environment supports the default prefork pool.

## Useful Commands

```powershell
# Syntax check
python -m compileall -q backend/app backend/tests

# Run tests
pytest backend/tests

# WebSocket debug
python scripts/test_ws.py <JWT_TOKEN> <SESSION_ID>

# Evaluation suite
python -m evaluation.eval_runner --all --report
```

## Interview Analysis Flow

The recording analysis pipeline requires:

| Input | Required | Format |
|-------|----------|--------|
| Audio/Video | ✅ Yes | mp3, wav, m4a, flac, ogg, wma, aac, mp4, mkv, avi, mov, webm |
| Resume | ✅ Yes | pdf, docx, txt, md |
| JD (Job Description) | Optional | Plain text |

The pipeline outputs a structured report with:
- Overall score, grade, and verdict
- Per-question analysis: original Q&A, score, critique, improved answer, tags
- Phase-level summaries (self-intro, project deep-dive, technical, behavioral)
- Skill radar chart data

## Data and Secrets

Runtime data is written under `data/` by default (model caches, uploads, vector stores, logs). These files are git-ignored and should not be committed.

The repository provides `.env.example` and `.env.docker.example` as templates only. Rotate any key that has ever been committed or shared. Production deployments must replace all local defaults and use a unique `SECRET_KEY`.
