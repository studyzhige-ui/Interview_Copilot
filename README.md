# Interview Copilot

<p align="center">
  <a href="./README.md"><img alt="English" src="https://img.shields.io/badge/Lang-English-3b82f6?style=for-the-badge"></a>
  <a href="./docs/zh/README.md"><img alt="简体中文" src="https://img.shields.io/badge/语言-%E7%AE%80%E4%BD%93%E4%B8%AD%E6%96%87-9ca3af?style=for-the-badge"></a>
</p>

> AI interview practice and analysis. Real-time voice mock interviews, recording
> analysis with WhisperX + Pyannote diarization, RAG over your resume and JD, and
> a tool-calling Agent — wired through a per-user model registry that works
> against any OpenAI-compatible provider (DeepSeek, OpenAI, Anthropic, Qwen,
> Moonshot, Zhipu, Xiaomi MiMo, NVIDIA Catalog, …).

📖 [Getting started](docs/getting-started.md) · 🛠 [Provider catalog](docs/providers.md) · 🩹 [Troubleshooting](docs/troubleshooting.md)

## Screenshots

<table>
  <tr>
    <td colspan="2" align="center"><sub><b>① Enter the app — sign in or register</b></sub></td>
  </tr>
  <tr>
    <td width="50%"><img src="docs/screenshots/login.png" alt="Sign in" /></td>
    <td width="50%"><img src="docs/screenshots/auth.png" alt="Registration with email verification" /></td>
  </tr>
  <tr>
    <td align="center"><sub>Sign-in — JWT access + refresh, jti revocation list in Redis</sub></td>
    <td align="center"><sub>Sign-up — email-verification flow (codes printed to backend stdout when SMTP isn't configured)</sub></td>
  </tr>
  <tr>
    <td colspan="2" align="center"><sub><b>② Set up — pick models, upload knowledge</b></sub></td>
  </tr>
  <tr>
    <td width="50%"><img src="docs/screenshots/models.png" alt="Models configuration page" /></td>
    <td width="50%"><img src="docs/screenshots/knowledge.png" alt="Knowledge library" /></td>
  </tr>
  <tr>
    <td align="center"><sub>Models — per-user routing across 9 providers (primary / agent / mock)</sub></td>
    <td align="center"><sub>Knowledge library — resume / interview question banks / official docs</sub></td>
  </tr>
  <tr>
    <td colspan="2" align="center"><sub><b>③ Run — mock interview or review a real recording</b></sub></td>
  </tr>
  <tr>
    <td width="50%"><img src="docs/screenshots/mock-interview.png" alt="Mock interview setup" /></td>
    <td width="50%"><img src="docs/screenshots/review.png" alt="Chat panel with interview record" /></td>
  </tr>
  <tr>
    <td align="center"><sub>Mock interview — resume + JD upload, four interviewer personas</sub></td>
    <td align="center"><sub>Review chat — per-record session list, model swap mid-conversation</sub></td>
  </tr>
</table>

---

## What's inside

| Module | Purpose |
|---|---|
| **Mock Interview** | Live voice interview against an LLM interviewer with TTS replies; configurable persona (friendly / professional / strict / pressure). |
| **Recording Analysis** | Upload a real recorded interview → WhisperX transcription → Pyannote diarization → 3-stage MapReduce LLM analysis (per-question scoring, phase summary, skill radar). |
| **Chat & Review** | Per-user dialogues backed by hybrid dense + BM25 retrieval over your resume / JD / docs, with cross-encoder rerank. |
| **Agent** | Tool-calling runtime with web search (Tavily), file IO, memory, structured event streaming. |
| **Per-user model routing** | Every user picks their own LLM per role (primary / fast / agent) from the Models page. 30+ profiles across 9 vendors out of the box; new ones added with a single config line. |

---

## Architecture

```mermaid
flowchart LR
    User([Browser]) -->|HTTPS / WSS| Front[Vite dev server<br/>or nginx prod<br/>:5173 / :80]
    Front -->|/api/v1/*| API[FastAPI uvicorn<br/>:8080]

    API --> Redis[(Redis<br/>broker · cache · JWT blacklist)]
    Redis --> Worker[Celery worker<br/>--pool=solo]

    subgraph Stateful[Stateful services]
        PG[(Postgres<br/>users · sessions · QA · uploads)]
        Milvus[(Milvus<br/>RAG · memory vectors)]
        MinIO[(MinIO / S3<br/>uploads · audio · avatars)]
    end

    API --> PG
    API --> Milvus
    API --> MinIO
    Worker --> PG
    Worker --> Milvus
    Worker --> MinIO

    API -->|chat / agent| LLM[Cloud LLM<br/>DeepSeek · OpenAI · Anthropic<br/>Qwen · Moonshot · Zhipu · ...]
    API -->|embed / rerank| Local[Local models<br/>bge-m3 · bge-reranker-v2-m3]
    Worker -->|transcribe| Whisper[WhisperX + Pyannote<br/>local or cloud]
```

LLM / embedding / reranker / ASR are dispatched through small **provider
registries**. The LLM catalog is sourced live from each vendor's official
`/v1/models` endpoint (no hardcoded list) — adding a new vendor is one
row in `providers.py` + one adapter spec under `model_sources/vendors/`.
New models appear automatically as the vendor ships them.

---

## Pick one path

### 🌐 Path A — API-light *(cloud everything; nothing downloads locally)*

Best for: trying the project end-to-end, no GPU, no big disk footprint.

You need **two** keys:

1. **An LLM provider** (DeepSeek recommended — cheapest starter).
2. **A combined embedding + reranker + ASR provider** (SiliconFlow
   recommended — one key for all three roles).

```bash
git clone https://github.com/<your-org>/Interview_Copilot.git
cd Interview_Copilot
conda create -n interview-copilot python=3.11 -y    # or 3.10 / 3.12 — NOT 3.13
conda activate interview-copilot

.\scripts\setup.ps1                                  # Windows  (Linux / macOS: ./scripts/setup.sh)
# answer "1" when asked: [1] API-light  [2] Local-models

# Open .env, paste both keys:
#   DEEPSEEK_API_KEY=sk-...
#   SILICONFLOW_API_KEY=sk-...

.\scripts\start.ps1 -SkipFrontend                    # tab 1
.\scripts\start.ps1 -SkipBackend                     # tab 2

# Open http://localhost:5173 → Register → verification code is printed
# to the backend terminal (no SMTP needed) → Login → Chat.
```

### 💻 Path B — Local-models *(embedding / reranker / ASR run on this machine)*

Best for: privacy, offline-capable deploys, you already have a GPU.

You only need **one** key (LLM still cloud):

```bash
# Steps 1-2 same as Path A, but answer "2" at the setup prompt.

# Open .env, paste just the LLM key:
#   DEEPSEEK_API_KEY=sk-...

python scripts/init_models.py --dry-run              # shows real-time sizes from HuggingFace
python scripts/init_models.py                        # ~5 GB total, supports byte-level resume

.\scripts\start.ps1 -SkipFrontend                    # tab 1
.\scripts\start.ps1 -SkipBackend                     # tab 2

# Register / login same as Path A. Try the recording-analysis flow —
# WhisperX + Pyannote run locally now.
```

→ **Full step-by-step walkthroughs (with expected outputs and gotchas):
[docs/getting-started.md](docs/getting-started.md)**

A third **Hybrid** mode (cloud ASR + local diarization) is a 2-line edit
on either path — see `docs/providers.md`.

---

## Repository layout

### `backend/app/` — FastAPI application

| Subpackage | Purpose |
|---|---|
| `api/` | Routers — auth, chat, interview, memory, model_runtime, rag |
| `schemas/` | Pydantic request / response models (one file per router) |
| `core/` | config, security, rate limiting, SSRF, request IDs, LLM tracing, HF runtime. Model registry was split into `model_catalog.py` + `user_model_selection.py` + `llm_client_factory.py` — `model_registry.py` survives as a 70-line back-compat shim |
| `db/` | SQLAlchemy engine, session factory, sync + async Redis clients |
| `models/` | ORM rows — `User`, `InterviewRecord`, `InterviewQA`, `KnowledgeDocument`, … |
| `rag/` | Embedding + reranker registries, hybrid retriever, ingestion, BM25 cache |
| `services/` | Business logic, grouped by domain — see the table below |
| `conversation/` | Chat engine + strategy split (L1 chat pipeline vs L2 ReAct loop) |
| `agent_runtime/` | Tool registry, ReAct loop, context compactor, event streaming |
| `worker/` | Celery app + tasks (analyze, ingest, refresh-catalog) |

### `backend/app/services/` — domain subpackages

| Subpackage | Files |
|---|---|
| `auth/` | email, token_blacklist, user_api_key, user_provider_settings, verification_code |
| `resume/` | resume_service, resume_vector_service |
| `knowledge/` | knowledge_service, document_chunk_service |
| `uploads/` | file_validation, upload_service |
| `analytics/` | diagnostics_report_service, telemetry_service |
| `interview/` | analysis_orchestrator, interview_record_service, mock_interview_service |
| `chat/` | session, runner, recall_policy, memory bundle |
| `memory/` | v3 long-term memory — doc-per-type, persisted in Postgres |
| `voice/` | WhisperX, Pyannote, TTS |
| `model_sources/` | Per-vendor `/v1/models` adapters + Redis catalog pipeline |

`storage_service.py` and `cache_service.py` live at the `services/` root — both are cross-domain (S3 wrapper, Redis-TTL cache) with importers across most subpackages.

### Top-level

- **`backend/tests/`** — ~500 tests across api / services / rag / models / core / db
- **`frontend/`** — React SPA (Vite + TS + Tailwind + zustand); nginx static configs under `public/`
- **`alembic/versions/`** — DB migrations (squashed to a single baseline + a few incremental adds)
- **`nginx/conf.d/`** — Reverse-proxy configs (dev + production)
- **`scripts/`** — setup / start / stop / init_models / refresh_models / wipe_non_admin / migrate_avatars
- **`docs/`** — getting-started · providers · postgres-tuning · troubleshooting · deploy-cloudflare-pages (each with a `zh/` mirror)
- **`.github/workflows/`** — CI (backend tests, ruff, frontend build)

---

## Documentation

| Topic | English | 中文 |
|---|---|---|
| Quick start, end-to-end | [getting-started.md](docs/getting-started.md) | [zh/getting-started.md](docs/zh/getting-started.md) |
| Provider catalog (LLM / embed / rerank / ASR) | [providers.md](docs/providers.md) | [zh/providers.md](docs/zh/providers.md) |
| Postgres tuning at scale | [postgres-tuning.md](docs/postgres-tuning.md) | [zh/postgres-tuning.md](docs/zh/postgres-tuning.md) |
| Troubleshooting | [troubleshooting.md](docs/troubleshooting.md) | [zh/troubleshooting.md](docs/zh/troubleshooting.md) |
| Deploy the frontend on Cloudflare Pages *(advanced / optional)* | [deploy-cloudflare-pages.md](docs/deploy-cloudflare-pages.md) | [zh/deploy-cloudflare-pages.md](docs/zh/deploy-cloudflare-pages.md) |

The Cloudflare doc is **optional**. Local dev needs nothing of the sort —
`docker compose up` + `npm run dev` is enough. You only reach for it if
you want a public hostname with free SSL/CDN for the SPA.

---

## Tech stack

- **API**: FastAPI 0.135, SQLAlchemy 2, Pydantic v2, slowapi (rate limit)
- **Background**: Celery 5 + Redis (queue / cache / blacklist)
- **Storage**: PostgreSQL 15, Milvus 2.5 (vector), MinIO (S3-compat)
- **AI**: LlamaIndex, BGE-M3 + BGE-Reranker-v2-m3, WhisperX, Pyannote
- **LLM**: Any OpenAI-compatible API (DeepSeek default)
- **Frontend**: React 18, Vite 5, Tailwind, zustand, react-virtual
- **Infra**: Docker Compose, nginx
- **Observability**: LangSmith (LLM traces — opt-in)

---

## License

MIT.
