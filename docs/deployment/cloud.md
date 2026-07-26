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

End users may configure LLM providers, personal API keys, model roles, Skills,
remote MCP servers, and voice. The operator owns embedding, reranking,
transcription, diarization, storage, queues, quotas, and monitoring.

Cloud rejects custom LLM endpoints and stdio MCP at the backend even if a client
forges the request.

## Required operator services

- PostgreSQL
- Redis and Celery workers
- Milvus
- S3-compatible object storage
- Managed or operator-hosted embedding and reranking
- Managed or operator-hosted transcription and diarization
- At least one default LLM provider for keyless onboarding

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
