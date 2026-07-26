# Interview Copilot Community

Community is the GitHub self-hosted edition:

```bash
cp .env.community.example .env
pwsh ./scripts/setup.ps1
```

Run the full container stack with:

```bash
docker compose --profile full up -d
```

## Model modes

The template uses local embedding, reranking, WhisperX, and Pyannote. Download
weights with:

```bash
python scripts/init_models.py
```

Every foundation role may instead use a supported remote provider by changing
the corresponding `*_PROVIDER` and `*_MODEL` values.

## Local capabilities

Community exposes advanced provider settings. stdio MCP is available only when
the deployment explicitly opts in:

```env
MCP_ALLOW_STDIO=true
```

This executes user-configured processes on the API host. Enable it only for a
trusted single-user or otherwise isolated deployment. Private-network MCP
targets require a separate explicit opt-in.

## Upgrades

Before upgrading:

1. back up PostgreSQL and object storage;
2. pull the target tagged release;
3. install dependencies or rebuild images;
4. run `alembic upgrade head`;
5. run the smoke tests.

Embedding model or dimension changes require reindexing the vector collections.

The optional RAG quality harness is documented in
[`evaluation/README.md`](../../evaluation/README.md). Its code and example
schema ship with Community; private evaluation corpora and generated reports do
not.
