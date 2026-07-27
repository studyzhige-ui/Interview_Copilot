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
# Cloud development
python -m pip install -e ".[dev]"

# Community development
python -m pip install --extra-index-url https://download.pytorch.org/whl/cu129 -e ".[community,dev]"

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

Workers (run the three commands in separate terminals, or use the launcher):

```bash
celery -A app.worker.celery_app.celery_app worker --workdir backend --pool=solo --queues=default,pipeline,transcription
celery -A app.worker.celery_app.celery_app worker --workdir backend --pool=threads --concurrency=2 --queues=turns
celery -A app.worker.celery_app.celery_app beat --workdir backend
```

Frontend:

```bash
cd frontend
npm run dev
```

## First-use checklist

1. Register an account.
2. Select an answer model and configure its key if needed; the deployment
   supplies the internal router/worker model.
3. Upload a resume and job description.
4. Run a mock interview.
5. Add optional Skills and MCP servers.

For production, review [Cloud deployment](deployment/cloud.md). For local
operation and customization, review [Community deployment](deployment/community.md).
