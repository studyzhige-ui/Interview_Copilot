# Getting Started

Pick **one** path:

- **[Path A — API-light](#path-a--api-light-cloud-everything)**: every
  component (LLM / embedding / reranker / ASR) is a cloud API call.
  Zero local model downloads, no GPU. The cheapest way to evaluate the
  project end-to-end.
- **[Path B — Local-models](#path-b--local-models-self-hosted-ml)**:
  embedding / reranker / Whisper / Pyannote all run on this machine.
  LLM is still cloud. Best for privacy or if you already have a GPU.

After either path completes, you'll have a working register / login /
chat / mock-interview / analysis flow.

Optional add-ons (real email, LLM tracing, Sentry, web search) and the
full gotcha collection live at the end:
**[Optional add-ons](#optional-add-ons)** · **[Common gotchas](#common-gotchas)**.

---

## Prerequisites (both paths)

| Tool | Min version | Why |
|---|---|---|
| **Python 3.10 / 3.11 / 3.12** | — | Backend + Celery. Not 3.13 (whisperx / pyannote wheels don't exist yet). |
| **Node.js** | 20 | Frontend dev / build. |
| **Docker Desktop** or `docker engine + compose` | 24 | Postgres / Redis / Milvus / MinIO. Must be running before setup. |
| **Conda** (Anaconda / Miniconda) | recent | Python env isolation. `venv` also works. |
| **Git** | any | Cloning. |
| **PowerShell 7** (`pwsh`) | optional | Cleaner than Windows PowerShell 5.1 on Windows. |

GPU is **only useful for Path B** (and even then optional — CPU runs
embedding / Whisper but slowly).

---

## Path A — API-light (cloud-everything)

Everything talks to a remote API. You'll need keys from **two** vendor
groups:

- **An LLM provider** (DeepSeek is the recommended starter — cheap, strong, China-friendly).
- **A combined Embedding + Reranker + ASR provider** (SiliconFlow is the recommended starter — one key covers all three).

### A1. Clone + isolated Python env

```bash
git clone https://github.com/<your-org>/Interview_Copilot.git
cd Interview_Copilot

conda create -n interview-copilot python=3.11 -y
conda activate interview-copilot

# Sanity check — path must contain envs/interview-copilot/, NOT base.
python -c "import sys; print(sys.executable)"
```

### A2. Run setup, pick API-light when prompted

```powershell
.\scripts\setup.ps1            # Windows
```

```bash
./scripts/setup.sh             # Linux / macOS
```

The script will:

1. Refuse if you're in base Python.
2. `pip install -r requirements.txt` (~3 GB; download speed = your
   network).
3. Ask: *"[1] API-light  [2] Local-models"* — enter `1`.
4. Copy `.env.example.lite` → `.env` and auto-generate a `SECRET_KEY`.
5. `docker compose up -d` then `alembic upgrade head`.
6. `cd frontend && npm install`.

### A3. Get API keys (~5 minutes per vendor)

**LLM key — pick one (you can add more later from the Models page):**

| Vendor | URL | Cost |
|---|---|---|
| **DeepSeek** *(recommended)* | <https://platform.deepseek.com/api_keys> | ¥1/M tokens, top-up required |
| OpenAI | <https://platform.openai.com/api-keys> | $$ |
| Anthropic | <https://console.anthropic.com/settings/keys> | $$ |
| Alibaba Qwen | <https://dashscope.console.aliyun.com/apiKey> | Free tier |
| Moonshot Kimi | <https://platform.moonshot.cn/console/api-keys> | Free tier |
| Zhipu GLM | <https://bigmodel.cn/usercenter/apikeys> | Free tier |

**Embedding + Reranker + ASR (the cheapest one-stop):**

- **SiliconFlow** *(recommended)*: <https://siliconflow.cn> · free tier covers casual use.

### A4. Fill `.env`

Open `.env`. Find **§ 4** and paste your LLM key:

```ini
DEEPSEEK_API_KEY=sk-...
```

Find **§ 5** and paste your one-stop key:

```ini
SILICONFLOW_API_KEY=sk-...
```

That's all you have to change. The other sections are pre-configured
to route every role to SiliconFlow (embedding / reranker / ASR) and to
DeepSeek (LLM). No models download.

### A5. Start the backend

```powershell
.\scripts\start.ps1 -SkipFrontend
```

Wait for these lines in the backend log:

```
[uvicorn] INFO ====== Interview Copilot startup sequence complete ======
[uvicorn] INFO: Application startup complete.
[celery] celery@<hostname> ready.
```

If something fails here, see [Common gotchas](#common-gotchas) (especially
**G1, G2, G3**).

### A6. Start the frontend

In a separate tab:

```powershell
.\scripts\start.ps1 -SkipBackend
```

Look for `vite -> http://localhost:5173` then open that URL.

### A7. Register + chat

Click **Register**, fill email/username/password, hit "Send code".

**The verification code prints to the backend terminal** (you didn't
configure SMTP):

```
[email] SMTP not configured — body printed below.
  Body:    您的验证码是: 123456
```

Copy it into the form. Log in. Right panel = chat. Type a message, hit
send. You should see a streaming reply from DeepSeek.

**Path A complete.** Skip to [Optional add-ons](#optional-add-ons) if
you want real email, LLM tracing, etc.

---

## Path B — Local-models (self-hosted ML)

Embedding / reranker / Whisper / Pyannote download to your disk and run
locally. LLM is still cloud (DeepSeek by default).

### B1. Clone + isolated Python env

Same as A1.

### B2. Run setup, pick Local-models when prompted

Same as A2 but enter **`2`** at the prompt — copies `.env.example` (not
the `.lite` one).

### B3. Get just the LLM key

Same vendor list as A3, just LLM. You don't need a SiliconFlow / Jina /
Cohere key — those roles run locally.

### B4. Fill `.env`

Open `.env`. **§ 4**:

```ini
DEEPSEEK_API_KEY=sk-...
```

`.env.example` already sets `EMBEDDING_PROVIDER=local`,
`RERANKER_PROVIDER=local`, `TRANSCRIPTION_PROVIDER=local_whisperx` and
the matching model ids. No further changes needed.

### B5. Download the local models (~5 GB)

```bash
python scripts/init_models.py --dry-run     # see what + size, real-time from HF
python scripts/init_models.py               # actually download
```

Expected dry-run (your sizes may differ):

```
      embedding: BAAI/bge-m3                                (~1.06 GB)
       reranker: BAAI/bge-reranker-v2-m3                    (~1.08 GB)
        whisper: Systran/faster-whisper-large-v3            (~2.88 GB)
    diarization: pyannote-community/speaker-diarization-community-1   (~32 MB)
```

`.env` defaults to `HF_ENDPOINT=https://hf-mirror.com` (the CN mirror).
Total ~5 GB. The script supports byte-level resume — if a download
stalls, just re-run.

### B6. Start the backend

```powershell
.\scripts\start.ps1 -SkipFrontend
```

The first start loads each local model into memory once. Expect ~15–30
seconds before you see "startup sequence complete", depending on GPU.

### B7. Start the frontend

In a separate tab:

```powershell
.\scripts\start.ps1 -SkipBackend
```

### B8. Register + chat + try a real upload

Same as A6/A7 — register, copy code from backend terminal, log in,
chat works.

**Bonus for Local-models:** the recording-analysis pipeline is now
fully local. Go to **复盘 → 创建面试 → 上传音视频** and try with a real
mp4/m4a/wav. WhisperX transcribes + Pyannote labels speakers + LLM
generates the report.

**Path B complete.**

---

## Optional add-ons

Each of these is **opt-in**. None is required for the core flow above.

### Real email delivery (SMTP)

Replaces "verification code → backend stdout" with actual emails. Fill
`.env` **§ 3.5**:

```ini
# Gmail example — generate at https://myaccount.google.com/apppasswords
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=you@gmail.com
SMTP_PASSWORD=abcd efgh ijkl mnop      # 16-char App Password, NOT login password
SMTP_FROM=Interview Copilot <you@gmail.com>
SMTP_USE_TLS=true
```

The verification body is **always** mirrored to the backend log too —
SMTP success or failure — so you can audit.

For 163 / QQ / Outlook, see comments inline in `.env.example` § 3.5.

### LangSmith — see every LLM call

Sign up <https://smith.langchain.com>, generate an API key, fill
`.env` § 3.6:

```ini
LANGSMITH_API_KEY=lsv2_pt_...
LANGSMITH_PROJECT=Interview Copilot
LANGSMITH_TRACING=true
```

Restart backend. Every chat now shows up in the LangSmith UI with full
prompts, responses, latency, and token counts.

### Agent web search — Tavily

Sign up <https://tavily.com/> (free 1k searches/month), fill `.env`:

```ini
TAVILY_API_KEY=tvly-...
```

Restart. Agent mode's `web_search` tool is now active. The model decides
on its own when to use it (function calling).

### Sentry — error tracking

Sign up <https://sentry.io>, create a Python (FastAPI) project, copy
DSN to `.env`:

```ini
SENTRY_DSN=https://...@...ingest.us.sentry.io/...
SENTRY_ENVIRONMENT=prod
```

Frontend has its own DSN in `frontend/.env.production` as
`VITE_SENTRY_DSN`.

### Per-user model selection (Models page)

Once logged in, the **Models** page (left nav) lets each user save
their own API keys (Fernet-encrypted in DB) and assign models to roles
(Primary / Agent / Mock Interview). Per-user keys take precedence over
`.env`.

### Hybrid mode (cloud ASR + local diarization)

Best of both worlds: cloud ASR gives word-level timestamps; local
Pyannote labels speakers without GPU thrash. Edit `.env`:

```ini
TRANSCRIPTION_PROVIDER=openai
TRANSCRIPTION_MODEL=whisper-1
DIARIZATION_MODE=pyannote
```

Then download just the small Pyannote model:

```bash
python scripts/init_models.py --only diarization
```

---

## Common gotchas

Sorted by where in the flow they tend to surface.

### G1. `pwsh scripts/start.ps1` reports base Python, even though prompt is `(env)`

`pwsh` prefix spawns a **child** PowerShell process. The child loads
`$PROFILE`, whose conda init can reset PATH back to base. The parent's
prompt still says `(your-env)` but the child runs against base Python.

**Fix:** use the `.\` form to run in the current shell:

```powershell
.\scripts\start.ps1
```

If ExecutionPolicy blocks `.\` scripts, allow signed user scripts once:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned -Force
```

### G2. `conda activate <env>` doesn't actually switch Python

You created the env with `conda create -n NAME` *without* `python=X.Y`.
Conda made a metadata-only env with no Python binary. Activating it
silently falls back to base.

**Fix:** rebuild including the Python version:

```powershell
conda env remove -n <env> -y
conda create -n <env> python=3.11 -y
conda activate <env>
pip install -r requirements.txt
```

### G3. `pip install` fails on whisperx / pyannote with Python 3.13

These libs don't have 3.13 wheels yet. Use 3.10 / 3.11 / 3.12. Setup
refuses 3.13 explicitly.

### G4. Don't install into base Python

Setup refuses to install ~3 GB of ML deps into a non-isolated Python.
This is deliberate — torch + whisperx would clobber whatever other
projects share your base interpreter.

### G5. Chat returns 401 "当前模型的密钥无效" even though `.env` has a valid key

Key resolution order:

1. `user_api_keys` row for `(user, provider)` — set via the Models page
2. fall back to `os.environ[provider.api_key_env]`

A wrong DB-side key beats a valid `.env` key. Either delete the entry
on the Models page (trash icon next to the configured badge) or wipe
non-admin data:

```bash
python scripts/wipe_non_admin.py --admin-username <you> --dry-run
python scripts/wipe_non_admin.py --admin-username <you> --yes
```

### G6. Chat 401 + the active model says a vendor I never configured

Your per-user selection points at a profile whose `api_key_env` is empty
in `.env`. Two ways to fix:

- **Models page** (preferred): left nav → Models → pick a primary /
  agent / mock-interview profile from a vendor whose key you've actually
  filled. Hit save.
- **DB-level reset**: clear the selection column so the next chat falls
  back to `ROLE_DEFAULTS`:
  ```sql
  UPDATE users SET model_selection_json = NULL WHERE username = '<you>';
  ```

Per-user selection lives in the `users.model_selection_json` Postgres
column (no JSON file on disk anymore). Profile ids are `provider/model`
strings — e.g. `deepseek/deepseek-chat`, `openai/gpt-4o-mini` — which
the live `/v1/models` catalog populates.

### G7. Frontend gets `http proxy error: EACCES` on every request

Backend isn't actually up. Look at the backend tab — usually a startup
crash. Until you see `Application startup complete` the frontend has
nothing to proxy to.

### G8. Backend hangs on `[2/5] Initializing reranker...`

Slow first-time HuggingFace download. Watch:

```bash
ls -la data/cache/huggingface/ | wc -l
```

It should grow. Behind a corporate proxy, set `HTTP_PROXY` /
`HTTPS_PROXY` or change `HF_ENDPOINT`.

### G9. Backend crash: `Reranker model 'X' is not in the local cache`

The error already lists *which* models you have cached vs. what `.env`
requested. Either change `.env` to use a cached model, or run:

```bash
python scripts/init_models.py
```

### G10. `Database is not migrated`

```bash
python -c "from alembic.config import CommandLine; CommandLine().main(['upgrade','head'])"
```

### G11. The "already-registered email won't get a code" banner

This is an anti-enumeration measure: a register attempt with an email
that's already a `users` row returns the same "sent" response but no
email goes out. **"Already registered"** here means there's a row in
the `users` table — clicking "Send code" by itself doesn't count.

### G12. Where `.env` vs `.env.docker` are read from

- `.env` is read by **Python** (uvicorn / celery / alembic / init_models).
- `.env.docker` is read by **`docker-compose`** to seed the Postgres +
  MinIO containers at first boot.

They share Postgres / MinIO credentials. If you customise `.env.docker`,
also update `.env`'s `DATABASE_URL` (and the optional `*_DOCKER`
overrides).

### Anything else

→ **[troubleshooting.md](troubleshooting.md)** for the long-form list.

---

## Stopping

`Ctrl+C` in each terminal tab stops that service. To bring docker down too:

```powershell
.\scripts\stop.ps1
```

Add `-Volumes` / `--volumes` to wipe Postgres / Milvus / MinIO data
volumes — **destructive**, clears all users / records / indexes.

---

## What runs where

```
.env             ← read by Python (uvicorn / celery / alembic / init_models)
.env.docker      ← read by docker-compose to seed Postgres + MinIO

uvicorn (port 8080)   ← HTTP API + WebSocket (streaming chat)
celery worker         ← async jobs (transcribe / ingest / analyze)

docker:
  postgres            ← relational data (users, sessions, QA, uploads)
  redis               ← Celery broker + JWT blacklist + cache
  milvus              ← RAG + memory vector index
  minio               ← uploaded files (resumes, audio, avatars)
```
