# Interview Copilot

Interview Copilot is a FastAPI backend for interview practice and analysis. It combines authenticated chat, interview audio transcription, RAG retrieval, model routing, personal memory, and analytics.

## Stack

- FastAPI + SQLAlchemy for the API and persistence layer
- Postgres for application data and LlamaIndex docstore metadata
- Redis + Celery for background transcription and ingestion jobs
- MinIO for local S3-compatible upload storage
- Milvus for vector search
- DeepSeek/OpenAI-compatible model clients through LlamaIndex and OpenAI SDK
- Faster-Whisper/WhisperX and optional diarization models for audio processing

## Repository Layout

```text
backend/app/        FastAPI app, services, models, RAG, worker tasks
backend/tests/      Unit and API tests
evaluation/         RAG and agent evaluation scripts
scripts/            Developer utilities
nginx/              Local reverse proxy configuration
docs/               Project and interview documentation
frontend/           Vue 3 web workspace
```

## Local Setup

1. Create a virtual environment.

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
python -m pip install --upgrade pip
pip install -r requirements.txt
```

2. Create environment files.

```powershell
Copy-Item .env.example .env
Copy-Item .env.docker.example .env.docker
```

Set at least `DEEPSEEK_API_KEY` in `.env`. Optional providers such as LlamaCloud and NVIDIA can stay as placeholders until you use those code paths. Do not commit `.env` or `.env.docker`.

The default model routing uses `deepseek-v4-flash` for normal chat and fast internal tasks, and `deepseek-v4-pro` for agent/tool workflows. You can override runtime selections from the frontend model panel; persisted legacy DeepSeek selections fall back to these V4 defaults.

RAG search is strictly user-private. Uploaded knowledge documents, interview audio, memories, and retrieval metadata are all scoped by `current_user.username`; each user must upload their own documents before they can search them.

3. Start local infrastructure.

```powershell
docker compose down -v
docker compose up -d db redis minio minio-create-bucket milvus-etcd milvus-minio milvus-standalone nginx
```

This compose file intentionally runs infrastructure only. The API and worker run on the host during development. Ports are bound to `127.0.0.1` for local use. `docker compose down -v` resets local development data; omit it if you intentionally want to keep existing volumes.

4. Migrate the development database.

```powershell
alembic upgrade head
```

This project now uses Alembic for schema management. `Base.metadata.create_all()` and `schema_compat` are no longer part of the normal startup path.

5. Optionally pre-download local models.

```powershell
python scripts/init_models.py
```

6. Start the API.

```powershell
cd backend
uvicorn app.main:app --reload --port 8080
```

Open [http://127.0.0.1:8080/docs](http://127.0.0.1:8080/docs) for Swagger UI, or [http://127.0.0.1/docs](http://127.0.0.1/docs) through Nginx.

7. Start the Celery worker in another terminal.

```powershell
cd backend
celery -A app.worker.celery_app.celery_app worker --loglevel=info --pool=solo
```

On Linux/macOS you can omit `--pool=solo` if your environment supports the default worker pool.

8. Start the Vue frontend in another terminal.

```powershell
cd frontend
npm install
npm run dev
```

Open [http://127.0.0.1:5173](http://127.0.0.1:5173). Vite proxies `/api` requests to `http://127.0.0.1:8080`.

## Useful Commands

```powershell
python -m compileall -q backend/app backend/tests
pytest backend/tests
python scripts/test_ws.py <JWT_TOKEN> <SESSION_ID>
.\scripts\run_eval_profiles.ps1
```

## Data And Secrets

Runtime data is written under `data/` by default, including model caches, uploads, vector-store files, docstore JSON, logs, and evaluation outputs. These files are ignored by git and should not be committed.

The repository provides `.env.example` and `.env.docker.example` as templates only. Rotate any key that has ever been committed or shared. Production deployments should replace all local defaults, keep MinIO buckets private, restrict exposed ports, and use a non-default `SECRET_KEY`.
