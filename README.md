# Interview Copilot

Interview Copilot is a cloud-first career copilot. It combines job-search
tracking, mock interviews, recording analysis, resume/JD retrieval, durable
artifacts, user Skills, and MCP tools. Long-term Agent Memory remains behind
its evaluation gate; the current runtime does not produce or recall it.

The repository ships one shared product core in two editions:

- **Interview Copilot Cloud** — a hosted Web product. Users choose their answer
  LLM, Skills, remote MCP servers, and voice; the operator manages internal
  routing, background models, retrieval, and speech infrastructure.
- **Interview Copilot Community** — the GitHub self-hosted edition. Developers
  can replace providers, run local models, use custom endpoints, and enable
  local stdio MCP.

[中文说明](docs/zh/README.md) ·
[Documentation system](docs/README.md) ·
[Career Agent OS blueprint](docs/architecture/career-agent-os-blueprint.md) ·
[Architecture document status](docs/architecture/README.md) ·
[Edition architecture](docs/architecture/editions.md)
· [Codebase architecture](docs/architecture/codebase.md) ·
[Product and systems audit](docs/reports/full-product-and-systems-audit-2026-08-04.md)

## Refactor branch status

The `refactor/product-runtime-convergence` branch integrates the shared Copilot
workspace, invitation confirmation/preparation, text-first mock handoff, and
runtime/RAG correctness fixes. It is not a completed product release: the
[existing implementation ledger](docs/implementation/career-agent-os-ledger.md)
records implementation and fixed-commit evidence. The branch now also contains
real Celery/PostgreSQL recovery and Chromium campaigns, mock-answer generation
fences, explicit retry consent, bounded retrieval workers and fail-closed model
configuration. Use the current PR's checks, not an earlier green commit, as the
execution evidence. No historical user records are discarded to make migrations
pass. Live model quality, full-platform monetary accounting and memory release
remain separate gates.

## Core features

- Mock interviews grounded in a resume and job description
- Audio transcription, speaker-aware review, scoring, and skill radar
- Hybrid RAG with PostgreSQL/pgvector, reranking, citations, and document lifecycle support
- Per-user credentials and one answer-model preference shared by chat, Agent,
  and mock interview
- Long-running agent turns with reconnectable event streams and cancellation
- User-scoped Skills and MCP servers with concrete Tool discovery, execution records, and current policy controls
- PostgreSQL/pgvector, Redis/Celery, and S3-compatible object storage

## Quick start

Choose one run mode and do not mix them in the same checkout.

### Host development

Requirements: Python 3.11–3.13, Node.js 20+, Docker, and an active Python
virtual environment. The setup script installs dependencies, starts the local
infrastructure, applies migrations, and installs the frontend packages.

```powershell
pwsh ./scripts/setup.ps1
```

```bash
bash ./scripts/setup.sh
```

The setup script asks which edition to configure. Community then asks for a
model profile: lightweight remote, local/hybrid CPU, or local/hybrid CUDA. A
local profile opens a per-capability model wizard and stores the selection in
`.env`. Then use the matching daily launcher:

```powershell
.\scripts\start.ps1
```

```bash
bash ./scripts/start.sh
```

Open `http://localhost:5173`.

### Full container stack

Copy the Community template, set a generated `SECRET_KEY` and any provider
keys, then start the complete stack. Database migrations are built into this
path.

```bash
cp .env.community.example .env
docker compose --profile full up -d --wait
```

Open `http://localhost`. Runtime data and model caches are stored under
`data/`; PostgreSQL/pgvector, Redis, and MinIO use Docker volumes.

See [Community deployment](docs/deployment/community.md) or
[Cloud deployment](docs/deployment/cloud.md) for the complete contract.

## Configuration

Use one explicit edition template:

```bash
cp .env.community.example .env
# or
cp .env.cloud.example .env
```

`APP_EDITION` controls product permissions, not model location. A Community
deployment may use cloud APIs; a Cloud operator may host models on its own
servers. The edition decides what end users are allowed to configure.

## Development

Python dependencies have one source of truth in `pyproject.toml`:

```bash
# Cloud development
python -m pip install -e ".[dev]"

# Community development (lightweight remote-provider mode)
python -m pip install -e ".[dev]"

# Optional local embedding, parsing, reranking and speech stack
python -m pip install -e ".[local,dev]"

# Optional NVIDIA CUDA runtime
python -m pip install --extra-index-url https://download.pytorch.org/whl/cu129 -e ".[local,cuda,dev]"

# Optional quality evaluation
python -m pip install -e ".[evaluation]"
```

```bash
python -m pytest -q
ruff format --check backend/app backend/tests evaluation scripts
ruff check backend/app backend/tests evaluation scripts
cd frontend
npm run typecheck
npm run lint
npm run test:run
npm run build
```

Release validation must not compete with locally running model services for
GPU memory. Run broad backend groups serially with CUDA hidden, or use the
cross-stage runner, which enforces that policy for its child processes and
terminates a timed-out child before continuing:

```powershell
$env:CUDA_VISIBLE_DEVICES = "-1"
$env:TOKENIZERS_PARALLELISM = "false"
python evaluation/career_scenario_eval.py
```

```bash
CUDA_VISIBLE_DEVICES=-1 TOKENIZERS_PARALLELISM=false \
  python evaluation/career_scenario_eval.py
```

Do not launch overlapping full-suite `pytest` commands in the same checkout.
Protocol-faithful provider tests do not require a GPU.

Database schema changes use Alembic:

```bash
alembic upgrade head
```

## Repository layout

```text
backend/app/       FastAPI application, domain services, and agent runtime
backend/tests/     Backend test suite
frontend/src/      React application
alembic/           Database migrations
evaluation/        Reproducible RAG/interview datasets, runners, and quality gates
docs/              Product, experience, architecture, delivery, and user documentation
scripts/           Setup, launch, maintenance, and model utilities
pyproject.toml     Python dependencies, package metadata, and tool configuration
docker-compose.yml Community infrastructure and full local stack
```

See [Codebase architecture](docs/architecture/codebase.md) for module ownership
and dependency direction.

## Security boundary

Cloud accepts remote Streamable HTTP MCP only and ignores stored custom provider
endpoints. Community can expose local processes only when the operator
explicitly enables `MCP_ALLOW_STDIO`. User credentials are encrypted at rest
and are never returned by read APIs.

Do not commit `.env`, production credentials, recordings, or user documents.
