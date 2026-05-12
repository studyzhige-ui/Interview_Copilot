# Interview Copilot

Interview Copilot is an AI-powered interview practice and analysis platform. It combines real-time voice mock interviews, interview recording analysis, RAG-based knowledge retrieval, resume-aware scoring, personal memory, and a modular Agent Harness for complex multi-step tasks.

## Architecture

The system uses a **dual-link architecture**:

- **Chat link**: conversational knowledge Q&A with RAG retrieval, routed by a query planner
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

## Prerequisites

- Python 3.12+
- Docker & Docker Compose (for Postgres, Redis, MinIO, Milvus)
- NVIDIA GPU with CUDA (recommended for Whisper and embeddings; CPU works but is slow)
- At least one LLM API key (DeepSeek recommended)

## Quick Start

### 1. Clone and create virtual environment

```powershell
git clone https://github.com/studyzhige-ui/Interview_Copilot.git
cd Interview_Copilot
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install --upgrade pip
pip install -r requirements.txt
```

### 2. Configure environment

```powershell
Copy-Item .env.example .env
Copy-Item .env.docker.example .env.docker
```

Open `.env` and configure:

#### Required: LLM API Key

You need at least **one** LLM provider. DeepSeek is the default:

```ini
# Get your key at: https://platform.deepseek.com/api_keys
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxx
```

#### Optional API Keys

| Service | Purpose | Get Key |
|---------|---------|---------|
| LlamaCloud | High-quality PDF/DOCX parsing | [cloud.llamaindex.ai](https://cloud.llamaindex.ai/api-key) |
| NVIDIA API | Additional LLM models | [build.nvidia.com](https://build.nvidia.com/) |
| Tavily | Agent web search tool | [tavily.com](https://tavily.com/) |

#### Local Model Selection

The system downloads several models locally for embedding, reranking, transcription, and speaker diarization. Default models are pre-configured, but you can change them in `.env`:

| Role | Default Model | Alternatives | Download Size |
|------|--------------|-------------|------|
| **Embedding** | `BAAI/bge-m3` (1024d) | `BAAI/bge-large-zh-v1.5` (620 MB), `BAAI/bge-small-en-v1.5` (64 MB) | 1.06 GB |
| **Reranker** | `BAAI/bge-reranker-base` | `BAAI/bge-reranker-large` (1.06 GB), `BAAI/bge-reranker-v2-m3` (1.08 GB) | 530 MB |
| **Whisper** | `Systran/faster-whisper-large-v2` | `Systran/faster-whisper-medium` (1.5 GB), `Systran/faster-whisper-small` (486 MB) | 3.09 GB |
| **Diarization** | `pyannote-community/speaker-diarization-community-1` | `pyannote/speaker-diarization-3.1` (needs HF token) | ~17 MB |

> **Note**: If you change `EMBEDDING_MODEL_ID`, you must also update `EMBEDDING_DIM` to match the model's output dimension.

See `.env.example` for the full list of options and detailed comments.

### 3. Download local models

```powershell
# Download all configured models (reads from .env)
python scripts/init_models.py

# Or download selectively
python scripts/init_models.py --only embedding
python scripts/init_models.py --only whisper

# Preview what will be downloaded
python scripts/init_models.py --dry-run

# Use official HuggingFace (if outside China)
python scripts/init_models.py --hf-endpoint https://huggingface.co
```

### 4. Start local infrastructure

```powershell
docker compose up -d
```

This starts Postgres, Redis, MinIO, Milvus, and Nginx. The API and Celery worker run on the host during development.

### 5. Run database migrations

```powershell
alembic upgrade head
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

## Interview Analysis Flow

The recording analysis pipeline requires:

| Input | Required | Supported Formats |
|-------|----------|-------------------|
| Audio/Video | ✅ Yes | mp3, wav, m4a, flac, ogg, wma, aac, mp4, mkv, avi, mov, webm |
| Resume | ✅ Yes | pdf, docx, txt, md |
| JD (Job Description) | Optional | Plain text |

The pipeline outputs a structured report with:
- Overall score, grade, and verdict
- Per-question analysis: original Q&A, score, critique, improved answer, tags
- Phase-level summaries (self-intro, project deep-dive, technical, behavioral)
- Skill radar chart data

## Useful Commands

```powershell
# Syntax check
python -m compileall -q backend/app backend/tests

# Run tests
pytest

# WebSocket debug
python scripts/test_ws.py <JWT_TOKEN> <SESSION_ID>

# Evaluation suite
python -m evaluation.eval_runner --all --report
```

## LLM Model Routing

The system uses role-based model routing with three roles:

| Role | Purpose | Default Model |
|------|---------|---------------|
| `primary` | Main chat and RAG responses | deepseek-v4-flash |
| `fast` | Internal tasks (routing, rewriting, annotation) | deepseek-v4-flash |
| `agent` | Tool-calling agent workflows | deepseek-v4-pro |

You can change model assignments at runtime from the frontend model panel, or by editing `data/runtime/model_selection.json`. The `agent` role requires a model that supports function calling.

## Data and Secrets

Runtime data is written under `data/` by default (model caches, uploads, vector stores, logs). These files are git-ignored and should not be committed.

The repository provides `.env.example` and `.env.docker.example` as templates only. Rotate any key that has ever been committed or shared. Production deployments must replace all local defaults and use a unique `SECRET_KEY`.
