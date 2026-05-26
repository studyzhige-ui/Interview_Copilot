# Troubleshooting

Common breakages, sorted by **where in the startup sequence** they tend to surface.

If a section doesn't fix your problem, search for the exact error
message in `git log`-friendly format: most production-affecting bugs
have a commit message that mentions the symptom.

---

## Python env / Windows shell

### `pwsh scripts/start.ps1` reports base Python despite `(env)` prompt

You activated a conda env in the parent shell, but the script still
sees base Python with the wrong package versions.

Root cause: `pwsh script.ps1` (with the explicit `pwsh` prefix) spawns
a **child** PowerShell process. The child loads your `$PROFILE`, whose
conda init hook can reset PATH back to base. So even though the parent
prompt shows `(your-env)`, the child runs with base activated.

**Fix:** drop the `pwsh` prefix and run with `.\` instead, which
executes in the current shell:

```powershell
.\scripts\start.ps1 -SkipFrontend
```

If the script is blocked by ExecutionPolicy, allow signed user scripts
once:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned -Force
```

### `conda activate <env>` doesn't actually switch Python

You created the env with `conda create -n NAME` *without* a `python=X.Y`
clause. Conda made a metadata-only env with no Python binary. Activating
it falls back to base Python silently.

**Fix:** rebuild the env including the Python version pin:

```powershell
conda env remove -n <env> -y
conda create -n <env> python=3.11 -y
conda activate <env>
python -c "import sys; print(sys.executable)"   # must include envs/<env>/
pip install -r requirements.txt
```

### Python 3.13: `pip install -r requirements.txt` fails on whisperx / pyannote

These two ML libraries don't have wheels for 3.13 yet. Use 3.10, 3.11, or
3.12. The setup script refuses 3.13 explicitly with this hint.

---

## Install / pip

### `torchcodec` symbol-missing on Windows

```
DLL load failed: aoti_torch_aten_narrow not found
```

**Fix**:
```bash
pip uninstall torchcodec
```
Pyannote falls back to `torchaudio`, which works fine.

### `slowapi` not installed

Backend logs `SENTRY_DSN is set but ...` or `slowapi not installed`.

**Fix**:
```bash
pip install slowapi==0.1.9
```
(It's in `requirements.txt` since Phase 1 — only an issue if your venv is stale.)

---

## Docker / infra

### Postgres "connection refused"

```
psycopg2.OperationalError: connection to server at "localhost" (::1), port 5432 failed
```

**Check**:
```bash
docker compose ps                     # is `postgres` healthy?
docker compose logs db | tail -30     # any error?
```

Most common cause: a stale local Postgres outside Docker is hogging
port 5432. Either stop it or change `docker-compose.yml`'s host port to
`127.0.0.1:5433:5432` and update `DATABASE_URL` accordingly.

### Milvus "service is not ready"

Milvus takes 30–60 s to become healthy after `docker compose up -d`.
Wait or:
```bash
docker compose ps milvus-standalone   # wait until "(healthy)"
```

If it stays unhealthy, check `milvus-etcd` and `milvus-minio` are also
healthy. Milvus depends on both.

### MinIO bucket missing

```
botocore.exceptions.ClientError: The specified bucket does not exist
```

The `minio-create-bucket` one-shot service should have created it.
If it didn't:
```bash
docker compose run --rm minio-create-bucket
```

---

## Migrations

### `Database is not migrated. Run alembic upgrade head`

Self-explanatory. Run it from the project root (NOT from `backend/`):
```bash
alembic upgrade head
```

### `Database migration is out of date (X != Y)`

You pulled new code but didn't migrate. Same fix as above.

### `Router.__init__() got an unexpected keyword argument 'on_startup'`

FastAPI / Starlette version mismatch. The repo pins
`fastapi==0.135.2`; if you let pip pull a newer one it'll bring a
Starlette that drops `on_startup`.

**Fix**:
```bash
pip install -r requirements.txt --force-reinstall
```

---

## Backend startup

### `SECRET_KEY is set to an insecure default`

Your `.env` either has the literal placeholder string, or doesn't have
`SECRET_KEY` at all (Phase 2 removed the in-code fallback).

**Fix**:
```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
# Paste output into .env as SECRET_KEY=...
```

### `RAG embedding init failed: ... requires SILICONFLOW_API_KEY`

You set `EMBEDDING_PROVIDER=siliconflow` but didn't fill
`SILICONFLOW_API_KEY`. Either fill the key or change the provider:
```ini
EMBEDDING_PROVIDER=local       # falls back to local model
```

### `Whisper model 'X' is missing. Run python scripts/init_models.py`

You're in full mode but never ran `init_models.py`. Run it once:
```bash
python scripts/init_models.py
```

If lite mode (`TRANSCRIPTION_PROVIDER=siliconflow` or similar) you
shouldn't see this — verify your `.env` actually has the right provider
set and there's no typo.

### Backend hangs on `Initializing reranker...`

Usually a slow first-run download from HuggingFace. Watch:
```bash
ls -la data/cache/huggingface/ | wc -l   # should grow
```

If you're behind a corporate proxy, set `HTTP_PROXY` / `HTTPS_PROXY` or
switch to an HF mirror via `HF_ENDPOINT=https://hf-mirror.com`.

### Chat returns 401 "当前模型的密钥无效" even though `.env` has a valid key

API key resolution order is:

1. `user_api_keys` row for `(user, provider)` — encrypted in the DB,
   set via the Models page in the frontend
2. fall back to `os.environ[provider.api_key_env]`

So a wrong DB-side key beats a valid `.env` key. Two ways to confirm:

```sql
-- which providers does this user have a saved key for?
docker exec interview_copilot_db psql -U postgres -d interview_copilot -c \
  "SELECT user_id, provider, key_masked FROM user_api_keys WHERE user_id = 'admin';"
```

**Fix:** delete the entry from the Models page UI (each card has a
trash icon next to the configured badge), OR wipe non-admin data:

```bash
python scripts/wipe_non_admin.py --admin-username <you> --dry-run    # preview
python scripts/wipe_non_admin.py --admin-username <you> --yes        # commit
```

### Chat returns 401 and the active model says it uses a vendor I never configured

Your per-user selection (column `users.model_selection_json`) points
at a profile whose `api_key_env` isn't filled in `.env` and you don't
have a per-user key for it either. Common case: someone clicked
through the Models page and selected Xiaomi MiMo for "primary", but
`MIMO_API_KEY` is empty.

**Fix (preferred):** go to the **Models** page in the frontend, pick a
primary / agent / mock-interview profile from a vendor whose key is
actually configured, and save.

**Fix (DB-level reset):** clear the selection column so the next chat
falls back to `ROLE_DEFAULTS`:

```sql
docker exec interview_copilot_db psql -U postgres -d interview_copilot -c \
  "UPDATE users SET model_selection_json = NULL WHERE username = '<you>';"
```

Profile ids are `provider/model` strings — e.g. `deepseek/deepseek-chat`,
`openai/gpt-4o-mini`. The full set comes from the live `/v1/models`
catalog cache (refreshable from the Models page).

---

## Frontend

### `tsc` fails with "Type error in node_modules"

Stale `node_modules`:
```bash
cd frontend
rm -rf node_modules package-lock.json
npm install
```

### Login succeeds but every API call returns 401

Token is being sent but server rejects it. Check the access token's
`jti` claim — Phase 2 enforces jti presence:
```bash
# In browser devtools → Application → Local Storage → access_token
# Decode the middle segment (base64url) — it should contain "jti": "..."
```

If `jti` is missing, you're using a token issued before the Phase 2
rollout. Log out + log in to get a fresh one.

### WebSocket immediately disconnects (`code: 1008`)

The `bearer` subprotocol handshake failed. Common causes:

1. JWT expired or revoked (logout, then re-login).
2. nginx between the browser and backend stripping the
   `Sec-WebSocket-Protocol` header. Production nginx config in
   `nginx/conf.d/frontend.conf` already forwards it; if you wrote your
   own config, add:
   ```
   proxy_set_header Sec-WebSocket-Protocol $http_sec_websocket_protocol;
   ```

### Avatar upload returns 502 with `头像存储不可用`

S3 / MinIO is unreachable from the backend process. Check:
```bash
docker compose ps minio                       # healthy?
curl http://localhost:9000/minio/health/live  # 200?
```

In `.env`, `AWS_ENDPOINT_URL` must point at MinIO. Default for local
dev is `http://localhost:9000`.

---

## Celery worker

### Worker exits immediately with `--pool=solo` error

PowerShell quoting bites you. Two workers run side by side now (one
heavy, one light — see the `worker-transcription` / `worker-light`
services in `docker-compose.yml`). Each in its own terminal:

```powershell
# Terminal 1 — transcription (loads Whisper, ~1.5 GB GPU)
celery -A app.worker.celery_app.celery_app worker --loglevel=info --pool=solo --queues=transcription --hostname=transcription@%h

# Terminal 2 — light tasks (memory dreaming, document ingestion; no Whisper)
celery -A app.worker.celery_app.celery_app worker --loglevel=info --pool=threads --concurrency=4 --queues=default --hostname=light@%h

# Terminal 3 — beat scheduler (fires nightly dreaming at 03:30 Asia/Shanghai)
celery -A app.worker.celery_app.celery_app beat --loglevel=info
```

Single line, exact spelling per command. Don't use a pipe / variable
substitution that might mangle `--pool=solo`.

### Tasks queued but never picked up

Either the worker isn't running, or the broker URL doesn't match
between API and worker. Both should read `REDIS_URL` from the same
`.env`. Verify:
```bash
docker compose exec redis redis-cli LRANGE celery 0 -1
```
(Should be empty when worker is consuming.)

### Long task gets re-delivered mid-execution

Phase 1 set `visibility_timeout=3700` and `task_time_limit=1800` for
analysis. If your custom task runs longer than 3700 s, bump
visibility_timeout in `backend/app/worker/celery_app.py` and the
matching `task_time_limit` decorator.

---

## Mock interview

### "Resume analysis 30s timeout" → fallback plan with hardcoded RESTful question

This was fixed in Phase 1 — the resume-parse path no longer calls an
LLM, just extracts text. If you still see it, your `.env`'s
`DEEPSEEK_API_KEY` is likely empty / wrong. Verify by hitting a chat
first; if chat works, mock should too.

### "你有一个未完成的模拟面试" never goes away

The Phase 2 fix purges 0-Q&A shell sessions automatically. If you're
on older code, either pull the latest or:
```bash
docker compose exec db psql -U postgres -d interview_copilot -c \
  "DELETE FROM chat_sessions WHERE session_type='mock_interview' AND turn_count=0;"
```

### Whisper transcript returns Norwegian / wrong language

WhisperX defaulted language detection to `nn` on certain audio types.
Phase 1 set explicit `language="zh"` on every call. If you're using
local whisperx and want a different default, edit
`audio_transcription_service.py:_run_whisperx_sync` — `transcribe(audio,
batch_size=16, language="zh")`.

---

## Performance

### "QueuePool limit reached" under multi-worker uvicorn

PG max_connections too low. Either:
1. Reduce `DB_POOL_SIZE` in `.env` (default 20 means 4 workers × 40 = 160 conns)
2. Raise `max_connections` in postgres.conf — see [postgres-tuning.md](postgres-tuning.md)

### "Vendor just released a new model — I don't see it in the dropdown"

The catalog auto-discovers from each vendor's `/v1/models` every 24 h.
Force-refresh either way:

- **Web**: Models page → click **「刷新模型库」**
- **CLI**: `python scripts/refresh_models.py`
- **HTTP**: `POST /api/v1/models/refresh-catalog`

If the model still doesn't appear, the vendor either hasn't exposed it
on `/v1/models` yet OR the vendor adapter's chat-only filter dropped
it (e.g. ids containing `embed`, `whisper`, `tts-`, `dall-e`, `realtime`).
For the latter, edit the relevant `_NON_CHAT_HINTS` list in
`backend/app/services/model_sources/vendors/<vendor>.py` — or, if it
deserves a featured display name + ranking, add a row in
`backend/app/services/model_sources/curated.py`.

### "I changed POSTGRES_PASSWORD in .env.docker and the API can't connect"

Two places hold credentials and they must agree:

1. `.env.docker` → seeds the postgres container at boot
2. `.env` → API/worker use this URL to dial the DB

If you changed the password in `.env.docker`, also set the matching
override in `.env`:
```ini
DATABASE_URL_DOCKER=postgresql://NEWUSER:NEWPASS@db:5432/interview_copilot
```
(`DATABASE_URL` for host-mode dev where uvicorn runs on the host needs
the same change with `localhost:5432`.)

After changing, you must **drop the postgres data volume** to re-seed
with the new password — otherwise the existing volume keeps the OLD
password and the new container picks up env vars but doesn't apply them
to existing data:
```bash
docker compose down
docker volume rm interview_copilot_pgdata
docker compose up -d
alembic upgrade head        # rebuild schema in fresh DB
```

### `/models/ping` very slow

Each profile pings its provider. With 280+ models in the catalog and
~10 timing out at 10 s each, a full ping takes minutes. Either:
- Only configure API keys for vendors you actually use (others get
  skipped at the "no key" short-circuit, no HTTP fired)
- Hide vendors you don't need via the Models page "显示更多厂商"
  picker — toggling a card OFF stops the ping from including it

### Embedding very slow, no GPU

You're on CPU. Either:
- Switch to lite mode (`EMBEDDING_PROVIDER=siliconflow`)
- Or in full mode use a smaller model: `EMBEDDING_MODEL=BAAI/bge-small-en-v1.5` + `EMBEDDING_DIM=384`

---

## Encoding (Windows-specific)

### Console shows `��` instead of Chinese / emoji

Windows GBK terminal can't render UTF-8. The dev script already sets
codepage; if you launched manually:
```powershell
chcp 65001
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'
```

### `init_models.py` crashes on Unicode arrows

Phase 5+ replaced `⏭` / `✓` / `⬇` with `[skip]` / `[ok]` / `[get]` to
work on GBK terminals. If you still see the crash, your repo is stale.

---

## Still stuck?

Read the structured log on the failing component:
```bash
# Backend
tail -200 logs/backend-*.log

# Celery (if using start.ps1 -SkipFrontend, it's in the same log)
docker compose logs <service>
```

Open an issue with:
- Mode (lite / full / hybrid)
- The exact error from the log (NOT a screenshot)
- Output of `docker compose ps`
- Output of `pip list | grep -E "(fastapi|sqlalchemy|llama-index|whisperx|sentry-sdk)"`
