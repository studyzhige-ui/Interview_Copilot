# 新手上路

**二选一**：

- **[路线 A — API 轻量版](#路线-a--api-轻量版云端组件全包)**：每一个组件
  （LLM / embedding / reranker / ASR）都是云 API 调用。零本地模型下载、
  不需要 GPU。最便宜的端到端评估方式。
- **[路线 B — 本地版](#路线-b--本地版self-hosted-ml)**：embedding /
  reranker / Whisper / Pyannote 全部跑在本机硬盘上。LLM 仍走云。
  适合追求隐私 / 已经有 GPU 的人。

两条路任选一条走完，都会得到一个能注册 / 登录 / 聊天 / 模拟面试 /
分析的完整流程。

可选增强（真发邮件、LLM trace、网页搜索）和**完整坑点合集**
在文档末尾：
**[可选增强](#可选增强)** · **[常见坑点](#常见坑点)**。

---

## 前置依赖（两条路都要）

| 工具 | 最低版本 | 用途 |
|---|---|---|
| **Python 3.10 / 3.11 / 3.12** | — | 后端 + Celery。**不能用 3.13**（whisperx / pyannote 还没出 3.13 的 wheel）。 |
| **Node.js** | 20 | 前端构建 / dev server。 |
| **Docker Desktop** 或 `docker engine + compose` | 24 | Postgres / Redis / Milvus / MinIO。setup 之前必须先把 Docker 跑起来。 |
| **Conda**（Anaconda / Miniconda） | 近期版本 | Python 环境隔离。也可以用 `venv`。 |
| **Git** | 任意 | clone。 |
| **PowerShell 7**（`pwsh`） | 可选 | Windows 上比 PowerShell 5.1 干净。 |

GPU **只对路线 B 有用**（而且本地版也不强求 —— CPU 能跑 embedding 和
Whisper，只是慢）。

---

## 路线 A — API 轻量版（云端组件全包）

所有组件都走远端 API。需要**两类**厂商的 key：

- **一家 LLM 厂商**（推荐 DeepSeek —— 便宜、强、中国友好）。
- **一家 Embedding + Reranker + ASR 联合厂商**（推荐硅基流动 ——
  一把 key 三个角色全覆盖）。

### A1. clone + 建独立 Python 环境

```bash
git clone https://github.com/<your-org>/Interview_Copilot.git
cd Interview_Copilot

conda create -n interview-copilot python=3.11 -y
conda activate interview-copilot

# 验证：路径必须含 envs/interview-copilot/，不能是 base
python -c "import sys; print(sys.executable)"
```

### A2. 跑 setup，提示时选 API 轻量版

```powershell
.\scripts\setup.ps1            # Windows
```

```bash
./scripts/setup.sh             # Linux / macOS
```

脚本会：

1. 不在隔离环境就拒绝继续。
2. `pip install -r requirements.txt` —— 约 3GB wheel，时长看你网络。
3. 交互提示：*"[1] API-light  [2] Local-models"* —— 输入 `1`。
4. 复制 `.env.example.lite` → `.env`，自动生成 `SECRET_KEY`。
5. `docker compose up -d` 然后 `alembic upgrade head`。
6. `cd frontend && npm install`。

### A3. 申请 API key（每家约 5 分钟）

**LLM key —— 选一家（之后可以在「模型」页加更多）：**

| 厂商 | 申请地址 | 费用 |
|---|---|---|
| **DeepSeek** *（推荐）* | <https://platform.deepseek.com/api_keys> | ¥1/M tokens，需充值 |
| OpenAI | <https://platform.openai.com/api-keys> | $$ |
| Anthropic | <https://console.anthropic.com/settings/keys> | $$ |
| 阿里通义 | <https://dashscope.console.aliyun.com/apiKey> | 有免费额度 |
| 月之暗面 Kimi | <https://platform.moonshot.cn/console/api-keys> | 有免费额度 |
| 智谱 GLM | <https://bigmodel.cn/usercenter/apikeys> | 有免费额度 |

**Embedding + Reranker + ASR（最省事的一站式）：**

- **硅基流动** *（推荐）*：<https://siliconflow.cn> · 免费额度够轻量使用。

### A4. 填 `.env`

打开 `.env`，找到 **§ 4**，粘 LLM key：

```ini
DEEPSEEK_API_KEY=sk-...
```

再找 **§ 5**，粘一站式 key：

```ini
SILICONFLOW_API_KEY=sk-...
```

**就这两个**。其他字段已经预配置：所有 embedding / reranker / ASR
角色走硅基流动，LLM 走 DeepSeek。无任何本地模型下载。

### A5. 起后端

```powershell
.\scripts\start.ps1 -SkipFrontend
```

等日志里出现这三行：

```
[uvicorn] INFO ====== Interview Copilot startup sequence complete ======
[uvicorn] INFO: Application startup complete.
[celery] celery@<hostname> ready.
```

这一步出问题去看 [常见坑点](#常见坑点)（特别是 **G1、G2、G3**）。

### A6. 起前端

另开一个 tab：

```powershell
.\scripts\start.ps1 -SkipBackend
```

看到 `vite -> http://localhost:5173` 就打开这个地址。

### A7. 注册 + 聊天

点 **注册**，填邮箱 / 用户名 / 密码，点 "发送验证码"。

**验证码会打到后端终端**（你还没配 SMTP）：

```
[email] SMTP not configured — body printed below.
  Body:    您的验证码是: 123456
```

复制 6 位数字填进去。登录。右侧面板就是聊天框，发条消息，应该看到
DeepSeek 流式返回。

**路线 A 完成。** 想要真发邮件 / LLM trace 之类，看 [可选增强](#可选增强)。

---

## 路线 B — 本地版（self-hosted ML）

Embedding / reranker / Whisper / Pyannote 全部下载到本机硬盘、本地跑。
LLM 仍走云（默认 DeepSeek）。

### B1. clone + 建独立 Python 环境

跟 A1 一样。

### B2. 跑 setup，提示时选本地版

跟 A2 一样，但提示时输入 **`2`** —— 复制 `.env.example`（不是 `.lite` 那个）。

### B3. 申请 LLM key（只要这一个）

跟 A3 的 LLM 列表一样。**不需要**硅基流动 / Jina / Cohere —— 那些角色
本地跑。

### B4. 填 `.env`

打开 `.env`，**§ 4**：

```ini
DEEPSEEK_API_KEY=sk-...
```

`.env.example` 已经预设 `EMBEDDING_PROVIDER=local`、
`RERANKER_PROVIDER=local`、`TRANSCRIPTION_PROVIDER=local_whisperx` 和
对应的 model id。其他不用改。

### B5. 下载本地模型（约 5GB）

```bash
python scripts/init_models.py --dry-run     # 看清单 + 实时大小（HF API 查询）
python scripts/init_models.py               # 真下载
```

期望 dry-run 输出（你的大小可能略有差异）：

```
      embedding: BAAI/bge-m3                                (~1.06 GB)
       reranker: BAAI/bge-reranker-v2-m3                    (~1.08 GB)
        whisper: Systran/faster-whisper-large-v3            (~2.88 GB)
    diarization: pyannote-community/speaker-diarization-community-1   (~32 MB)
```

`.env` 默认 `HF_ENDPOINT=https://hf-mirror.com`（国内镜像）。加起来约
5GB。支持字节级断点续传，下载卡了直接重跑。

### B6. 起后端

```powershell
.\scripts\start.ps1 -SkipFrontend
```

第一次启动会把每个本地模型加载进内存。看你 GPU 配置，"startup sequence
complete" 出现需要 15-30 秒。

### B7. 起前端

```powershell
.\scripts\start.ps1 -SkipBackend
```

### B8. 注册 + 聊天 + 试真录音上传

跟 A6 / A7 一样 —— 注册时验证码看后端终端、登录、聊天能用。

**本地版的额外能力：** 录音分析链路完全本地。去**复盘 → 新建面试 →
上传音视频**，传一份 mp4/m4a/wav 试试。WhisperX 转写 + Pyannote 标说话人
+ LLM 生成分析报告。

**路线 B 完成。**

---

## 可选增强

每一项都是**可选的**，核心流程不需要。

### 真发邮件（SMTP）

替换"验证码 → 后端 stdout"为真发邮件。填 `.env` **§ 3.5**：

```ini
# Gmail 示例 —— 在 https://myaccount.google.com/apppasswords 生成
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=you@gmail.com
SMTP_PASSWORD=abcd efgh ijkl mnop      # 16 位应用专用密码，不是登录密码
SMTP_FROM=Interview Copilot <you@gmail.com>
SMTP_USE_TLS=true
```

无论 SMTP 是否配，验证码 body **都会**镜像到后端日志便于追溯。

163 / QQ / Outlook 配置见 `.env.example` § 3.5 内联注释。

### LangSmith —— 看每次 LLM 调用

在 <https://smith.langchain.com> 注册、生成 API key，填 `.env` § 3.6：

```ini
LANGSMITH_API_KEY=lsv2_pt_...
LANGSMITH_PROJECT=Interview Copilot
LANGSMITH_TRACING=true
```

重启后端。每次聊天都会在 LangSmith UI 显示完整 prompt / response /
延迟 / token 数。

### Agent 联网搜索 —— Tavily

在 <https://tavily.com/> 注册（免费 1000 次/月），填 `.env`：

```ini
TAVILY_API_KEY=tvly-...
```

重启。Agent 模式的 `web_search` 工具激活，模型用 function calling
自己决定何时调用。

### 用户级模型路由（「模型」页）

登录后侧栏 **模型** 页：每个用户保存自己的 API key（Fernet 加密入
DB），给三个角色（主 / Agent / 模拟面试）各选模型。用户级 key 优先
级**高于** `.env`。

### Hybrid 模式（云 ASR + 本地 Pyannote）

兼顾两边：云 ASR 给 word 级时间戳，本地 Pyannote 做说话人分离 / 不挤
GPU。改 `.env`：

```ini
TRANSCRIPTION_PROVIDER=openai
TRANSCRIPTION_MODEL=whisper-1
DIARIZATION_MODE=pyannote
```

只下小的 Pyannote 模型：

```bash
python scripts/init_models.py --only diarization
```

---

## 常见坑点

按容易出错的位置排序。

### G1. `pwsh scripts/start.ps1` 看到的是 base Python，明明 prompt 是 `(env)`

`pwsh` 前缀**新开一个**子 pwsh 进程。子进程会加载 `$PROFILE`，里面
的 conda init hook 可能把 PATH 重置回 base。所以父 prompt 显示
`(your-env)`，但子进程跑的是 base。

**修复：** 用 `.\` 形式在当前 shell 里跑：

```powershell
.\scripts\start.ps1
```

ExecutionPolicy 拦着的话一次性放开：

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned -Force
```

### G2. `conda activate <env>` 没真的切 Python

你建 env 时 `conda create -n NAME` **没**带 `python=X.Y`。conda 只建
了空元数据目录，没装 Python，激活后悄悄 fallback 到 base。

**修复：** 删了重建，加上版本：

```powershell
conda env remove -n <env> -y
conda create -n <env> python=3.11 -y
conda activate <env>
pip install -r requirements.txt
```

### G3. Python 3.13 装 whisperx / pyannote 失败

这俩库还没出 3.13 wheel。用 3.10 / 3.11 / 3.12。setup 脚本显式拒绝 3.13。

### G4. 不要装到 base Python

Setup 脚本拒绝把 ~3GB ML 依赖装到没隔离的 Python 上。故意的 ——
torch + whisperx 会跟你 base 里别的项目互踩。

### G5. 聊天返回 401「当前模型的密钥无效」，但 `.env` 里 key 是有效的

Key 解析顺序：

1. `user_model_credentials` 表里 `(user, provider)` —— 「模型」页设置的
2. fallback 到 `os.environ[provider.api_key_env]`

DB 里的错 key **会覆盖** `.env` 里的对 key。两种处理：「模型」页删
那条（已配置徽标旁边垃圾桶图标），或清非 admin 数据：

```bash
python scripts/wipe_non_admin.py --admin-username <你> --dry-run
python scripts/wipe_non_admin.py --admin-username <你> --yes
```

### G6. 聊天 401 + 当前模型显示的厂商我没配过 key

你的用户级模型选择指向了一个 profile，但对应的 `api_key_env` 在
`.env` 里没填。两种修法：

- **模型页**（推荐）：左侧导航 → 模型 → 给 primary / agent / mock-interview
  选一个你确实配了 key 的厂商的 profile，保存。
- **DB 级重置**：把选择列清空，下次聊天就回退到 `ROLE_DEFAULTS`：
  ```sql
  UPDATE users SET model_selection_json = NULL WHERE username = '<你>';
  ```

用户级选择存在 `users.model_selection_json`（Postgres 列），不再有磁盘
JSON 文件。Profile id 是 `provider/model` 形式 ——
比如 `deepseek/deepseek-chat`、`openai/gpt-4o-mini` —— 由实时
`/v1/models` 目录填充。

### G7. 前端每个请求都 `http proxy error: EACCES`

后端没真起来。看后端 tab，通常 startup crash。看到 `Application startup
complete` 之前，前端没东西可代理。

### G8. 后端卡在 `[2/5] Initializing reranker...`

HF 第一次慢下载。看 `ls -la data/cache/huggingface/ | wc -l`，应该
在涨。公司代理后面设 `HTTP_PROXY` / `HTTPS_PROXY`，或改
`HF_ENDPOINT`。

### G9. 后端崩：`Reranker model 'X' is not in the local cache`

报错信息**已经**列出你 cache 里实际有哪些 vs `.env` 想要哪个。要么
改 `.env` 用已 cache 的，要么：

```bash
python scripts/init_models.py
```

### G10. `Database is not migrated`

```bash
python -c "from alembic.config import CommandLine; CommandLine().main(['upgrade','head'])"
```

### G11. "已完成注册的邮箱不会再收到验证码" banner

反账号枚举防御：用已注册的 email 试注册会返回相同的"已发送"形状但
不真发邮件。注意**"已完成注册"** 指 `users` 表里有那行 —— 仅点过
"发送验证码"不算。

### G12. `.env` vs `.env.docker` 各被谁读

- `.env` 由 **Python**（uvicorn / celery / alembic / init_models）读。
- `.env.docker` 由 **`docker-compose`** 读，用于初始化 Postgres + MinIO
  容器。

两边共享 Postgres / MinIO 凭据。改了 `.env.docker` 必须同步更新
`.env` 的 `DATABASE_URL`（和可选的 `*_DOCKER` overrides）。

### 还有别的

→ 卡住的话，开个 GitHub issue，附上后端日志尾部（启动序列 + 报错的接口）
和脱敏后的 `.env`，一般就能定位。

---

## 停止

每个 tab 各自 `Ctrl+C`。还想把 docker 也停了：

```powershell
.\scripts\stop.ps1
```

加 `-Volumes` / `--volumes` 还会删 Postgres / Milvus / MinIO 的数据卷
——**会清空所有用户、录音、索引**。

---

## 各组件跑在哪

```
.env             ← Python 读（uvicorn / celery / alembic / init_models）
.env.docker      ← docker-compose 读，初始化 Postgres + MinIO 容器

uvicorn (8080)        ← HTTP API + WebSocket（流式聊天）
celery worker         ← 异步任务（转写 / 入库 / 分析）

docker:
  postgres            ← 关系数据（用户、会话、QA、上传记录）
  redis               ← Celery broker + JWT 黑名单 + 缓存
  milvus              ← RAG + memory 向量库
  minio               ← 上传文件（简历、录音、头像）
```
