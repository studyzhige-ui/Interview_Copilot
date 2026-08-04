# Interview Copilot Community

Community is the GitHub self-hosted edition. It has two independent choices:

- **Launch topology:** host development or full containers.
- **Model profile:** lightweight remote, all-local, or a per-capability hybrid.

All combinations use `.env.community.example` and the same application code,
database schema, and `data/` layout.

## Host development mode

Use this mode to read, debug, test, or modify the source. Python, Celery, and
Vite run on the host; Docker Compose runs PostgreSQL, Redis, MinIO, and Milvus.

Requirements:

- Python 3.11–3.13 in an active virtual environment
- Node.js 20+
- Docker with Compose v2
- Enough RAM and disk for local models, or remote provider credentials

Run the one-time setup:

```powershell
pwsh ./scripts/setup.ps1
```

The setup asks for a Community model profile. For an unattended setup, pass
`-ModelProfile remote`, `-ModelProfile local-cpu`, or
`-ModelProfile local-cuda`. The earlier `-LocalModels` and `-Cuda` aliases
remain supported.

```bash
bash ./scripts/setup.sh
```

For an unattended setup, set `COMMUNITY_MODEL_PROFILE=remote`, `local-cpu`, or
`local-cuda`. The earlier `INSTALL_LOCAL_MODELS=1` and `INSTALL_CUDA=1` aliases
remain supported.

Choose Community when prompted. The setup script creates `.env` when needed,
installs the Community development dependencies, starts healthy infrastructure,
applies Alembic migrations, and runs `npm ci`.

For daily startup:

```powershell
.\scripts\start.ps1
```

```bash
bash ./scripts/start.sh
```

The launcher shows a concise status view by default while preserving complete
output under `data/logs`. Use `-VerboseLogs` on PowerShell or `--verbose-logs`
on Bash when diagnosing startup or runtime failures.

Open `http://localhost:5173`. Stop the foreground launcher with `Ctrl+C`; use
`scripts/stop.ps1` or `bash scripts/stop.sh` when you also want to stop the
Docker infrastructure.

## Full container mode

Use this mode to run the packaged Community stack without host Python, Celery,
or Node processes.

```bash
cp .env.community.example .env
```

Generate a strong `SECRET_KEY`, place it in `.env`, configure the internal LLM
credential and any optional providers, then start everything:

```bash
docker compose --profile full up -d --wait
```

The default image uses remote-provider dependencies and stays relatively
small. Set `APP_EXTRAS=local` for local CPU models or `APP_EXTRAS=local,cuda`
for NVIDIA before building.

Open `http://localhost`. This command waits for dependency health checks and
runs `alembic upgrade head` through the one-shot `migrate` service before the
API and workers start.

Useful operations:

```bash
docker compose --profile full ps
docker compose --profile full logs -f api worker-turns worker-pipeline
docker compose --profile full down
```

Application runtime data and model caches are mounted at `./data`; database,
Redis, MinIO, and Milvus state use named Docker volumes. `docker compose down`
preserves them. Adding `--volumes` permanently removes database and service
state and must only be used for an intentional reset.

Full Compose uses `AWS_ENDPOINT_URL=http://minio:9000` for server-side object
I/O and `S3_PUBLIC_ENDPOINT_URL=http://localhost:9000` for browser presigned
URLs. If users access the site through another hostname, set the public value
to the externally reachable MinIO/S3 origin before starting the stack.

## Model modes

The Community template defaults to SiliconFlow for embedding, reranking and
speech, plus lightweight local document parsers. Fill `SILICONFLOW_API_KEY`.
This keeps the standard install usable on ordinary computers.

Choosing a local setup profile starts the model wizard automatically. Run it
again whenever you want to change the selection:

```bash
python scripts/init_models.py
```

Choose the recommended complete bundle or a custom/hybrid profile. For each
local capability the wizard offers compatible model choices, accepts a custom
Hugging Face repository, updates `.env`, and downloads only the selection.
Embedding, reranker, speech, diarization, and Docling can be chosen separately.

For full containers, build the local extra first and run the same wizard in a
one-shot container before starting the stack:

```bash
APP_EXTRAS=local docker compose build api
docker compose run --rm api python scripts/init_models.py
docker compose --profile full up -d --wait
```

Automation never waits for a prompt: use `--non-interactive`, `--only ROLE`,
or `--dry-run`. All model weights live under `data/cache/models`; library
metadata and resumable state remain under `data/cache`. Local providers fail
with a clear download hint instead of silently writing into a user cache.

## Runtime files and growth

All application-managed files live under the ignored `data/` tree:

| Directory | Contents | Lifecycle |
| --- | --- | --- |
| `cache/` | Local model weights and Python bytecode | Rebuildable; never deleted automatically because downloads can be large |
| `logs/` | Host launcher logs and `metrics.jsonl` | Launcher logs older than 14 days are swept; metrics rotate at 50 MiB with one backup |
| `runtime/` | Celery Beat schedule and small process state | Reused and overwritten |
| `storage/` | Local fallback for user uploads when object storage is unavailable | Deleted with the owning business object/outbox job |
| `agent-results/` | Oversized tool results keyed by conversation | Deleted with the conversation; orphan directories are swept daily |
| `tmp/` | Document/audio downloads and parser conversions | Deleted after each operation; crash leftovers older than 24 hours are swept daily |
| `backups/`, `evaluation/`, `release/` | Explicit operator command output | Created only when the corresponding script is run |

PostgreSQL, Redis, MinIO, and Milvus data use named Docker volumes rather than
arbitrary source folders. `docker compose down` keeps them; `down --volumes`
deletes them. Cache cleanup is intentionally manual: stop application workers,
then remove only the unused model directory under `data/cache`.

Community can instead use supported remote embedding, reranking, parsing, and
transcription providers by changing the corresponding `*_PROVIDER` settings.
This reduces local hardware requirements. Product edition and model location
are independent.

End users choose the answer model in the application. The deployment-owned
`router` and `worker` roles share `INTERNAL_LLM_PROVIDER` and
`INTERNAL_LLM_MODEL` (default `deepseek/deepseek-v4-flash`) and use only the
operator's environment credential.

## Local capabilities

Community exposes advanced provider settings. stdio MCP is available only when
the deployment explicitly opts in:

```env
MCP_ALLOW_STDIO=true
```

This executes user-configured processes on the API or turns-worker host. Enable
it only for a trusted single-user or otherwise isolated deployment. Private
network MCP targets require the separate `MCP_ALLOW_PRIVATE_NETWORKS` opt-in.

## Upgrades

The `0.1` Community release starts from a new migration baseline. Databases
created by unpublished development revisions (`0001_baseline` through `0051`)
cannot be upgraded in place: back them up, recreate the PostgreSQL database,
and re-import any data you intentionally keep. Tagged public releases after
`0.1` will retain a continuous migration chain.

Before upgrading:

1. Back up PostgreSQL and object storage.
2. Pull the target tagged release.
3. Re-run the setup script in host development mode, or rebuild the full stack.
4. Let setup/the Compose `migrate` service apply `alembic upgrade head`.
5. Run the smoke test.

Embedding model or dimension changes require rebuilding the affected Milvus
collections with `python scripts/reingest_hybrid.py`.

The optional quality harness is documented in
[`evaluation/README.md`](../../evaluation/README.md). Its code and example
schema ship with Community; private corpora and generated reports do not.
