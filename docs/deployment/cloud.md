# Interview Copilot Cloud

Cloud is the hosted Web product. Start from:

```bash
cp .env.cloud.example .env
```

The Cloud backend image uses the lean core dependency set by default:

```bash
docker build -f backend/Dockerfile .
```

## Product contract

End users may configure answer-model providers, personal API keys, one answer
model, Skills, remote MCP servers, and voice. The operator owns the internal
router/worker model, embedding, reranking, transcription, diarization, storage,
queues, quotas, and monitoring.

Cloud rejects custom LLM endpoints and stdio MCP at the backend even if a client
forges the request.

## Required operator services

- PostgreSQL
- Redis and isolated Celery workers for turns, pipelines, voice, and control jobs
- Milvus
- S3-compatible object storage
- Managed or operator-hosted embedding and reranking
- Managed or operator-hosted transcription and diarization
- A deployment `DEEPSEEK_API_KEY` for the internal
  `deepseek-v4-flash` router/worker
- At least one answer-model provider for keyless onboarding, if offered

Use managed database and object-storage services in production where possible.
The root Docker Compose file is the Community development stack, not a complete
production Cloud topology.

## Release gates

- `ENVIRONMENT=production` and a generated `SECRET_KEY`
- TLS and an explicit `CORS_ORIGINS`
- Correct `TRUSTED_PROXIES`
- Rotated database and object-storage credentials
- Database backup and restore test
- Alembic migration check
- Per-user quotas and provider cost monitoring
- Error/request-id collection
- Data retention, export, and deletion policy
- Smoke test with no user API key and with a user-provided key

Do not expose operator model keys to the frontend. User keys remain encrypted in
the backend credential store.

## Operations

The API exposes process and dependency probes:

- `GET /api/v1/health/live` — process liveness only
- `GET /api/v1/health/ready` — PostgreSQL and Redis readiness; returns 503 on
  failure

Every response carries `X-Request-ID`; backend logs carry the same ID. Collect
stdout/stderr centrally and alert on readiness failures, HTTP 5xx, dead Outbox
jobs, stale turns and queue age. Enable LangSmith for LLM latency, token usage
and trace-level diagnosis. User-facing rate limits are keyed by verified JWT
subject; anonymous/auth traffic falls back to client IP.

Answer-model cost belongs to the user's provider key when BYOK is active.
Platform cost is the internal DeepSeek router/worker plus managed RAG and speech
providers. Monitor provider invoices and token traces; set provider-side hard
budgets as the final circuit breaker. Do not hard-code mutable vendor prices in
application code.

Create a PostgreSQL backup, optionally including S3 objects:

```bash
python scripts/backup.py create --output /secure/backups --include-objects
```

Restore only into a pre-created target database, then rebuild Milvus from the
PostgreSQL chunk source of truth:

```bash
python scripts/backup.py restore /secure/backups/<timestamp> \
  --target-database-url postgresql://.../restore_target --restore-objects
python scripts/reingest_hybrid.py
```

Run the non-destructive release drills and deployed smoke flow:

```bash
python scripts/resilience_drill.py
python scripts/smoke_test.py --base-url https://host \
  --username "$SMOKE_USER" --password "$SMOKE_PASSWORD"
```

The repository automates encryption, tenant isolation, secret masking, backup
and technical deletion constraints. A public Cloud launch still requires the
operator to choose and publish retention periods, legal basis, data-export and
account-deletion service levels, subprocessors and incident contacts; these are
business/legal decisions and must not be invented by code.
