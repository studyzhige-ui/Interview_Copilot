# Getting started

## Choose an edition

Use **Community** when you are running the repository yourself or learning from
the implementation. Use **Cloud** when you are deploying the hosted Web product
for end users.

```bash
cp .env.community.example .env
# or
cp .env.cloud.example .env
```

Generate `SECRET_KEY` before the first start:

```bash
python scripts/generate_secret.py
```

Paste the generated value into `.env`.

## Install and initialize

The setup scripts install dependencies, start local infrastructure, and run
database migrations:

```powershell
pwsh ./scripts/setup.ps1
```

```bash
bash ./scripts/setup.sh
```

Manual equivalent:

```bash
python -m pip install -r requirements-dev.txt
docker compose up -d
alembic upgrade head
cd frontend && npm ci
```

## Model setup

Cloud defaults to remote embedding, reranking, and transcription providers.
Fill the operator keys in `.env`; end users never see them.

Community defaults to local BGE and WhisperX models. Download them once:

```bash
python scripts/init_models.py
```

You may instead switch the Community `*_PROVIDER` settings to cloud APIs. Model
location and product edition are independent.

## Run

Backend:

```bash
uvicorn app.main:app --app-dir backend --reload --port 8080
```

Worker:

```bash
celery -A app.worker.celery_app.celery_app worker --workdir backend --pool=solo
```

Frontend:

```bash
cd frontend
npm run dev
```

## First-use checklist

1. Register an account.
2. Configure at least one LLM provider or use an operator-provided default.
3. Upload a resume and job description.
4. Run a mock interview.
5. Add optional Skills and MCP servers.

For production, review [Cloud deployment](deployment/cloud.md). For local
operation and customization, review [Community deployment](deployment/community.md).
