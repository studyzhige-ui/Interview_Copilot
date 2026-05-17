# Provider 目录 — Lite / Full / Hybrid

Interview Copilot 有 4 个模型角色。每个角色由「**~6 个 provider 之一** + **任意模型名**」配置。
新增模型变体（small / base / large）只是改 env 变量，不动代码。

## TL;DR — 挑一栏

| 模式 | 本地下载 | GPU | 首次启动 | 单次成本 | 隐私 |
|---|---|---|---|---|---|
| **Lite** | 0 GB | 不需 | ~5 分钟 | API 按量付费 | 音频+文本会上传到云 |
| **Full** | ~5–8 GB | 推荐 | ~30 分钟下载 | 免费（电费） | 全部数据本地不外传 |
| **Hybrid** | ~17 MB（仅 Pyannote） | 推荐 | ~1 分钟 | API 跑 ASR/embed/rerank | 音频上传，说话人本地标注 |

也可按角色混用 — 比如 embedding 本地 + rerank 远程。

## 4 个角色一览

| 角色 | 配置 env 变量 | 注册表文件 |
|---|---|---|
| **LLM**（聊天 / Agent / 模拟面试官） | 在「模型」页用户级选择 | `backend/app/core/model_registry.py` |
| **Embedding** | `EMBEDDING_PROVIDER` + `EMBEDDING_MODEL` + `EMBEDDING_DIM` | `backend/app/rag/embedding_registry.py` |
| **Reranker** | `RERANKER_PROVIDER` + `RERANKER_MODEL` | `backend/app/rag/reranker_registry.py` |
| **ASR**（语音转文字） | `TRANSCRIPTION_PROVIDER` + `TRANSCRIPTION_MODEL` | `backend/app/services/voice/transcription_registry.py` |
| **说话人分离** | `DIARIZATION_MODE`（auto/pyannote/none）+ `DIARIZATION_MODEL_ID` | 内联在 `audio_transcription_service.py` |

## provider+model 拆分如何工作

每个 registry 文件维护一个小 `PROVIDERS` 字典（5–10 条），**每家厂商一条**，不是「(厂商 × 模型)」组合。例：

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

用户只填 3 行：

```ini
EMBEDDING_PROVIDER=siliconflow         # 上面字典的 key
EMBEDDING_MODEL=BAAI/bge-m3             # 该厂商支持的任意模型名
EMBEDDING_DIM=1024                      # 该模型的输出维度
```

想换模型？改 `EMBEDDING_MODEL` 一行。换厂商？改 `EMBEDDING_PROVIDER` + key。新增厂商？在 `PROVIDERS` 加一条记录，不动其他代码。

## 推荐组合

### 🇨🇳 中国友好 lite（5 分钟启动，无 GPU）

```ini
DEEPSEEK_API_KEY=sk-...                   # LLM
SILICONFLOW_API_KEY=sk-...                # 其他全部

EMBEDDING_PROVIDER=siliconflow
EMBEDDING_MODEL=BAAI/bge-m3
EMBEDDING_DIM=1024

RERANKER_PROVIDER=siliconflow
RERANKER_MODEL=BAAI/bge-reranker-v2-m3

TRANSCRIPTION_PROVIDER=siliconflow
TRANSCRIPTION_MODEL=FunAudioLLM/SenseVoiceSmall
DIARIZATION_MODE=auto                     # 关闭 — SenseVoice 不返回 word 时间戳
```

### 🌐 海外 lite

```ini
OPENAI_API_KEY=sk-...

EMBEDDING_PROVIDER=openai
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIM=1536

RERANKER_PROVIDER=cohere                  # 或 jina（更便宜）
RERANKER_MODEL=rerank-multilingual-v3.0
COHERE_API_KEY=...

TRANSCRIPTION_PROVIDER=openai
TRANSCRIPTION_MODEL=whisper-1
DIARIZATION_MODE=auto                     # 纯远程时关闭，要 hybrid 看下文
```

### 💻 完全本地（隐私优先）

```ini
DEEPSEEK_API_KEY=sk-...                   # LLM 还是要打 API；其他全本地

EMBEDDING_PROVIDER=local
EMBEDDING_MODEL=BAAI/bge-m3                # 或 bge-large-zh-v1.5 / bge-small-en-v1.5 等
EMBEDDING_DIM=1024                         # 跟模型对齐

RERANKER_PROVIDER=local
RERANKER_MODEL=BAAI/bge-reranker-v2-m3     # 或 bge-reranker-large / bge-reranker-base

TRANSCRIPTION_PROVIDER=local_whisperx
TRANSCRIPTION_MODEL=Systran/faster-whisper-large-v3   # 或 medium / small / base
DIARIZATION_MODE=auto                      # → 本地 Pyannote 自动加载

HF_ENDPOINT=https://hf-mirror.com          # 中国镜像
```

然后 `python scripts/init_models.py` 把你配的模型预下载（脚本读 env，只下 local-* 的角色）。

要 100% 离线还得加一个本地 LLM（Ollama / vLLM）— 在 model_registry.py 的 `MODEL_PROFILES` 里新加一条 `api_base="http://localhost:11434/v1"` 的记录即可。

### 🔀 Hybrid（最佳折中）

远程 ASR 跑得快，本地 Pyannote 提供准确说话人标签：

```ini
TRANSCRIPTION_PROVIDER=openai
TRANSCRIPTION_MODEL=whisper-1              # 支持 word 级时间戳
DIARIZATION_MODE=pyannote                  # 强制本地 Pyannote
```

然后 `python scripts/init_models.py --only diarization`（只 17 MB）。

每次调用流程：
1. 音频 → OpenAI Whisper API → 文本 + word 级时间戳
2. 同样音频 → 本地 Pyannote → 说话人时间段
3. `whisperx.assign_word_speakers` 把 word 对齐到 speaker
4. 输出 → `**[Speaker 1]**: ... **[Speaker 2]**: ...` 的 markdown

如果选的 ASR provider 不支持 word 时间戳（比如硅基流动的 SenseVoiceSmall），系统会**自动降级**到单说话人输出，不会报错。

## Provider 目录（哪些模型用在哪）

下表是**建议**，不是硬编码。把任意 HF id / API 模型名填进 `*_MODEL`；只要 provider 支持就能跑。

### Embedding 厂商

| `*_PROVIDER` | 中国友好 | 推荐 `*_MODEL` 值 | 说明 |
|---|---|---|---|
| `local`       | ✓ | `BAAI/bge-m3` (1024) · `BAAI/bge-large-zh-v1.5` (1024) · `BAAI/bge-small-en-v1.5` (384) · `intfloat/multilingual-e5-large` (1024) | HF 下载，本地 CPU/GPU 跑 |
| `siliconflow` | ✓ | `BAAI/bge-m3` (1024) · `Pro/BAAI/bge-m3` (1024，付费 SLA) | 与本地 bge-m3 维度兼容 |
| `dashscope`   | ✓ | `text-embedding-v3` (1024) · `text-embedding-v2` (1536) | OpenAI 兼容模式 |
| `zhipu`       | ✓ | `embedding-3` (2048) · `embedding-2` (1024) | 2048 维 → Milvus 独立 collection |
| `openai`      |   | `text-embedding-3-small` (1536) · `text-embedding-3-large` (3072) | 支持 `dimensions=` 参数裁剪 |
| `jina`        |   | `jina-embeddings-v3` (1024) · `jina-embeddings-v2-base-zh` (768) | 与 bge-m3 维度兼容 |

**⚠ EMBEDDING_DIM 锁定**：Milvus collection 在第一次写入时维度就固定了。要么提前定好维度，要么准备好「drop + 重新入库」。

### Reranker 厂商

| `*_PROVIDER` | 中国友好 | 推荐 `*_MODEL` 值 | 说明 |
|---|---|---|---|
| `local`       | ✓ | `BAAI/bge-reranker-v2-m3` (1.5 GB) · `BAAI/bge-reranker-large` (1.1 GB) · `BAAI/bge-reranker-base` (530 MB) | HF 下载，cross-encoder |
| `siliconflow` | ✓ | `BAAI/bge-reranker-v2-m3` · `BAAI/bge-reranker-v2-gemma` | 同模型，无需本地下载 |
| `dashscope`   | ✓ | `gte-rerank` | OpenAI 兼容 /rerank |
| `jina`        |   | `jina-reranker-v2-base-multilingual` · `jina-reranker-m0` | 多语言 |
| `cohere`      |   | `rerank-multilingual-v3.0` · `rerank-english-v3.0` | 质量最佳，付费 |

Rerank 失败时会**降级**为返回未重排的 top-N — 远程不稳只是质量下降，不会让请求失败。

### ASR（转写）厂商

| `*_PROVIDER` | 中国友好 | 推荐 `*_MODEL` 值 | Word 时间戳 | 说明 |
|---|---|---|---|---|
| `local_whisperx` | ✓ | `Systran/faster-whisper-large-v3` · `medium` · `small` · `base` | ✓ | 内置 Pyannote 说话人分离 |
| `openai`         |   | `whisper-1` · `gpt-4o-transcribe` · `gpt-4o-mini-transcribe` | ✓ | whisper-1 ¥0.04/min |
| `siliconflow`    | ✓ | `FunAudioLLM/SenseVoiceSmall` · `openai/whisper-large-v3` |   | SenseVoice 中文优化、便宜 |
| `dashscope`      | ✓ | `paraformer-realtime-v2` · `paraformer-v2` |   | 中文 ASR、超快 |

**Word 时间戳**列 = 该 provider 是否能返回 word 级时间用于 hybrid Pyannote 对齐。✓ 表示 hybrid 模式可用；空白表示 hybrid 会自动降级到单说话人。

### LLM 厂商

LLM 是**用户级**配置（在「模型」页选）—— 同一部署里不同用户可以用不同模型。约 38 个 profile 在 `backend/app/core/model_registry.py` —— DeepSeek、OpenAI、Anthropic、Gemini、通义、Moonshot、智谱、MiMo、NVIDIA。新用户能看到全部 profile，只配自己实际用的 API key。

LLM 这里继续保留「(provider, model)」profile 模式，因为 LLM 需要更丰富的元数据（function calling 支持、上下文窗口、显示名）给前端 UI dropdown — 设计约束跟 embedding/rerank/ASR 不一样。

## 如何安全切换模式

| 场景 | 操作 |
|---|---|
| 还没数据 | 改 `.env`，重启即可 |
| 已有数据 + EMBEDDING_DIM 不变 | 重启；Milvus 继续工作 |
| 已有数据 + 维度变了 | 删 Milvus collection、重启、从 Library 重新入库知识。聊天历史 + 面试记录不受影响（在 Postgres） |

快速删 collection：

```bash
docker compose exec milvus-standalone /bin/sh -c \
  'curl -X POST localhost:9091/v1/collection/drop -d "{\"collection\":\"interview_copilot_rag\"}"'
```

## LLM provider 路由 —— 一条分支搞定所有厂商

所有支持的 LLM 厂商都走**同一个** `OpenAILike` 客户端。每个
`MODEL_PROFILES` 条目只是 `api_base` 不同：

| 厂商 | `api_base` |
|---|---|
| DeepSeek | `https://api.deepseek.com` |
| OpenAI | `https://api.openai.com/v1` |
| Anthropic | `https://api.anthropic.com/v1` *（OpenAI 兼容 shim）* |
| NVIDIA | `https://integrate.api.nvidia.com/v1` |
| Google Gemini | `https://generativelanguage.googleapis.com/v1beta/openai` |
| 阿里 DashScope | `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| 月之暗面、智谱、小米 MiMo、SiliconFlow、…… | 各自的 OpenAI 兼容 base URL |

所以切换 provider 完全就是 **(api_base, api_key, model_id)** 三元组的事。
没有特殊 wrapper、没有 LiteLLM、没有按厂商分支的代码。加新厂商 = 加
一条 `MODEL_PROFILES`，runtime 代码完全不增 `if`。

`backend/app/core/model_registry.py:_build_llm_instance` 实际就 6 行：

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

## 添加新厂商（开发者操作）

需要的厂商不在表里？比如 Voyage AI embedding：

```python
# backend/app/rag/embedding_registry.py — 加一条
PROVIDERS["voyage"] = EmbeddingProvider(
    kind="openai_compat",
    api_base="https://api.voyageai.com/v1",
    api_key_env="VOYAGE_API_KEY",
    label="Voyage AI",
)
```

然后 `.env`：
```ini
EMBEDDING_PROVIDER=voyage
EMBEDDING_MODEL=voyage-3-large
EMBEDDING_DIM=1024
VOYAGE_API_KEY=...
```

重启。其他文件不动。如果是流行厂商欢迎 PR。

## 添加新模型（用户操作）

不需要"添加"。你只需要**把模型名填进 `*_MODEL`**。该厂商支持就能跑；不支持就在第一次请求时返回 404，错误日志会很清楚。

## 实时模型发现（仅 LLM）

LLM 下拉框会自动加载每家厂商 `/v1/models` 接口当前公开的所有模型 ID。也就是说 — DeepSeek / OpenAI / Anthropic 一发布新模型，下次刷新「模型」页时就能看到，**不需要改代码**。

**工作原理**：

1. 每次「模型」页加载时，后端把策展的 `MODEL_PROFILES` 字典 + 每家厂商 `/v1/models` 的缓存结果合并返回
2. 发现结果缓存到 Redis 24 小时（key 形如 `model_catalog:v1:<provider>`）。部署后第一个加载的用户付发现耗时（每家约 1-2 秒），之后全部走缓存
3. 策展条目元数据**优先**（display name、描述、context window），策展中没有的自动发现条目使用合理默认值（128K context、假设支持函数调用）+ 携带 `auto_discovered: true` 标记

**手动触发刷新**：

- **Web UI**：模型页 → 点 **「刷新模型库」** 按钮（在 "Ping 测试" 旁）。一次性清缓存 + 重新发现
- **HTTP**：`POST /api/v1/models/refresh-catalog`（任何登录用户）
- **CLI**（适合 cron / CI 预热）：
  ```bash
  python scripts/refresh_models.py                 # 刷所有厂商
  python scripts/refresh_models.py --provider openai
  python scripts/refresh_models.py --json
  ```

**支持的厂商**：任何 `api_base` 提供 OpenAI 风格 `/v1/models` 的 provider — 也就是目录里所有聊天 LLM 厂商（OpenAI / Anthropic / DeepSeek / Moonshot / 通义 / 硅基流动 / 智谱 / xAI / Mistral）。没设 API key 的厂商默默跳过（无 key 也发现不了）。

**过滤启发**：发现代码会丢掉名字包含 `embedding` / `whisper` / `tts-` / `dall-e` / `rerank` 等关键字的模型 ID，避免聊天下拉框被非聊天模型污染。如果某个聊天模型恰好被误删（很少见），把它加到 `MODEL_PROFILES` 里就会以策展条目的形式显示。
