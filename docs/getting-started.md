# Getting started

## Choose an edition

Use **Community** when you run the repository yourself or learn from the
implementation. **Cloud** is the hosted product policy and needs an
operator-managed production topology; the root Compose file is for Community.

The two supported local run modes below are alternatives. Do not run both from
the same checkout at the same time.

## Mode A: host development

Use this mode when changing or debugging the code. It requires Python
3.11–3.13, Node.js 20+, Docker Compose v2, and an active Python virtual
environment.

Run the one-time setup:

```powershell
pwsh ./scripts/setup.ps1
```

The script separately asks which Community model profile to use: lightweight
remote, local/hybrid CPU, or local/hybrid CUDA. For example, unattended CPU
setup uses `pwsh ./scripts/setup.ps1 -ModelProfile local-cpu`; accepted values
are `remote`, `local-cpu`, and `local-cuda`.

```bash
bash ./scripts/setup.sh
```

For example, unattended CPU setup uses
`COMMUNITY_MODEL_PROFILE=local-cpu bash ./scripts/setup.sh`; the same three
values are accepted.

Choose Community when prompted. The script creates `.env` when absent,
installs dependencies, generates a missing `SECRET_KEY`, starts the local
infrastructure, applies migrations, and installs frontend packages.

Start the development processes each day with:

```powershell
.\scripts\start.ps1
```

```bash
bash ./scripts/start.sh
```

The launcher runs Uvicorn, the configured Celery workload queues, Celery Beat,
and Vite in one console. Open `http://localhost:5173` and press `Ctrl+C` to stop
the host processes. The default console is concise; complete output is retained
under `data/logs`. Add `-VerboseLogs` on PowerShell or `--verbose-logs` on Bash
for live diagnostic output.

## Mode B: full container stack

Use this mode to run the packaged Community application. Copy the template and
set a strong secret before startup:

```bash
cp .env.community.example .env
python scripts/generate_secret.py
```

Paste the generated value into `.env` as `SECRET_KEY`, then configure the
deployment-owned internal LLM credential and any optional providers.

```bash
docker compose --profile full up -d --wait
```

Open `http://localhost`. The full profile starts the frontend, API, four Worker
classes, scheduler, PostgreSQL, Redis, MinIO, and Milvus. Its one-shot migrate
service applies the database schema before runtime services start.

Inspect or stop it with:

```bash
docker compose --profile full ps
docker compose --profile full logs -f api worker-turns
docker compose --profile full down
```

## Models

Community can use remote APIs, local models, or a per-capability hybrid. A
remote profile avoids multi-gigabyte downloads. A local setup profile installs
the local dependency extra and opens the model wizard automatically. Run it
again later to change the selection:

```bash
python scripts/init_models.py
```

The wizard can configure and download Embedding, Reranker, Whisper,
diarization, and Docling independently, including compatible custom Hugging
Face repositories. It writes the selected providers, model IDs, and embedding
dimension to `.env`. Use `--non-interactive`, `--only ROLE`, or `--dry-run` in
automation.

Model weights are kept together in `data/cache/models`; library metadata and
partial download state remain under `data/cache`. Both launch topologies use
that managed cache, and the full stack mounts `./data` into its containers.

Cloud defaults to operator-managed remote embedding, reranking, and speech
providers. Those credentials belong to the Cloud deployment and are not shown
in ordinary user settings.

## First-use checklist

1. Register an account and verify its email. If SMTP is intentionally disabled
   for local development, read the verification code from backend output.
2. Select an answer model and configure its key if needed; the deployment
   supplies the internal router/worker model.
3. Upload a resume and job description.
4. Run a mock interview and review the result.
5. Add optional Skills and MCP servers.
6. Confirm password reset from the login page before relying on the account.

See [Community deployment](deployment/community.md) for persistence, model,
upgrade, and MCP details. See [Cloud deployment](deployment/cloud.md) for the
hosted-product boundary, and [Codebase architecture](architecture/codebase.md)
before changing module ownership.
