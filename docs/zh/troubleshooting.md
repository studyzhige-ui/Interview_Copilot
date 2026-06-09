# 故障排查

按**启动顺序**分组的常见故障。每段都给出症状 + 原因 + 解决办法。

如果某节没解决你的问题，把日志里的精确报错文本拿去 `git log` 里搜 — 大部分影响生产的 bug 都有 commit 信息提到症状。

---

## Python 环境 / Windows shell

### `pwsh scripts/start.ps1` 显示 base Python，明明 prompt 已经是 `(env)`

父 shell 已经 conda activate 过了，但脚本看到的还是 base Python + 包版本错的。

根因：`pwsh script.ps1`（带 `pwsh` 前缀）会**新开**一个 pwsh 子进程。
子进程加载 `$PROFILE`，里面的 conda init hook 可能把 PATH 重置回 base。
所以即便父 prompt 是 `(your-env)`，子进程实际是 base 激活态。

**修复：** 去掉 `pwsh` 前缀，用 `.\` 形式在当前 shell 里跑：

```powershell
.\scripts\start.ps1 -SkipFrontend
```

ExecutionPolicy 拦着的话一次性放开签名脚本：

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned -Force
```

### `conda activate <env>` 没真的切 Python

你执行 `conda create -n NAME` **没**带 `python=X.Y`。conda 建了一个元数据
空目录，里面没 Python。激活后悄悄回退到 base。

**修复：** 删了重建，加上版本：

```powershell
conda env remove -n <env> -y
conda create -n <env> python=3.11 -y
conda activate <env>
python -c "import sys; print(sys.executable)"   # 路径必须含 envs/<env>/
pip install -r requirements.txt
```

### Python 3.13：`pip install -r requirements.txt` 在 whisperx / pyannote 上挂

这俩库还没出 3.13 wheel。用 3.10 / 3.11 / 3.12。setup 脚本会显式拒绝 3.13。

### 聊天返回 401「当前模型的密钥无效」，但 `.env` 里 key 是有效的

API key 解析顺序：

1. `user_api_keys` 表里 `(user, provider)` 那条（DB 内 Fernet 加密，
   通过前端「模型」页设置）
2. fallback 到 `os.environ[provider.api_key_env]`

所以 DB 里的错 key 会**覆盖** `.env` 里的对 key。两种确认方式：

```sql
-- 当前用户存了哪些厂商的 key？
docker exec interview_copilot_db psql -U postgres -d interview_copilot -c \
  "SELECT user_id, provider, key_masked FROM user_api_keys WHERE user_id = 'admin';"
```

**修复：** 在「模型」页删掉那条（每张厂商卡片"已配置"徽标旁边有垃圾桶
图标），或者清掉非 admin 数据：

```bash
python scripts/wipe_non_admin.py --admin-username <你> --dry-run    # 预览
python scripts/wipe_non_admin.py --admin-username <你> --yes        # 真删
```

### 聊天 401 + 活动模型显示的是我没配过的厂商

用户级模型选择（`users.model_selection_json` 列）指向了一个 profile，
但对应的 `api_key_env` 在 `.env` 里没填，用户级 key 也没存。最常见：
在「模型」页给 primary 选了小米 MiMo，但 `MIMO_API_KEY` 是空的。

**修复（推荐）：** 前端「模型」页，给 primary / agent / mock-interview
选一个你确实配了 key 的厂商的 profile，保存即可。

**修复（DB 级重置）：** 把选择列清空，下次聊天就回退到 `ROLE_DEFAULTS`：

```sql
docker exec interview_copilot_db psql -U postgres -d interview_copilot -c \
  "UPDATE users SET model_selection_json = NULL WHERE username = '<你>';"
```

Profile id 是 `provider/model` 形式 —— 比如 `deepseek/deepseek-chat`、
`openai/gpt-4o-mini`。完整集合来自实时 `/v1/models` 目录缓存（在
「模型」页可以手动刷新）。

---

## 安装 / pip

### Windows 上 `torchcodec` 缺符号

```
DLL load failed: aoti_torch_aten_narrow not found
```

**修复**：
```bash
pip uninstall torchcodec
```
Pyannote 会回退到 `torchaudio`，工作正常。

### `slowapi` 没装

后端日志说 `slowapi not installed`。

**修复**：
```bash
pip install slowapi==0.1.9
```
（已经在 `requirements.txt` 里 — 只在虚拟环境过期时会出现这问题。）

---

## Docker / 基础设施

### Postgres "connection refused"

```
psycopg2.OperationalError: connection to server at "localhost" (::1), port 5432 failed
```

**检查**：
```bash
docker compose ps                     # postgres 是否 healthy？
docker compose logs db | tail -30     # 看错误
```

最常见原因：宿主机已经有一个 Postgres 在占 5432 端口。要么停掉它，要么改 `docker-compose.yml` 的宿主端口为 `127.0.0.1:5433:5432`，并相应更新 `DATABASE_URL`。

### Milvus "service is not ready"

Milvus 启动后需要 30–60 秒才会 healthy。耐心等或：
```bash
docker compose ps milvus-standalone   # 等到显示 "(healthy)"
```

如果一直不 healthy，检查 `milvus-etcd` 和 `milvus-minio` 是不是也 healthy（Milvus 依赖这两个）。

### MinIO bucket 找不到

```
botocore.exceptions.ClientError: The specified bucket does not exist
```

`minio-create-bucket` 这个一次性服务应该建好了。如果没建：
```bash
docker compose run --rm minio-create-bucket
```

---

## 数据库迁移

### `Database is not migrated. Run alembic upgrade head`

字面意思。**从项目根**（不是 `backend/`）跑：
```bash
alembic upgrade head
```

### `Database migration is out of date (X != Y)`

你拉了新代码但没迁移。同上。

### `Router.__init__() got an unexpected keyword argument 'on_startup'`

FastAPI / Starlette 版本不匹配。仓库锁了 `fastapi==0.135.2`，如果你让 pip 拉了更新版本，会带来一个移除了 `on_startup` 的 Starlette。

**修复**：
```bash
pip install -r requirements.txt --force-reinstall
```

---

## 后端启动

### `SECRET_KEY is set to an insecure default`

你的 `.env` 要么写了字面占位字符串，要么根本没 `SECRET_KEY`（Phase 2 删了代码里的 fallback）。

**修复**：
```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
# 把输出粘到 .env 的 SECRET_KEY=...
```

### `RAG embedding init failed: ... requires SILICONFLOW_API_KEY`

你设了 `EMBEDDING_PROVIDER=siliconflow` 但没填 `SILICONFLOW_API_KEY`。要么填 key 要么换 provider：
```ini
EMBEDDING_PROVIDER=local       # 回退到本地模型
```

### `Whisper model 'X' is missing. Run python scripts/init_models.py`

你在 full 模式但没跑过 `init_models.py`。跑一次：
```bash
python scripts/init_models.py
```

如果你是 lite 模式（`TRANSCRIPTION_PROVIDER=siliconflow` 或类似）就不该出现这个错 — 检查你的 `.env` 是不是真的设了正确 provider 没拼错。

### 后端在 `Initializing reranker...` 卡住

通常是首次从 HuggingFace 慢速下载。盯着看：
```bash
ls -la data/cache/huggingface/ | wc -l   # 应该会涨
```

如果在公司代理后面，设 `HTTP_PROXY` / `HTTPS_PROXY` 或换 HF 镜像 `HF_ENDPOINT=https://hf-mirror.com`。

---

## 前端

### `tsc` 报 "Type error in node_modules"

`node_modules` 过期：
```bash
cd frontend
rm -rf node_modules package-lock.json
npm install
```

### 登录成功但每个 API 都返回 401

token 发出去但后端拒了。检查 access token 的 `jti` 字段 — Phase 2 强制要求 jti 存在：
```bash
# 浏览器 devtools → Application → Local Storage → access_token
# 把中间段（base64url）解码 — 应该包含 "jti": "..."
```

如果没 `jti`，说明你用的是 Phase 2 之前签发的 token。**登出 + 重新登录**就能拿到新的。

### WebSocket 连上立刻断开（`code: 1008`）

`bearer` 子协议握手失败。常见原因：

1. JWT 过期或被撤销（登出后再登入）
2. 浏览器和后端之间的 nginx 把 `Sec-WebSocket-Protocol` header 吃掉了。生产 `nginx/conf.d/frontend.conf` 已经有正确转发；如果你写了自己的 nginx 配置，加上：
   ```
   proxy_set_header Sec-WebSocket-Protocol $http_sec_websocket_protocol;
   ```

### 头像上传 502 报「头像存储不可用」

后端进程访问不到 S3 / MinIO。检查：
```bash
docker compose ps minio                       # healthy?
curl http://localhost:9000/minio/health/live  # 200?
```

`.env` 里 `AWS_ENDPOINT_URL` 必须指向 MinIO。本地默认是 `http://localhost:9000`。

---

## Celery worker

### worker 立刻退出，报 `--pool=solo` 错

PowerShell 的引号转义坑你。现在并行跑两个 worker（一重一轻 ——
见 `docker-compose.yml` 的 `worker-transcription` / `worker-light`
服务）。每个一个终端：

```powershell
# 终端 1 —— 转写 worker（加载 Whisper，~1.5 GB GPU）
celery -A app.worker.celery_app.celery_app worker --loglevel=info --pool=solo --queues=transcription --hostname=transcription@%h

# 终端 2 —— 轻 worker（记忆梦境、文档入库；不加载 Whisper）
celery -A app.worker.celery_app.celery_app worker --loglevel=info --pool=threads --concurrency=4 --queues=default --hostname=light@%h

# 终端 3 —— beat 调度器（每天 03:30 Asia/Shanghai 触发夜间梦境扫描）
celery -A app.worker.celery_app.celery_app beat --loglevel=info
```

每条单行、精确拼写。不要用管道或变量替换搅乱 `--pool=solo`。

### 任务入队但不执行

要么 worker 没起来，要么 broker URL 在 API 和 worker 两边不一致。两边都该读同一个 `.env` 的 `REDIS_URL`。验证：
```bash
docker compose exec redis redis-cli LRANGE celery 0 -1
```
（worker 在消费时应该是空的。）

### 长任务执行到一半被重新派发

Phase 1 把分析任务的 `visibility_timeout` 设到 3700 秒、`task_time_limit` 1800 秒。如果你的自定义任务跑超过 3700 秒，就要在 `backend/app/worker/celery_app.py` 里调大 visibility_timeout，对应任务的 `task_time_limit` 装饰器也要调。

---

## 模拟面试

### 「简历分析超时 30s」→ fallback 到硬编码的 RESTful 问题

Phase 1 已经修了 — 简历解析路径不再调 LLM，只抽文本。如果还遇到，多半是你的 `.env` 里 `DEEPSEEK_API_KEY` 是空的或错的。先去试一次普通聊天验证；聊天能走说明 mock 也能走。

### 「你有一个未完成的模拟面试」一直消不掉

Phase 2 的修复会自动清理 0-Q&A 的空壳会话。如果你跑的是旧代码，要么 git pull 拿最新，要么手动清：
```bash
docker compose exec db psql -U postgres -d interview_copilot -c \
  "DELETE FROM chat_sessions WHERE session_type='mock_interview' AND turn_count=0;"
```

### Whisper 转写返回挪威语 / 错误语言

WhisperX 在某些音频上语言检测会默认成 `nn`（挪威语）。Phase 1 把每次调用都强制 `language="zh"`。如果你用本地 whisperx 想换默认语言，编辑 `audio_transcription_service.py:_run_whisperx_sync` — `transcribe(audio, batch_size=16, language="zh")`。

---

## 性能

### 多 worker uvicorn 下报 "QueuePool limit reached"

PG max_connections 太小。两条路：
1. 调小 `.env` 里的 `DB_POOL_SIZE`（默认 20 意味着 4 worker × 40 = 160 连接）
2. 调大 postgres.conf 里的 `max_connections` — 见 [postgres-tuning.md](postgres-tuning.md)

### 「厂商刚发了新模型，下拉框里看不到」

模型目录每 24 小时自动从每家厂商的 `/v1/models` 重新拉一次。强制刷新有三种方式：

- **Web**：模型页 → 点 **「刷新模型库」** 按钮
- **CLI**：`python scripts/refresh_models.py`
- **HTTP**：`POST /api/v1/models/refresh-catalog`

刷新后还是没出现，要么是厂商还没把这个模型公开到 `/v1/models`，要么是被 vendor 适配器的"仅聊天"过滤器删掉了（如名字含 `embed` / `whisper` / `tts-` / `dall-e` / `realtime` 等）。后者解决办法：改 `backend/app/services/model_sources/vendors/<vendor>.py` 里的 `_NON_CHAT_HINTS` 列表；如果想给它单独的显示名 / 优先级，再到 `backend/app/services/model_sources/curated.py` 加一条 CURATED。

### 「我改了 .env.docker 的 POSTGRES_PASSWORD，API 连不上数据库」

两个地方存凭据，必须保持一致：

1. `.env.docker` → 启动 postgres 容器时初始化用
2. `.env` → API/worker 用这个 URL 连数据库

改了 `.env.docker` 的密码，同样要在 `.env` 里加覆盖：
```ini
DATABASE_URL_DOCKER=postgresql://新用户:新密码@db:5432/interview_copilot
```
（host 模式开发时 uvicorn 跑在宿主机，`DATABASE_URL` 也要同步修改，但 host 是 `localhost:5432`。）

改完之后必须**删 postgres 数据卷**让新密码生效 — 否则老卷里存的还是旧密码，新容器收到 env 也不会改已有数据：
```bash
docker compose down
docker volume rm interview_copilot_pgdata
docker compose up -d
alembic upgrade head        # 在干净的 DB 上重建 schema
```

### `/models/ping` 巨慢

每个 profile 都 ping 一遍它的 provider。280+ 个模型，如果有 10 个 key 错（每次超时 10 秒），总计 ~分钟级。要么：
- 只配置你实际用的 vendor key（没 key 的 vendor 在 "no key" 短路，不会真发请求）
- 或者在模型页用"显示更多厂商"把不用的 vendor 卡片关掉，ping 就不会包含它

### Embedding 巨慢，没 GPU

你跑在 CPU 上。要么：
- 切到 lite 模式（`EMBEDDING_PROVIDER=siliconflow`）
- 或者 full 模式下用更小模型：`EMBEDDING_MODEL=BAAI/bge-small-en-v1.5` + `EMBEDDING_DIM=384`

---

## 编码（Windows 专属）

### 控制台显示 `��` 而不是中文 / emoji

Windows GBK 终端解不了 UTF-8。dev 脚本已经设了 codepage；如果你手动启动：
```powershell
chcp 65001
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'
```

### `init_models.py` 因为 unicode 箭头崩

Phase 5+ 把 `⏭` / `✓` / `⬇` 替换成 `[skip]` / `[ok]` / `[get]` 让它能在 GBK 终端跑。如果还报 unicode crash，你的仓库不够新。git pull。

---

## 还是没解决？

读出问题组件的结构化日志：
```bash
# 后端
tail -200 logs/backend-*.log

# Celery（用 start.ps1 -SkipFrontend 时在同一个 log 里）
docker compose logs <服务名>
```

提交 issue 时附上：
- 模式（lite / full / hybrid）
- 日志里的精确报错（不要截图）
- `docker compose ps` 输出
- `pip list | grep -E "(fastapi|sqlalchemy|llama-index|whisperx)"` 输出
