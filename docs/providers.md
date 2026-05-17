# Provider Catalog — Lite / Full / Hybrid

Interview Copilot has four model roles. Each is configured by **one of
~6 providers** + **a free-form model name**. Adding a new model variant
(small / base / large) is just an env-var change — no code touches.

## TL;DR — pick a column

| Mode    | Local downloads | GPU | First-run | Per-call cost | Privacy |
|---------|-----------------|-----|-----------|---------------|---------|
| **Lite** | 0 GB | No | ~5 min | API pay-per-use | Audio + text leave the machine |
| **Full** | ~5–8 GB | Recommended | ~30 min download | Free (electricity only) | All data stays local |
| **Hybrid** | ~17 MB (Pyannote only) | Recommended | ~1 min | API for ASR/embed/rerank | Audio leaves; speakers labelled locally |

You can also mix on a per-role basis — e.g. local embedding + remote rerank.

## The four roles

| Role | Env vars | Registry file |
|------|----------|---------------|
| **LLM** (chat / agent / mock interviewer) | picked per-user via Models page UI | `backend/app/core/model_registry.py` |
| **Embedding** | `EMBEDDING_PROVIDER` + `EMBEDDING_MODEL` + `EMBEDDING_DIM` | `backend/app/rag/embedding_registry.py` |
| **Reranker** | `RERANKER_PROVIDER` + `RERANKER_MODEL` | `backend/app/rag/reranker_registry.py` |
| **ASR** (audio → text) | `TRANSCRIPTION_PROVIDER` + `TRANSCRIPTION_MODEL` | `backend/app/services/voice/transcription_registry.py` |
| **Diarization** (who spoke) | `DIARIZATION_MODE` (auto/pyannote/none) + `DIARIZATION_MODEL_ID` | inline in `audio_transcription_service.py` |

## How the provider+model split works

Each registry file ships a small `PROVIDERS` dict (~5–10 entries). One
entry **per vendor**, NOT per (vendor × model). Example from
`embedding_registry.py`:

```python
PROVIDERS = {
    "local":       EmbeddingProvider(kind="local_huggingface"),
    "openai":      EmbeddingProvider(kind="openai",        api_base="...", api_key_env="OPENAI_API_KEY"),
    "siliconflow": EmbeddingProvider(kind="openai_compat", api_base="...", api_key_env="SILICONFLOW_API_KEY"),
    "jina":        EmbeddingProvider(kind="openai_compat", api_base="...", api_key_env="JINA_API_KEY"),
    "dashscope":   EmbeddingProvider(kind="openai_compat", api_base="...", api_key_env="DASHSCOPE_API_KEY"),
    "zhipu":       EmbeddingProvider(kind="openai_compat", api_base="...", api_key_env="ZHIPU_API_KEY"),
}
```

User chooses:

```ini
EMBEDDING_PROVIDER=siliconflow         # the dict key above
EMBEDDING_MODEL=BAAI/bge-m3             # ANY model name SiliconFlow hosts
EMBEDDING_DIM=1024                      # output dim
```

Want a different model? Just edit `EMBEDDING_MODEL`. Want a different
provider? Edit `EMBEDDING_PROVIDER` + key. Want to add a new vendor?
Append one line to `PROVIDERS` in code, set the new env vars in `.env`.

## Recommended combos

### 🇨🇳 China-friendly lite (5-min start, no GPU)

```ini
DEEPSEEK_API_KEY=sk-...                   # LLM
SILICONFLOW_API_KEY=sk-...                # everything else

EMBEDDING_PROVIDER=siliconflow
EMBEDDING_MODEL=BAAI/bge-m3
EMBEDDING_DIM=1024

RERANKER_PROVIDER=siliconflow
RERANKER_MODEL=BAAI/bge-reranker-v2-m3

TRANSCRIPTION_PROVIDER=siliconflow
TRANSCRIPTION_MODEL=FunAudioLLM/SenseVoiceSmall
DIARIZATION_MODE=auto                     # off — SenseVoice doesn't do word ts
```

### 🌐 Global lite

```ini
OPENAI_API_KEY=sk-...

EMBEDDING_PROVIDER=openai
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIM=1536

RERANKER_PROVIDER=cohere                  # or jina (cheaper)
RERANKER_MODEL=rerank-multilingual-v3.0
COHERE_API_KEY=...

TRANSCRIPTION_PROVIDER=openai
TRANSCRIPTION_MODEL=whisper-1
DIARIZATION_MODE=auto                     # off in pure remote — see hybrid below
```

### 💻 Full local (privacy-first)

```ini
DEEPSEEK_API_KEY=sk-...                   # LLM still hits API; nothing else does

EMBEDDING_PROVIDER=local
EMBEDDING_MODEL=BAAI/bge-m3                # or bge-large-zh-v1.5 / bge-small-en-v1.5 / ...
EMBEDDING_DIM=1024                         # match the model

RERANKER_PROVIDER=local
RERANKER_MODEL=BAAI/bge-reranker-v2-m3     # or bge-reranker-large / bge-reranker-base

TRANSCRIPTION_PROVIDER=local_whisperx
TRANSCRIPTION_MODEL=Systran/faster-whisper-large-v3   # or medium / small / base
DIARIZATION_MODE=auto                      # → local Pyannote, bundled

HF_ENDPOINT=https://hf-mirror.com          # CN mirror
```

Then `python scripts/init_models.py` to pre-download everything you
configured (it reads the env vars, downloads only the local-* roles).

For 100% offline you'd add a local LLM (Ollama / vLLM) — register it as
a new entry in `MODEL_PROFILES` (model_registry.py) with
`api_base="http://localhost:11434/v1"`.

### 🔀 Hybrid (best of both)

Remote ASR for fast transcription, local Pyannote for proper speaker
labels:

```ini
TRANSCRIPTION_PROVIDER=openai
TRANSCRIPTION_MODEL=whisper-1              # supports word-level timestamps
DIARIZATION_MODE=pyannote                  # force local Pyannote
```

Then `python scripts/init_models.py --only diarization` (~17 MB).

Workflow per call:
1. Audio → OpenAI Whisper API → text + word timestamps
2. Same audio → local Pyannote → speaker segments
3. `whisperx.assign_word_speakers` aligns words to speakers
4. Output → `**[Speaker 1]**: ... **[Speaker 2]**: ...` markdown

If the chosen ASR provider can't return word timestamps (e.g.
SenseVoiceSmall on SiliconFlow), the system auto-degrades to single-
speaker output without erroring.

## Provider catalog (which models work where)

The lists below are **suggestions**, not hard-coded options. Type any
HF id / API model name into `*_MODEL`; if the provider hosts it, it works.

### Embedding providers

| `*_PROVIDER` | China-friendly | Suggested `*_MODEL` values | Notes |
|---|---|---|---|
| `local`       | ✓ | `BAAI/bge-m3` (1024) · `BAAI/bge-large-zh-v1.5` (1024) · `BAAI/bge-small-en-v1.5` (384) · `intfloat/multilingual-e5-large` (1024) | HF download, run on local CPU/GPU |
| `siliconflow` | ✓ | `BAAI/bge-m3` (1024) · `Pro/BAAI/bge-m3` (1024, paid SLA) | Drop-in dim with local bge-m3 |
| `dashscope`   | ✓ | `text-embedding-v3` (1024) · `text-embedding-v2` (1536) | OpenAI-compat mode |
| `zhipu`       | ✓ | `embedding-3` (2048) · `embedding-2` (1024) | 2048-dim → separate Milvus collection |
| `openai`      |   | `text-embedding-3-small` (1536) · `text-embedding-3-large` (3072) | The `dimensions=` param is honoured |
| `jina`        |   | `jina-embeddings-v3` (1024) · `jina-embeddings-v2-base-zh` (768) | Drop-in dim with bge-m3 |

**⚠ EMBEDDING_DIM lock-in**: Milvus collection dim is fixed at first
write. Pre-commit to one dim or be ready to drop + re-ingest.

### Reranker providers

| `*_PROVIDER` | China-friendly | Suggested `*_MODEL` values | Notes |
|---|---|---|---|
| `local`       | ✓ | `BAAI/bge-reranker-v2-m3` (1.5 GB) · `BAAI/bge-reranker-large` (1.1 GB) · `BAAI/bge-reranker-base` (530 MB) | HF download, runs as cross-encoder |
| `siliconflow` | ✓ | `BAAI/bge-reranker-v2-m3` · `BAAI/bge-reranker-v2-gemma` | Same model, no local download |
| `dashscope`   | ✓ | `gte-rerank` | OpenAI-compat /rerank |
| `jina`        |   | `jina-reranker-v2-base-multilingual` · `jina-reranker-m0` | Multilingual, decent |
| `cohere`      |   | `rerank-multilingual-v3.0` · `rerank-english-v3.0` | Highest quality, paid |

Rerank failures fall through to passing the unranked top-N — flaky
upstream degrades quality, never breaks the request.

### ASR (transcription) providers

| `*_PROVIDER` | China-friendly | Suggested `*_MODEL` values | Word ts | Notes |
|---|---|---|---|---|
| `local_whisperx` | ✓ | `Systran/faster-whisper-large-v3` · `medium` · `small` · `base` | ✓ | Bundled Pyannote diarization |
| `openai`         |   | `whisper-1` · `gpt-4o-transcribe` · `gpt-4o-mini-transcribe` | ✓ | $0.006/min for whisper-1 |
| `siliconflow`    | ✓ | `FunAudioLLM/SenseVoiceSmall` · `openai/whisper-large-v3` |   | SenseVoice = CN-optimised; cheap |
| `dashscope`      | ✓ | `paraformer-realtime-v2` · `paraformer-v2` |   | CN ASR, very fast |

**Word timestamps** column = whether the provider can return word-level
timing for hybrid Pyannote alignment. ✓ means hybrid mode works; blank
means hybrid will auto-degrade to single-speaker.

### LLM providers

LLM is selected per-user from the Models page UI (different users in
the same deployment can use different chat models). The catalog of ~38
profiles is in `backend/app/core/model_registry.py` — DeepSeek, OpenAI,
Anthropic, Gemini, Qwen, Moonshot, 智谱, MiMo, NVIDIA. New users see
all and only configure the ones they want.

This one keeps the per-(provider, model) profile pattern because LLMs
need richer per-model metadata (function calling, context window,
display name) for the UI dropdown — different design constraint from
the simpler embedding/rerank/ASR roles.

## Switching modes safely

| Scenario | Action |
|----------|--------|
| No data yet | Edit `.env`, restart. |
| Have indexed data + same `EMBEDDING_DIM` | Restart; Milvus keeps working. |
| Have indexed data + different dim | Drop Milvus collection, restart, re-ingest knowledge from Library. Chat history + interviews are unaffected (Postgres). |

Quick collection drop:

```bash
docker compose exec milvus-standalone /bin/sh -c \
  'curl -X POST localhost:9091/v1/collection/drop -d "{\"collection\":\"interview_copilot_rag\"}"'
```

## LLM provider routing — one branch for everything

Every supported LLM provider is reached through the **same**
`OpenAILike` client. Each `MODEL_PROFILES` entry just plugs in a
different `api_base`:

| Provider | `api_base` |
|---|---|
| DeepSeek | `https://api.deepseek.com` |
| OpenAI | `https://api.openai.com/v1` |
| Anthropic | `https://api.anthropic.com/v1` *(OpenAI-compat shim)* |
| NVIDIA | `https://integrate.api.nvidia.com/v1` |
| Google Gemini | `https://generativelanguage.googleapis.com/v1beta/openai` |
| Alibaba DashScope | `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| Moonshot, Zhipu, MiMo, SiliconFlow, … | each vendor's own OpenAI-compatible base URL |

So switching providers is purely **(api_base, api_key, model_id)**.
No special wrappers, no LiteLLM, no per-vendor branches. Adding a new
provider = one new `MODEL_PROFILES` entry; the runtime code never
grows another `if`.

The actual builder in `backend/app/core/model_registry.py:_build_llm_instance`
is six lines:

```python
def _build_llm_instance(profile: ModelProfile):
    return OpenAILike(
        model=profile.model,
        api_key=resolve_api_key(profile),
        api_base=profile.api_base,
        is_chat_model=True,
        is_function_calling_model=profile.supports_function_calling,
        context_window=profile.context_window,
        temperature=0.2,
    )
```

---

## Adding a new provider (developer-side)

Need a vendor that's not in the list? E.g. Voyage AI for embeddings:

```python
# backend/app/rag/embedding_registry.py — add one entry
PROVIDERS["voyage"] = EmbeddingProvider(
    kind="openai_compat",
    api_base="https://api.voyageai.com/v1",
    api_key_env="VOYAGE_API_KEY",
    label="Voyage AI",
)
```

Then in `.env`:
```ini
EMBEDDING_PROVIDER=voyage
EMBEDDING_MODEL=voyage-3-large
EMBEDDING_DIM=1024
VOYAGE_API_KEY=...
```

Restart. No other code changes. PR-worthy if it's a popular vendor.

## Adding a new model (user-side)

You don't add models. You **type the model name** into `*_MODEL`. If the
provider hosts it, it works. If it doesn't, the provider returns 404 at
the first request and you'll see a clear error in the log.

## Live model discovery (LLM only)

The LLM dropdown auto-populates with whatever each vendor's `/v1/models`
endpoint currently advertises. So when DeepSeek / OpenAI / Anthropic ship
a new model, it shows up in the **Models** page on the next refresh —
no code update needed.

**How it works**:

1. On every Models-page load, the backend merges the curated
   `MODEL_PROFILES` dict with the cached output of each vendor's
   `/v1/models` call.
2. Discovery results are cached in Redis for 24 h
   (`model_catalog:v1:<provider>`). The first user to load the page
   after a deploy pays the discovery cost (~1–2 s per vendor); everyone
   else hits cache.
3. Curated entries always win on metadata (display name, description,
   context window). Auto-discovered models that aren't in the curated
   set get sensible defaults (128 K context, function-calling assumed)
   and a `auto_discovered: true` flag in the API response.

**How to trigger a refresh manually**:

- **Web UI**: Models page → click **「刷新模型库」** (next to the
  "Ping 测试" button). Drops the cache + re-discovers in one round trip.
- **HTTP**: `POST /api/v1/models/refresh-catalog` (any logged-in user).
- **CLI** (great for cron / CI pre-warming):
  ```bash
  python scripts/refresh_models.py                 # all vendors
  python scripts/refresh_models.py --provider openai
  python scripts/refresh_models.py --json
  ```

**Vendor coverage**: any provider whose `api_base` serves an OpenAI-style
`/v1/models` endpoint — that's all the chat-LLM vendors in the catalog
(OpenAI / Anthropic / DeepSeek / Moonshot / Qwen / SiliconFlow / Zhipu /
xAI / Mistral). Vendors without a key set are silently skipped (nothing
to discover anyway).

**Filter heuristic**: the discovery code drops models whose id contains
`embedding`, `whisper`, `tts-`, `dall-e`, `rerank`, etc. so the LLM
dropdown doesn't get cluttered with non-chat models. If a chat model
happens to match the heuristic (rare), promote it to `MODEL_PROFILES`
and it'll show up curated.
