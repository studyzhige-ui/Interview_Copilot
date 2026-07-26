# Interview Copilot

Interview Copilot is an AI interview practice and review platform. It combines
mock interviews, recording analysis, resume/JD retrieval, long-term learning
memory, user Skills, and MCP tools.

The repository ships one shared product core in two editions:

- **Interview Copilot Cloud** — a hosted Web product. Users choose their LLM,
  Skills, remote MCP servers, and voice; the operator manages retrieval and
  speech infrastructure.
- **Interview Copilot Community** — the GitHub self-hosted edition. Developers
  can replace providers, run local models, use custom endpoints, and enable
  local stdio MCP.

[中文说明](docs/zh/README.md) · [Edition architecture](docs/architecture/editions.md)
· [2026-07 consolidation report](docs/reports/consolidation-2026-07-26.md)

## Core features

- Mock interviews grounded in a resume and job description
- Audio transcription, speaker-aware review, scoring, and skill radar
- Hybrid RAG with Milvus, reranking, citations, and document lifecycle support
- Per-user LLM credentials and role-based model selection
- Long-running agent turns with reconnectable event streams and cancellation
- User-scoped Skills, MCP servers, session permissions, and immutable turn tools
- PostgreSQL, Redis/Celery, Milvus, and S3-compatible object storage

## Quick start

Requirements: Python 3.11+, Node.js 20+, and Docker.

```powershell
pwsh ./scripts/setup.ps1
```

```bash
bash ./scripts/setup.sh
```

The setup script asks which edition to configure:

1. Community — full self-hosted controls and local-model defaults
2. Cloud — hosted product policy and managed API defaults

Then start the backend and frontend:

```bash
uvicorn app.main:app --app-dir backend --reload --port 8080
cd frontend
npm run dev
```

Open `http://localhost:5173`.

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

# Community development
python -m pip install --extra-index-url https://download.pytorch.org/whl/cu129 -e ".[community,dev]"
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

Database schema changes use Alembic:

```bash
alembic upgrade head
```

## Repository layout

```text
backend/app/       FastAPI application and agent runtime
backend/tests/     Backend test suite
frontend/src/      React application
alembic/           Database migrations
evaluation/        Optional RAG evaluation runners, tests, and dataset template
docs/deployment/   Edition-specific deployment guidance
docs/              Current architecture and operator documentation
scripts/           Setup, maintenance, and model initialization
pyproject.toml     Python dependencies, package metadata, and tool configuration
docker-compose.yml Community infrastructure and optional full local stack
```

## Security boundary

Cloud accepts remote Streamable HTTP MCP only and ignores stored custom provider
endpoints. Community can expose local processes only when the operator
explicitly enables `MCP_ALLOW_STDIO`. User credentials are encrypted at rest
and are never returned by read APIs.

Do not commit `.env`, production credentials, recordings, or user documents.
