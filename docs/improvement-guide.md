# Interview Copilot 改进方案完整讲解

> 写给基础尚在打底的读者：本文每个改进项都先解释**底层概念**，再说为什么这块代码会有问题，最后给出**怎么改**和**怎么验证**。
> 你不需要按顺序读，但建议先看 **Part 1 基础概念**，后面所有改进都建立在这些概念之上。

---

## 阅读说明

每个改进项的结构固定如下：

```
### 改进 #N · 标题
  📚 概念铺垫     — 必备的底层知识
  🔍 当前状态     — 现在代码里是什么样
  ⚠ 为什么是问题  — 不修会怎样
  🛠 改进方案     — 怎么改（前后对比）
  ✅ 如何验证     — 改完怎么知道好了
  ⏱ 难度估时      — S（半天内）/ M（1-2 天）/ L（一周左右）
```

**优先级**：
- 🔴 P0 — 上线前必须改（安全或正确性）
- 🟠 P1 — 性能/稳定性，重要但不阻断上线
- 🟡 P2 — 代码质量，长期收益
- 🟢 P3 — 工程化锦上添花

---

# Part 1 · 必备基础概念

读改进项之前先了解这些底层概念，后面提到时不再重复展开。

## 1.1 HTTP 请求生命周期与反向代理

当用户在浏览器点"发送"按钮，发生了什么：

```
浏览器
  │  ① 发起 HTTPS 请求到 yourdomain.com
  ▼
DNS 解析 → 服务器 IP
  │
  ▼
[Nginx 反向代理]  ← 公网入口（80/443 端口）
  │  ② TLS 终结（解密 HTTPS）
  │  ③ 添加/检查 HTTP 头
  │  ④ 限流、IP 黑名单第一道墙
  │  ⑤ 把请求转发给应用
  ▼
[FastAPI 应用]    ← 内网（8080 端口）
  │  ⑥ JWT 鉴权
  │  ⑦ 路由分发到具体 endpoint
  │  ⑧ 执行业务逻辑
  ▼
[Postgres / Redis / Milvus / OpenAI 等]
```

**反向代理（Reverse Proxy）** 就是"前台接待"：
- 公网只暴露 nginx 一个端口，应用躲在后面
- nginx 处理 TLS、压缩、缓存、安全头这些通用工作
- 应用只关心业务

**为什么不让应用直接对外**：应用专注业务、不擅长（也不应该）处理 TLS 证书、限流、安全头这些边界关注点。让 nginx 这种久经考验的工具来做。

---

## 1.2 同步 vs 异步（asyncio / event loop）

这是 Python 后端最容易踩坑的概念。

### 同步代码（阻塞）

```python
def fetch_user(user_id):
    result = db.query(...).first()   # ← 这一行执行时，整个线程"停住"
    return result                     #   等数据库返回（可能几毫秒到几百毫秒）
```

期间 CPU 闲着，但**这个线程不能干别的事**。

### 异步代码（非阻塞）

```python
async def fetch_user(user_id):
    result = await async_db.fetch_one(...)   # ← 这里"挂起"当前协程
    return result                             #   线程去处理别的请求
```

`await` 这一行不是停住线程，而是告诉 **event loop**：
> "我在等 I/O，你先去跑别的协程，等数据库返回了再叫我醒过来。"

### Event Loop 是什么

Event Loop 是一个"单线程调度器"：

```
┌─────────────────────────────────────┐
│  Event Loop（单线程）                │
│                                      │
│  待办列表:                            │
│   [请求A 在等 DB]                    │
│   [请求B 准备发响应]      ← 现在轮到这个
│   [请求C 在等 OpenAI]                │
│                                      │
│  循环：找一个"可以推进"的协程跑一会儿  │
└─────────────────────────────────────┘
```

只要每个协程都在 I/O 等待时 `await`，event loop 就能在 1 个线程里同时服务上千个请求。

### ⚠ 致命陷阱：在 async 函数里调用同步阻塞代码

```python
async def my_endpoint(db: Session):
    user = db.query(User).first()   # ← 同步 ORM 调用，event loop 被卡住！
    db.commit()                      # ← 也是同步阻塞
    return user
```

这一行执行时，event loop 整个停转。**所有其他用户的请求都被堵在队列里**，直到这次 DB 查询结束。高并发下完全失去 async 的意义。

### 解决方法

- **方案 A（短期）**：把同步代码包到 `asyncio.to_thread()`，扔到线程池跑：
  ```python
  user = await asyncio.to_thread(lambda: db.query(User).first())
  ```
- **方案 B（彻底）**：换成 async ORM（`sqlalchemy.ext.asyncio`）
- **方案 C（回避）**：endpoint 直接用 `def`（不是 `async def`），FastAPI 会自动放到线程池里跑

---

## 1.3 容器与 Docker

**容器**可以理解成"打包了运行环境的可执行文件"。你写完代码，把它和 Python、依赖、配置一起打成一个 image，到哪儿都能跑。

```
Dockerfile  →  docker build  →  Image  →  docker run  →  Container（运行中）
（菜谱）         （做菜）         （成品）                 （正在吃）
```

### 容器内的"用户"

容器里有完整的 Linux 用户系统。**默认所有进程以 root 跑**，权限最大。

```dockerfile
# 默认情况
FROM python:3.13-slim
COPY . /app
CMD ["python", "app.py"]
# ↑ 这个 python 进程是 root 跑的
```

**为什么 root 是问题**：如果你的应用被攻击（比如反序列化漏洞、命令注入），攻击者能在容器里以 root 干任何事——读所有文件、改系统配置、安装恶意软件。如果容器又有 Docker socket 挂载或者 `--privileged`，可以逃逸到宿主机。

### 最佳实践

```dockerfile
RUN groupadd -r app && useradd -r -g app app
USER app
CMD ["python", "app.py"]
# ↑ 现在这个 python 进程是 app 用户跑的，权限有限
```

---

## 1.4 JWT 认证基础

JWT = JSON Web Token。一段被服务器签名过的字符串：

```
eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJhbGljZSIsImV4cCI6MTcwMH0.signature
└─────header─────┘  └─────────payload──────────────────┘ └────签名────┘
```

- **Header**：算法名（HS256、RS256 等）
- **Payload**：用户身份 + 过期时间（`exp`）等
- **签名**：用服务器 `SECRET_KEY` 对前两部分做 HMAC

### 认证流程

```
登录:
  用户 → POST /login (username, password)
       ← 200 { "access_token": "eyJ..." }

后续请求:
  用户 → GET /api/me   Header: Authorization: Bearer eyJ...
       ← 服务器验签 + 检查 exp → 200 用户信息
```

服务器**不需要查数据库**就能验证 token（只要验签和 exp），所以扩展性好。

### SECRET_KEY 的关键性

`SECRET_KEY` 用来签 token。如果别人知道了它：
- 他们可以伪造任意用户的 token
- 等同于拿到了"万能钥匙"

所以 `SECRET_KEY` 必须：
1. 随机生成（不是 "change-me-for-local-development" 这种占位）
2. 绝不进版本库
3. 生产环境与开发环境用不同的值
4. 泄露后立即轮换

---

## 1.5 CORS 同源策略

浏览器为了安全，默认禁止"跨域请求"：
- 你访问 `frontend.com`
- 这个页面上的 JS 想 POST 到 `api.different-domain.com`
- 默认会被浏览器拦截

CORS（Cross-Origin Resource Sharing）就是"白名单制度"——后端在响应头里告诉浏览器："我允许从这些 origin 过来的请求"：

```
Access-Control-Allow-Origin: https://frontend.com
Access-Control-Allow-Methods: GET, POST
Access-Control-Allow-Headers: Authorization, Content-Type
```

### `allow_methods=["*"]` 为什么不好

允许任意方法看似方便，但如果你的 origin 白名单不严格、又允许 credentials（cookie），攻击者可以从子域名诱导浏览器发任意 verb 的请求（包括 DELETE）。**明确列出**用到的方法是更安全的做法。

---

## 1.6 HTTP 安全响应头

这些头是浏览器层的"防线"，告诉浏览器怎么对待你的页面：

| 头 | 作用 |
|---|---|
| `Strict-Transport-Security` | 强制 HTTPS（HSTS），防止中间人降级到 HTTP |
| `X-Frame-Options: DENY` | 禁止页面被 iframe 嵌入，防点击劫持 |
| `X-Content-Type-Options: nosniff` | 禁止浏览器猜测 MIME 类型，防 XSS |
| `Referrer-Policy` | 控制 Referer 头泄露的信息量 |
| `Content-Security-Policy` | 限制哪些 JS/CSS/图片来源能加载，强力防 XSS |

它们应该在**两个地方都加**：
1. 应用层（FastAPI middleware）—— 防止直接访问应用（绕过 nginx）
2. nginx 层 —— 防止应用配错；nginx 加是"最后一道防线"

---

## 1.7 文件上传的安全

用户上传文件时，**永远不能相信客户端的 `Content-Type` 头**。

举例：攻击者上传 `evil.exe` 但改了请求头声称是 `image/jpeg`。如果你只看头：
- 存到 S3 → 后续可能被当 PDF 渲染、当 JS 解析
- 处理流程崩溃 → 拒绝服务
- 内嵌 payload → 钓鱼分发

### Magic Bytes（魔数）

文件的**真实类型**藏在文件开头几个字节里：

| 文件类型 | 前几个字节（hex） |
|---|---|
| PDF | `25 50 44 46` （"%PDF"） |
| PNG | `89 50 4E 47` |
| JPEG | `FF D8 FF` |
| ZIP/DOCX/XLSX | `50 4B 03 04` |
| MP3 | `49 44 33` （"ID3"）或 `FF FB` |

读前 16 字节判断真实类型，与声明类型对比——这就是 magic-byte 校验。Python 用 `python-magic` 库即可。

---

## 1.8 速率限制（Rate Limiting）

防止：
- 暴力破解登录
- 恶意爬虫
- LLM 端点被刷爆（每个请求都很贵）
- DoS 攻击

最常见做法：**计数器 + 时间窗**（如 5次/分钟）。计数器存哪里？

- **进程内字典**：4 个 worker 各自一份，加起来用户实际能用 20 次/分钟 → ❌ 不行
- **Redis**：所有 worker 共享一个计数器 → ✅ 这是 slowapi 默认做法

---

## 1.9 缓存的两面

缓存能大幅降低延迟和成本，但有两个坑：

**坑 1：一致性**——数据更新了，缓存怎么办？两种策略：
- **TTL**（5 分钟过期）—— 简单，但更新后有窗口期看到旧数据
- **主动失效**（更新时 `cache.delete(key)`）—— 精确，但写路径复杂

**坑 2：缓存击穿/雪崩**
- 击穿：热门 key 同时过期，大量请求穿透到下游
- 雪崩：缓存整体故障，下游被瞬时打挂

### 我们项目的当下选择

`services/cache_service.py` 用 TTL 模式，加 Redis 错误时**降级**（不缓存但仍返回正确结果）——这个 fallback 行为正确。

---

## 1.10 Vector Store / Milvus 是什么

传统数据库存"精确字段"。向量数据库存"语义向量"。

```
文本 "Redis 缓存雪崩" → 通过 embedding 模型 → [0.12, -0.5, 0.7, ...]
                                                ↑ 512 维向量
```

把这个向量存进 Milvus；查询时：
```
查询文本 "Redis 缓存怎么穿透"
   → embedding → [0.13, -0.49, 0.71, ...]
   → Milvus 用近似最近邻算法（HNSW）找出向量空间里"距离最近"的 K 个
   → 返回语义相似的文档
```

### LlamaIndex 是什么

LlamaIndex 是 Python 库，封装了"文档 → embedding → 存 vector store → 检索 → 重排"这一整套 RAG pipeline，让你不用每个步骤都写底层代码。

### 我们项目里的 Milvus 用法

有 3 个 collection（独立的"数据库表"）：
- `interview_copilot_documents` — RAG 知识库（八股文 + 用户上传的文档）
- `interview_copilot_memory` — 用户长期记忆
- `interview_copilot_resume` — 简历向量

为什么是 3 个：早期没考虑合并，每加一个功能新建一个。合并需要数据迁移，所以一直没合。

---

## 1.11 BM25 是什么

BM25 是**词频检索**算法（vs 语义检索的向量搜索）。

例子：
- 查询 "Redis 持久化 AOF"
- BM25 找出**字面上包含这些词**最多、词频/文档频率比最优的文档

混合检索 = 向量检索（语义） + BM25（关键词）。两者互补：
- 向量擅长"意思相近但用词不同"
- BM25 擅长"专有名词、API 名、人名"

### BM25 索引是怎么建的

BM25 需要"看过所有文档"才能算 TF-IDF 统计。所以：
1. 启动时把所有文档读出来
2. 构建倒排索引
3. 查询时用索引快速匹配

文档变了（新增/删除）就要**重建索引**。我们项目用 TTL（5 分钟）触发重建，并在 ingestion 时主动失效。

---

## 1.12 单例模式（Singleton）

让一个类**整个进程只有一个实例**的设计模式。

```python
class MilvusClient:
    def __init__(self):
        self._connection = self._build_connection()  # 很贵

# ❌ 错误用法：每次新建
def query(text):
    client = MilvusClient()   # ← 每次都建连接
    return client.search(text)

# ✅ 正确用法：单例
_client = None
def get_client():
    global _client
    if _client is None:
        _client = MilvusClient()  # 只建一次
    return _client

def query(text):
    return get_client().search(text)
```

### 为什么重要

- 连接是昂贵的（TCP 握手、TLS、认证）
- 模型加载是昂贵的（GB 级权重、几秒到几分钟）
- 索引初始化是昂贵的（构建数据结构）

如果不做单例，每个请求都重复这些开销，延迟和资源消耗会暴涨。

---

## 1.13 测试中的 mock / stub

测试时不能真的调 OpenAI、连 Milvus、跑 GPU 推理——慢、贵、不稳定。所以用 **mock** 把外部依赖换成"假货"：

```python
# 真实代码
from openai import AsyncOpenAI
client = AsyncOpenAI()

# 测试代码
def test_something(monkeypatch):
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = {"choices": [...]}
    monkeypatch.setattr("app.module.client", fake_client)
    # 现在被测代码用的是 fake_client
```

### 模块导入时的副作用是测试敌人

```python
# resume_service.py 第一行
from sentence_transformers import SentenceTransformer
_embedding_model = SentenceTransformer("bge-small")  # ← 加载几百 MB 模型
```

只要测试 `import resume_service`，这个模型就会加载——即使你只想测一个 5 行的纯函数。解决方案：
- **延迟加载**：模型放到函数里第一次用时初始化
- **测试中 stub**：conftest 提前注入假的 SentenceTransformer

---

## 1.14 数据库分页

`get_full_transcript()` 一次拉所有消息：

```python
rows = db.query(ChatMessage).filter(...).all()
# 1 个 session 有 5000 条消息 → 全部读入内存 + 走网络
```

问题：
- 内存可能 OOM
- 响应慢
- 把 DB 负载拉高

**分页**：每次只拉一小段：

```python
# offset/limit（最简单，但深度分页性能差）
rows = db.query(...).offset(100).limit(20).all()

# cursor（推荐）
rows = db.query(...).filter(ChatMessage.seq < before_seq).order_by(...desc()).limit(20).all()
# 然后返回最后一条的 seq 作为下次的 before_seq
```

---

## 1.15 异常处理收紧

```python
# ❌ 反模式
try:
    do_something()
except Exception as exc:  # noqa: BLE001  ← 这个 noqa 是个红旗
    return {"error": str(exc)}
```

问题：
- **类型范围太广**：捕获了 `KeyboardInterrupt`、`SystemExit` 之外的一切。本来应该抛到顶部让监控告警的，被悄悄吞了
- **信息损失**：`str(exc)` 只是异常的字符串，丢了 traceback
- **难定位**：日志里看到 "error: Some thing" 不知道哪个文件第几行

```python
# ✅ 推荐
try:
    do_something()
except json.JSONDecodeError as exc:        # 具体类型
    logger.warning("JSON 解析失败: %s", exc)
    return None                              # 业务上能处理的情况返回
except DatabaseError as exc:                # 数据库错误是另一回事
    logger.exception("DB 错误")              # logger.exception 自动带 traceback
    raise                                    # 让上层处理
# 不写 except Exception —— 让真正未预料的异常冒泡，被全局 handler 抓
```

---

## 1.16 异步并行（asyncio.gather）

多个独立的 I/O 任务可以**同时进行**：

```python
# ❌ 串行：3 个 LLM 调用，每个 5s，总共 15s
for chunk in chunks:
    result = await analyze_chunk(chunk)
    results.append(result)

# ✅ 并行：3 个同时发出，总耗时约 max(5s, 5s, 5s) = 5s
tasks = [analyze_chunk(chunk) for chunk in chunks]
results = await asyncio.gather(*tasks)
```

注意：
- 只对**独立**任务有效（后一个不依赖前一个的结果）
- 要控制并发度（外部 API 通常有 rate limit）：用 `asyncio.Semaphore` 限上限
- 一个失败默认会让 gather 抛错；用 `return_exceptions=True` 改成"失败也返回异常对象"

---

好了，基础概念铺垫完。下面是具体改进项。

---

# Part 2 · 改进项详解

## 改进 #1 · 🔴 Docker 容器以 root 跑

📚 **概念铺垫**：见 [1.3 容器与 Docker](#13-容器与-docker)

🔍 **当前状态**

`backend/Dockerfile` 一共 55 行，**没有任何 `USER` 指令**。这意味着 `CMD` 启动的 gunicorn 进程是 **root 身份**跑的。

```dockerfile
# 现在的 Dockerfile（节选）
FROM python:3.13-slim AS runtime
...
WORKDIR /app
COPY backend/ ./
EXPOSE 8080
CMD ["gunicorn", "app.main:app", ...]
# ↑ 没有 USER，默认 root
```

⚠ **为什么是问题**

1. **攻击面放大**：任何远程代码执行漏洞 → 攻击者立刻是 root
2. **容器逃逸风险**：如果有 Docker socket 挂载或者 `--privileged`，能从容器跳到宿主机
3. **合规**：很多公司安全审计要求容器非 root
4. **最小权限原则**违反——应用根本不需要 root

🛠 **改进方案**

```dockerfile
# Stage 2: Lean runtime image
FROM python:3.13-slim AS runtime

RUN apt-get update && \
    apt-get install -y --no-install-recommends libpq5 curl && \
    rm -rf /var/lib/apt/lists/*

# ⭐ 新增：创建非特权用户
RUN groupadd --system --gid 1001 app && \
    useradd --system --uid 1001 --gid app --no-create-home --shell /sbin/nologin app

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# 用 --chown 让拷进来的文件属于 app 用户
COPY --chown=app:app backend/ ./
COPY --chown=app:app alembic.ini /app/alembic.ini
COPY --chown=app:app alembic/ /app/alembic/

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8080/ping || exit 1

# ⭐ 新增：切换到非特权用户
USER app

CMD ["gunicorn", "app.main:app", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--workers", "2", \
     "--bind", "0.0.0.0:8080", \
     "--timeout", "120", \
     "--access-logfile", "-"]
```

**注意点**：
- `--system` 标志：创建系统用户（UID < 1000），不能登录
- `--no-create-home`：不创建家目录，应用不需要
- 端口 8080 > 1024，非特权用户能监听（< 1024 需要 root）
- 若有写盘需求（log/缓存），目录所有权要给 app 用户

✅ **如何验证**

```bash
# 构建镜像
docker build -t interview-copilot:test backend/

# 启动容器并查 PID 1 的用户
docker run -d --name ictest interview-copilot:test
docker exec ictest ps aux | head -3
# 期望：USER 列显示 "app" 而不是 "root"

docker exec ictest id
# 期望：uid=1001(app) gid=1001(app)
```

⏱ **难度估时**：S（半小时）

---

## 改进 #2 · 🔴 默认 SECRET_KEY 在生产环境硬阻断

📚 **概念铺垫**：见 [1.4 JWT 认证基础](#14-jwt-认证基础)

🔍 **当前状态**

`backend/app/core/config.py:286-292`：

```python
# SECRET_KEY is always WARNING — it's not a "dev convenience" issue.
if secret_finding is not None:
    name, hint = secret_finding
    logger.warning(
        "[security] %s is set to an insecure default. %s",
        name, hint,
    )
```

即使在生产环境（`SENTRY_ENVIRONMENT=production`），用占位 SECRET_KEY 时**只打 WARNING，进程照常启动**。

⚠ **为什么是问题**

- 部署上线时谁也不看启动日志的 WARNING（淹没在几百行启动信息里）
- 占位 SECRET_KEY 的危害已经在 [1.4](#14-jwt-认证基础) 讲过——攻击者能伪造任意用户 token
- 一次粗心 → 整个产品的认证系统失效

🛠 **改进方案**

把生产环境的 SECRET_KEY 检查从 WARNING 升级为 **RuntimeError**：

```python
def _validate_production_safety(s: "Settings") -> None:
    is_prodlike = (s.SENTRY_ENVIRONMENT or "local").strip().lower() in {"staging", "prod", "production"}
    findings: list[tuple[str, str]] = []
    secret_finding: tuple[str, str] | None = None

    if (s.SECRET_KEY or "").strip() in _INSECURE_SECRET_KEYS:
        secret_finding = (
            "SECRET_KEY",
            "Generate one with: python -c \"import secrets; print(secrets.token_urlsafe(48))\"",
        )

    # ... 已有的其他 findings 收集 ...

    # ⭐ 关键改动：生产环境下 SECRET_KEY 是"硬错误"
    if secret_finding is not None:
        name, hint = secret_finding
        if is_prodlike:
            # 直接抛错，进程退出 —— 比启动后被攻破强一万倍
            raise RuntimeError(
                f"[FATAL] {name} is an insecure default in production. "
                f"Refusing to start. {hint}"
            )
        else:
            logger.warning(
                "[security] %s is set to an insecure default. %s",
                name, hint,
            )

    # 其他 findings 在生产环境也升级为 ERROR
    if findings and is_prodlike:
        for name, hint in findings:
            logger.error(
                "[PRODUCTION BLOCKER] Insecure default: %s. Hint: %s",
                name, hint,
            )
        # 可选：是否把 DB/MinIO 默认密码也升级为 raise？
        # 取决于你想多严格。建议：先 raise SECRET_KEY，DB/MinIO 保留为 ERROR
        # 等运维流程稳定后再升级
```

**为什么 SECRET_KEY 是 RuntimeError 而 DB 密码只是 ERROR**：
- SECRET_KEY 占位 = 整个认证系统被攻破，无缝替换
- DB 默认密码占位 = 暴露给内网，影响有限（应该有网络隔离作第二道防线）
- 阶梯式收紧能减少误伤

✅ **如何验证**

```bash
# 模拟生产环境启动
SENTRY_ENVIRONMENT=production SECRET_KEY="change-me-for-local-development" \
  python -c "from app.core.config import settings"
# 期望：直接 RuntimeError 退出
```

⏱ **难度估时**：S（半小时）

---

## 改进 #3 · 🔴 nginx 加安全头与 TLS

📚 **概念铺垫**：见 [1.6 HTTP 安全响应头](#16-http-安全响应头)、[1.1 反向代理](#11-http-请求生命周期与反向代理)

🔍 **当前状态**

`nginx/conf.d/default.conf` 23 行，**只做反向代理转发**，无 TLS、无安全头、无限流：

```nginx
server {
    listen 80;
    server_name localhost;
    client_max_body_size 500M;  # 全局 500M
    location / {
        proxy_pass http://host.docker.internal:8080;
        proxy_set_header Host $host;
        # ... 转发头 ...
    }
}
```

应用层（`main.py:247-261`）已经加了安全头，但：
1. 直接打 nginx 的请求（绕过应用）拿不到这些头
2. 没有 TLS——HTTP 明文传输

⚠ **为什么是问题**

- 明文 HTTP：中间人可读 token、可改请求
- 缺安全头双保险：应用层 bug 导致漏掉头时，nginx 没补位
- 上传无差别 500M：知识库上传、头像上传都按这个上限——头像被恶意上 500M 直接耗磁盘
- 没有 IP 级限流：第一道防线缺位，slowapi 是应用层（请求已经吃了一遍解析开销）

🛠 **改进方案**

```nginx
# /etc/nginx/conf.d/default.conf

# ── 限流配置（在 http 块或 nginx.conf 里）─────────────────────────────
# 这里假设主 nginx.conf 里已有：
# limit_req_zone $binary_remote_addr zone=ip_general:10m rate=30r/s;
# limit_req_zone $binary_remote_addr zone=ip_auth:10m rate=5r/m;

# ── 80 端口：把 HTTP 全部 301 到 HTTPS ──
server {
    listen 80;
    server_name yourdomain.com;
    return 301 https://$server_name$request_uri;
}

# ── 443 端口：真正的服务 ──
server {
    listen 443 ssl http2;
    server_name yourdomain.com;

    # TLS 证书（用 Let's Encrypt / certbot 自动管理）
    ssl_certificate /etc/letsencrypt/live/yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/yourdomain.com/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;

    # ── 安全头（"add_header always" 保证错误响应也带头）──
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Frame-Options "DENY" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    add_header Permissions-Policy "geolocation=(), microphone=(self), camera=()" always;
    # CSP 比较严格，需根据前端实际依赖调试，先留个简单版
    add_header Content-Security-Policy "default-src 'self'; img-src 'self' data: https:; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'" always;

    # ── 默认上传上限：5MB ──
    client_max_body_size 5M;

    # ── 不同端点的上限分流 ──
    location ~ ^/api/v1/interviews/.+/upload {
        client_max_body_size 200M;   # 面试音视频
        limit_req zone=ip_general burst=20;
        proxy_pass http://host.docker.internal:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location ~ ^/api/v1/knowledge/upload {
        client_max_body_size 50M;    # 知识库文档
        limit_req zone=ip_general burst=10;
        proxy_pass http://host.docker.internal:8080;
        # 同上其他 proxy_set_header
    }

    location ~ ^/api/v1/(auth|users)/ {
        limit_req zone=ip_auth burst=3 nodelay;   # 登录、注册严格限流
        proxy_pass http://host.docker.internal:8080;
        # 同上其他 proxy_set_header
    }

    # ── SSE 端点：长连接，关 proxy buffer ──
    location ~ ^/api/v1/chat/sse {
        proxy_pass http://host.docker.internal:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_http_version 1.1;
        proxy_buffering off;          # 关闭缓冲，SSE 才能流式
        proxy_cache off;
        proxy_read_timeout 600s;      # 长会话别 60s 就掐
    }

    # ── 默认路由 ──
    location / {
        limit_req zone=ip_general burst=50;
        proxy_pass http://host.docker.internal:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_http_version 1.1;
    }
}
```

**说明**：
- `always` 参数：确保 4xx/5xx 响应也带头（默认不加）
- `limit_req_zone` 要在 `nginx.conf` 的 `http {}` 块定义；如果你只能改 `conf.d/*`，可能要让运维配合
- TLS 证书我假设走 certbot，本地开发可以用自签

✅ **如何验证**

```bash
# 头是否就位
curl -I https://yourdomain.com/ | grep -i "frame\|hsts\|content-type-options"

# CSP 是否报错（打开浏览器开发者工具看 Console）
# 如果 CSP 太严，会看到 Refused to load... 错误，按需放宽

# 限流是否生效
for i in {1..10}; do curl -s -o /dev/null -w "%{http_code}\n" https://yourdomain.com/api/v1/auth/login -X POST -d '{}'; done
# 期望：前 5 次 401（认证失败），后面变 429（被限流）
```

⏱ **难度估时**：M（一天，含证书申请和 CSP 调试）

---

## 改进 #4 · 🔴 文件上传 magic-byte 校验

📚 **概念铺垫**：见 [1.7 文件上传的安全](#17-文件上传的安全)

🔍 **当前状态**

`services/storage_service.py` 做了文件名净化和路径穿越保护，但**不校验文件内容的真实类型**。Presigned URL 接受任意 `content_type` 参数。

⚠ **为什么是问题**

举两个具体攻击场景：
1. 上传伪造 PDF 的 PHP 文件 → 如果 S3 暴露成静态站点，可能被远程执行
2. 上传伪造图片的恶意 docx → 后续 resume_service 解析时触发已知 CVE

🛠 **改进方案**

新建 `backend/app/services/uploads/file_validation.py`：

```python
"""上传文件 magic-byte 校验。

调用约定：在调用方拿到 UploadFile 后、写入存储前 await validate_upload()。
失败抛 HTTPException(400)，调用方不用 catch。
"""
from __future__ import annotations

import logging
from typing import Literal

import magic  # python-magic
from fastapi import HTTPException, UploadFile

logger = logging.getLogger(__name__)

# 业务上允许的 purpose → 允许的真实 MIME 类型
_ALLOWED_MIME: dict[str, set[str]] = {
    "resume": {
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  # .docx
        "application/msword",  # .doc
        "text/plain",
    },
    "jd": {
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "text/plain",
        "text/markdown",
    },
    "knowledge": {
        "application/pdf",
        "text/plain",
        "text/markdown",
    },
    "audio": {
        "audio/mpeg",       # mp3
        "audio/mp4",        # m4a
        "audio/wav",
        "audio/x-wav",
        "audio/ogg",
        "audio/webm",
        "video/mp4",        # 面试录制可能是 mp4
        "video/webm",
    },
    "avatar": {
        "image/jpeg",
        "image/png",
        "image/webp",
    },
}

# 业务上限（字节）；外层 nginx 也会限，这是双保险
_SIZE_LIMITS: dict[str, int] = {
    "resume": 10 * 1024 * 1024,        # 10 MB
    "jd": 5 * 1024 * 1024,             # 5 MB
    "knowledge": 50 * 1024 * 1024,     # 50 MB
    "audio": 200 * 1024 * 1024,        # 200 MB
    "avatar": 2 * 1024 * 1024,         # 2 MB
}


async def validate_upload(
    file: UploadFile,
    purpose: Literal["resume", "jd", "knowledge", "audio", "avatar"],
) -> bytes:
    """校验上传文件的真实类型和大小。

    返回：文件内容（已读到内存，调用方可以直接写存储）。
    抛：HTTPException(400) on validation failure.
    """
    allowed_mime = _ALLOWED_MIME.get(purpose)
    size_limit = _SIZE_LIMITS.get(purpose)
    if allowed_mime is None or size_limit is None:
        raise HTTPException(400, f"Unknown upload purpose: {purpose}")

    # 读全文件（注意：大文件可能 OOM，下面有改进方向）
    content = await file.read()
    size = len(content)

    if size == 0:
        raise HTTPException(400, "文件为空")
    if size > size_limit:
        raise HTTPException(
            400,
            f"文件超过 {size_limit // 1024 // 1024}MB 上限（实际 {size // 1024 // 1024}MB）",
        )

    # python-magic 读前几个字节判断真实类型
    # from_buffer(content, mime=True) 返回 "application/pdf" 这种
    detected_mime = magic.from_buffer(content[:8192], mime=True)
    if detected_mime not in allowed_mime:
        logger.warning(
            "Rejected upload: purpose=%s declared=%s detected=%s",
            purpose, file.content_type, detected_mime,
        )
        raise HTTPException(
            400,
            f"不支持的文件类型 {detected_mime}（{purpose} 允许：{', '.join(sorted(allowed_mime))}）",
        )

    # 客户端声明类型与实际不一致也警告（可能是攻击或客户端 bug）
    if file.content_type and file.content_type != detected_mime:
        logger.info(
            "Content-Type mismatch (purpose=%s): declared=%s detected=%s — accepting based on magic bytes",
            purpose, file.content_type, detected_mime,
        )

    return content
```

**调用点改造**（举例：简历上传）：

```python
# 在 api/upload.py 或类似地方
@router.post("/upload/resume/direct")
async def upload_resume_direct(
    file: UploadFile,
    current_user: User = Depends(get_current_user),
):
    from app.services.uploads.file_validation import validate_upload
    content = await validate_upload(file, purpose="resume")
    # 拿到 content 后存 S3 / 写 DB
    upload = await storage_service.save_blob(...)
    return {"upload_id": upload.id}
```

**注意点**：

1. **依赖问题**：`python-magic` 需要系统库 `libmagic`。在 Dockerfile 加：
   ```dockerfile
   RUN apt-get install -y libmagic1
   ```
   在 `requirements.txt` 加 `python-magic==0.4.27`。

2. **大文件 OOM**：上面的实现 `await file.read()` 一把读全文件。对 200MB 音频不合适。改进方向：
   - 只读前 8KB 判类型，然后 `file.seek(0)` 重置，剩下流式存
   - 但 UploadFile 的实现可能不支持 seek，需要测试

3. **性能**：magic 调用很快（几毫秒），但每次上传 +1 次磁盘到内存的拷贝。如果上传是热点路径再考虑流式优化。

✅ **如何验证**

```python
# tests/test_file_validation.py
async def test_validate_pdf_upload():
    fake_pdf = b"%PDF-1.4\n" + b"x" * 1000  # PDF magic + 填充
    file = UploadFile(filename="resume.pdf", file=BytesIO(fake_pdf))
    content = await validate_upload(file, purpose="resume")
    assert content == fake_pdf

async def test_reject_exe_disguised_as_pdf():
    fake = b"MZ\x90\x00" + b"x" * 1000  # Windows PE magic
    file = UploadFile(
        filename="resume.pdf",
        file=BytesIO(fake),
        headers={"content-type": "application/pdf"},
    )
    with pytest.raises(HTTPException) as exc_info:
        await validate_upload(file, purpose="resume")
    assert exc_info.value.status_code == 400
```

⏱ **难度估时**：S（半天）

---

## 改进 #5 · 🟠 Milvus 客户端单例

📚 **概念铺垫**：见 [1.10 Vector Store](#110-vector-store--milvus-是什么)、[1.12 单例模式](#112-单例模式singleton)

🔍 **当前状态**

`services/memory/vector_service.py:181-200`：

```python
async def retrieve_vector(self, *, user_id, query, memory_types, top_k):
    vector_store = self._vector_store(overwrite=False)   # ← 每次新建 MilvusVectorStore
    index = VectorStoreIndex.from_vector_store(vector_store)  # ← 每次新建 index
    ...
```

而 `_vector_store` 内部：

```python
def _vector_store(self, overwrite=False):
    return MilvusVectorStore(
        uri=settings.MILVUS_URI,
        collection_name=self.collection_name,
        # ... 一堆参数 ...
    )
    # ↑ MilvusVectorStore 构造时会建 gRPC 连接、ping collection、读 schema 信息
```

`services/resume/resume_vector_service.py` 同模式。

对比 `rag/retriever.py:66-90` 已经做了正确的单例：

```python
def _get_milvus_index() -> VectorStoreIndex:
    global _milvus_store, _milvus_index
    if _milvus_index is not None:
        return _milvus_index
    with _milvus_lock:
        if _milvus_index is not None:
            return _milvus_index
        _milvus_store = MilvusVectorStore(...)   # 只建一次
        _milvus_index = VectorStoreIndex.from_vector_store(_milvus_store)
        return _milvus_index
```

⚠ **为什么是问题**

每次 memory 召回或 resume 检索：
- 新建 gRPC 连接（TCP 握手）
- 拉一遍 collection schema
- 重新构造 VectorStoreIndex

并发 50 用户每秒 1 次查询 = 50 次/s 的新连接 = Milvus 端连接耗尽风险 + 平均 +50~200ms 延迟。

🛠 **改进方案**

把 `MemoryVectorService` 改成持有单例的形式：

```python
class MemoryVectorService:
    def __init__(self):
        self.collection_name = settings.MEMORY_MILVUS_COLLECTION
        # ⭐ 实例上缓存 store 和 index
        self._store: MilvusVectorStore | None = None
        self._index: VectorStoreIndex | None = None
        self._lock = threading.Lock()  # 防止多线程同时初始化

    def _get_store_and_index(self) -> tuple[MilvusVectorStore, VectorStoreIndex]:
        """双检锁懒加载：99% 路径无锁，仅冷启动时进锁。"""
        if self._index is not None:
            return self._store, self._index
        with self._lock:
            if self._index is not None:        # 再检查一次（可能别的线程刚建好）
                return self._store, self._index
            store = MilvusVectorStore(
                uri=settings.MILVUS_URI,
                collection_name=self.collection_name,
                dim=EMBEDDING_DIM,
                overwrite=False,
                similarity_metric=settings.MILVUS_SIMILARITY_METRIC,
                index_config={...},
                search_config={...},
            )
            index = VectorStoreIndex.from_vector_store(store)
            self._store = store
            self._index = index
            return store, index

    async def retrieve_vector(self, *, user_id, query, memory_types, top_k):
        # ⭐ 用单例
        _, index = self._get_store_and_index()
        filters = MetadataFilters(
            filters=[MetadataFilter(key="user_id", value=user_id, operator=FilterOperator.EQ)],
            condition="and",
        )
        retriever = VectorIndexRetriever(
            index=index,
            similarity_top_k=top_k,
            filters=filters,
        )
        # ... 后面不变 ...
```

**注意点**：
1. **写路径（upsert）也要复用**：原来 `upsert_memory` 也是每次新建，改成调 `_get_store_and_index()`
2. **`overwrite=True` 是初始化特殊场景**——这个时候要新建（不复用单例）。给 `_get_store_and_index` 加个 `force_new` 参数或单独建一个 `_build_fresh_store` 方法
3. **进程内单例 vs 多 worker**：每个 gunicorn worker 进程都有自己的单例。如果你有 4 个 worker，就是 4 个连接——这是合理的，不是问题（uvicorn worker 之间不共享 Python 对象）

🔧 **同样改造 `resume_vector_service.py`**——结构完全一样。

✅ **如何验证**

```python
# 简单单测
def test_milvus_store_is_singleton():
    svc = MemoryVectorService()
    s1, i1 = svc._get_store_and_index()
    s2, i2 = svc._get_store_and_index()
    assert s1 is s2
    assert i1 is i2

# 性能基线：跑 100 次 retrieve_vector，看总耗时
import time
async def bench():
    svc = MemoryVectorService()
    start = time.perf_counter()
    for _ in range(100):
        await svc.retrieve_vector(user_id="alice", query="redis", memory_types=["user_profile"], top_k=5)
    print(f"100 queries: {time.perf_counter() - start:.2f}s")
# 改造前后对比，预期至少快 30%
```

⏱ **难度估时**：S（半天）

---

## 改进 #6 · 🟠 BM25 缓存语义升级 + Postgres docstore 复用

📚 **概念铺垫**：见 [1.11 BM25 是什么](#111-bm25-是什么)、[1.9 缓存的两面](#19-缓存的两面)

🔍 **当前状态**

`rag/bm25_cache.py:105`：

```python
def _build_and_cache_bm25(user_id, source_type, allowed_user_ids, ...):
    docstore = PostgresDocumentStore.from_uri(uri=settings.DATABASE_URL)
    all_nodes = list(docstore.docs.values())   # ← 全表扫描
    filtered_nodes = [n for n in all_nodes if metadata_matches_scope(n.metadata, ...)]
    ...
```

每次缓存 miss（TTL 5min 到期或新用户）都做这个全表扫描。

`services/memory/vector_service.py:62` 同样每次新建 `PostgresDocumentStore`。

⚠ **为什么是问题**

1. **`PostgresDocumentStore.from_uri()` 不便宜**：建连接 + 读全部 docs 到内存
2. **`docstore.docs.values()` 是全表**：10K 节点 × 多个用户/source_type = 多次重复读
3. **TTL 5min 是个粗糙阈值**：可能 4 分钟内没新数据也强制重建（浪费）；也可能新数据 ingest 后等 5 分钟才生效（用户疑惑）

🛠 **改进方案**

分两步：

### 6A. PostgresDocumentStore 单例化

新建 `app/db/docstore.py`：

```python
"""共享的 PostgresDocumentStore 单例。

LlamaIndex 的 PostgresDocumentStore.from_uri 会在每次调用时建新连接 +
prepared statement，重复创建很贵。这里给整个进程提供一个共享实例。
"""
from __future__ import annotations

import logging
from threading import Lock

from app.core.config import settings

try:
    from llama_index.storage.docstore.postgres import PostgresDocumentStore
except ModuleNotFoundError:
    PostgresDocumentStore = None  # type: ignore

logger = logging.getLogger(__name__)

_docstore: "PostgresDocumentStore | None" = None
_lock = Lock()


def get_docstore() -> "PostgresDocumentStore":
    """返回进程内共享的 PostgresDocumentStore（懒初始化）。"""
    global _docstore
    if PostgresDocumentStore is None:
        raise RuntimeError("PostgresDocumentStore 依赖未安装")
    if _docstore is not None:
        return _docstore
    with _lock:
        if _docstore is not None:
            return _docstore
        _docstore = PostgresDocumentStore.from_uri(uri=settings.DATABASE_URL)
        logger.info("PostgresDocumentStore singleton initialized")
        return _docstore
```

调用方改成：

```python
# rag/bm25_cache.py 和 services/memory/vector_service.py
from app.db.docstore import get_docstore

def _build_and_cache_bm25(...):
    docstore = get_docstore()  # ⭐ 复用
    all_nodes = list(docstore.docs.values())
    ...
```

### 6B. BM25 缓存改成"mutation epoch"驱动

加一个全局 epoch 计数，ingestion 时 `+1`，缓存条目记录建立时的 epoch：

```python
# rag/bm25_cache.py
from threading import Lock

_global_epoch = 0
_epoch_lock = Lock()


def bump_epoch() -> int:
    """文档变更时调用。所有现存缓存条目变"陈旧"。"""
    global _global_epoch
    with _epoch_lock:
        _global_epoch += 1
        return _global_epoch


class _BM25CacheEntry:
    __slots__ = ("retriever", "node_count", "epoch")  # ⭐ 去掉 created_at，加 epoch

    def __init__(self, retriever, node_count, epoch):
        self.retriever = retriever
        self.node_count = node_count
        self.epoch = epoch


def _get_cached_bm25(user_id, source_type, ...) -> BM25Retriever | None:
    cache_key = _bm25_cache_key(user_id, source_type)
    with _bm25_cache_lock:
        entry = _bm25_cache.get(cache_key)
        if entry is not None and entry.epoch == _global_epoch:  # ⭐ 比对 epoch
            return entry.retriever
    return None


# rag/ingestion.py 在每次 ingest 完成后
from app.rag.bm25_cache import bump_epoch
bump_epoch()
```

效果：
- 没新数据时，缓存**永不失效**（即使过了几小时）—— 命中率 ↑
- 一旦有 ingestion，所有用户的缓存下一次查询时都重建（确保看到最新数据）—— 一致性 ↑
- 不再每 5 分钟"瞎过期"

**注意**：epoch 是进程内的，多 worker 之间不同步。如果你需要跨 worker：把 epoch 存 Redis（`INCR bm25_epoch`），每次 read 时拿一下。但这增加每次查询 +1ms Redis 调用——按需选择。

✅ **如何验证**

```python
def test_bm25_cache_survives_ttl_with_no_mutation(monkeypatch):
    """没新数据时缓存不应失效。"""
    # ... 构建一个 retriever 存入缓存 ...
    entry_before = _bm25_cache[key]
    # 模拟过 1 小时
    monkeypatch.setattr(time, "monotonic", lambda: time.monotonic() + 3600)
    cached = _get_cached_bm25(...)
    assert cached is entry_before.retriever  # 没 mutation，依然命中

def test_bm25_cache_invalidated_on_ingest():
    """ingest 后全部缓存失效。"""
    _bm25_cache[key] = _BM25CacheEntry(..., epoch=_global_epoch)
    bump_epoch()
    cached = _get_cached_bm25(...)
    assert cached is None
```

⏱ **难度估时**：M（1 天）

---

## 改进 #7 · 🟠 三个 Milvus collection 合并评估

📚 **概念铺垫**：见 [1.10 Vector Store](#110-vector-store--milvus-是什么)

🔍 **当前状态**

3 个独立 collection：

| Collection | 用途 | 文档大小 |
|---|---|---|
| `interview_copilot_documents` | RAG 知识库 | 较大文本块 |
| `interview_copilot_memory` | 用户长期记忆 | 短文本（一句话）|
| `interview_copilot_resume` | 简历段落 | 中等 |

⚠ **为什么可能是问题**

- 3 套连接、3 个 schema、3 个索引调优、3 套备份
- 不能跨 collection 检索（"召回与简历相关的记忆"做不到）
- 但**也可能不是问题**——如果三种数据的：
  - 写入频率差异大
  - 查询模式差异大（top_k 不同，filter 不同）
  - 数据规模差异大（百万级 vs 千级）

  那么分开维护更合理。

🛠 **改进方案：先评估，再决定**

**Step 1：测量当前现状**

写一个临时脚本，跑一次：

```python
from pymilvus import connections, utility, Collection
from app.core.config import settings

connections.connect(uri=settings.MILVUS_URI)
for name in ["interview_copilot_documents", "interview_copilot_memory", "interview_copilot_resume"]:
    if utility.has_collection(name):
        c = Collection(name)
        c.load()
        print(f"{name}: {c.num_entities} 条")
```

**Step 2：决策矩阵**

| 指标 | 阈值 → 分开维护 | 合并 |
|---|---|---|
| 任意 collection 超 1M 条 | ✓ | ✗ |
| 三者 top_k 差 5 倍以上 | ✓ | ✗ |
| 需要跨类型检索（如"和简历相关的记忆"）| ✗ | ✓ |
| 运维成本痛点（备份/扩容/调优）| ✗ | ✓ |

**Step 3：合并方案（如果决定合并）**

```python
# 单一 collection: interview_copilot_unified
# Schema:
#   id (PK)
#   vector (FLOAT_VECTOR, dim=EMBEDDING_DIM)
#   user_id (VARCHAR, indexed)
#   source_type (VARCHAR, indexed)  ← "rag" / "memory" / "resume"
#   sub_type (VARCHAR)               ← memory 类型 / source_type 二级
#   metadata (JSON)

# 查询时所有调用方在 filter 里加 source_type:
filters = MetadataFilters(filters=[
    MetadataFilter(key="user_id", value=user_id, operator=FilterOperator.EQ),
    MetadataFilter(key="source_type", value="memory", operator=FilterOperator.EQ),
])
```

**迁移流程**：
1. 创建新 collection
2. 写双写：新数据同时写老和新
3. 跑迁移脚本把老数据 dump → 新 collection
4. 切换读路径到新 collection（开关 + 灰度）
5. 验证一周
6. 停止写老 collection
7. 删老 collection

**注意**：这是个大工程，**只在评估后真有痛点再做**。在没痛点时合并是过度工程。

⏱ **难度估时**：评估 S（半天），合并 L（一周）

---

## 改进 #8 · 🟠 get_full_transcript 加分页

📚 **概念铺垫**：见 [1.14 数据库分页](#114-数据库分页)

🔍 **当前状态**

`services/chat/chat_history_service.py:133-144`：

```python
def get_full_transcript(self, session_id: str) -> list[dict]:
    db = SessionLocal()
    try:
        rows = (
            db.query(ChatMessage)
            .filter(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.seq.asc())
            .all()    # ← 全量返回
        )
        return [self._message_to_dict(row) for row in rows]
```

⚠ **为什么是问题**

模拟面试一场可能 50-100 轮，加上 status 消息超过 500 条。如果用户来"查看完整 transcript"，一次性返回所有：
- 内存：500 条 × 平均 2KB = 1MB（单请求 OK，但并发 100 个就是 100MB 瞬时）
- 网络：1MB JSON 传到前端，慢
- 渲染：前端一次渲染 500 条 DOM 卡顿

🛠 **改进方案**

加 cursor-based 分页（推荐 over offset/limit，深度分页时 cursor 性能稳定）：

```python
# services/chat/chat_history_service.py
def get_full_transcript(
    self,
    session_id: str,
    *,
    before_seq: int | None = None,
    limit: int = 100,
) -> dict:
    """分页拉取 transcript。

    Args:
        session_id: 会话 ID
        before_seq: 拉取 seq < before_seq 的消息。None = 拉最新的。
        limit: 单次最多返回多少条（最大 200）

    Returns:
        {
            "messages": [...],         # 按 seq 升序
            "next_before_seq": int | None,  # 下一页用的 cursor；None = 没更多
            "has_more": bool,
        }
    """
    limit = min(max(limit, 1), 200)
    db = SessionLocal()
    try:
        q = db.query(ChatMessage).filter(ChatMessage.session_id == session_id)
        if before_seq is not None:
            q = q.filter(ChatMessage.seq < before_seq)
        # 倒序拉 limit+1 条（多拉一条用来判断 has_more）
        rows = q.order_by(ChatMessage.seq.desc()).limit(limit + 1).all()
        has_more = len(rows) > limit
        rows = rows[:limit]
        rows.reverse()  # 转回正序

        next_cursor = rows[0].seq if (has_more and rows) else None
        return {
            "messages": [self._message_to_dict(r) for r in rows],
            "next_before_seq": next_cursor,
            "has_more": has_more,
        }
    finally:
        db.close()
```

调用方（`api/chat/sessions.py:210` 附近的 `get_full_transcript` endpoint）：

```python
@router.get("/chat/transcript")
def get_full_transcript(
    session_id: str = Query(...),
    before_seq: int | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # 权限检查 ...
    result = transcript_service.get_full_transcript(
        session_id,
        before_seq=before_seq,
        limit=limit,
    )
    return {
        "status": "success",
        "session_id": session_id,
        # ... 其他元数据 ...
        **result,
    }
```

**前端兼容**：API 形状从 `"messages": [...]` 变成 `"messages": [...], "has_more": bool, "next_before_seq": int|None`。

- 不破坏老前端：`messages` 字段还在
- 新前端可以用 cursor 滚动加载

⏱ **难度估时**：S（半天，含前端配合）

---

## 改进 #9 · 🟠 mock_interview 端点的 async + sync ORM 修复

📚 **概念铺垫**：见 [1.2 同步 vs 异步](#12-同步-vs-异步asyncio--event-loop)

🔍 **当前状态**

`api/chat/mock_interview.py` 6 处 `async def + db.commit()`：

```python
@router.post("/chat/mock-interview/start")
async def start_mock_interview(...):
    # ...
    db.commit()   # L155 ← event loop 阻塞
```

⚠ **为什么是问题**

mock_interview 是热点路径（每次回答都要走 `/answer`），每次 commit 期间 event loop 卡住。并发用户互相拖累。

🛠 **改进方案**

两种思路，从轻到重：

### 方案 A：endpoint 改成同步 `def`（推荐先做这个）

FastAPI 对同步 `def` 路由会**自动放进线程池跑**，整体表现和异步差不多，event loop 不会被阻塞。

```python
# 改前
@router.post("/chat/mock-interview/start")
async def start_mock_interview(...):
    # ... 异步调用 LLM ...
    brief = await generate_brief(...)
    db.commit()
    return ...

# 改后：endpoint 是同步的，但仍可在内部 await LLM
# 等等：FastAPI 同步 endpoint 不能直接 await，需要拆出 helper
```

但 mock_interview 里大量 `await llm_call()`，硬要变同步会很糟糕。所以**方案 A 不适用 mock_interview**。

### 方案 B：用 `asyncio.to_thread` 包装 commit（推荐）

```python
# 改前
db.commit()

# 改后
await asyncio.to_thread(db.commit)
```

更进一步，把整个"操作 + commit"包成一个同步函数：

```python
def _persist_state_change(db: Session, session_id: str, state: dict):
    session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    session.session_state = dump_session_state(state)
    db.commit()

# endpoint 里
await asyncio.to_thread(_persist_state_change, db, request.session_id, state)
```

### 方案 C：迁移到 async ORM（长期方向）

SQLAlchemy 2.0 提供 `AsyncSession`：

```python
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

async_engine = create_async_engine("postgresql+asyncpg://...")

# endpoint
async with AsyncSession(async_engine) as db:
    result = await db.execute(select(ChatSession).where(...))
    row = result.scalar_one_or_none()
    # ...
    await db.commit()  # 真正的异步 commit
```

但这是大改造：
- 整个 `get_db` 依赖要换
- 所有 service 接口要改
- driver 从 `psycopg2` 换 `asyncpg`

建议作为长期路线图，不要现在做。

### 推荐节奏

1. 现在：对**热点路径**（mock_interview answer、QA pipeline）用 `to_thread` 包 commit
2. 季度内：完整异步化（如果 QPS 真的有压力）

✅ **如何验证**

用 `pytest-benchmark` 或自己写并发测试：

```python
import asyncio
import time
from httpx import AsyncClient

async def hammer(n=50):
    async with AsyncClient(base_url="http://localhost:8080") as c:
        start = time.perf_counter()
        await asyncio.gather(*[
            c.post("/api/v1/chat/mock-interview/answer",
                   json={"session_id": "...", "answer": "test"},
                   headers={"Authorization": "Bearer ..."})
            for _ in range(n)
        ])
        print(f"{n} concurrent: {time.perf_counter() - start:.2f}s")

# 改造前后跑这个，看延迟分布
```

⏱ **难度估时**：S（半天 to_thread 改造），L（一两周完整异步化）

---

## 改进 #10 · 🟡 大文件拆分

📚 **概念铺垫**：见 [单一职责原则](https://en.wikipedia.org/wiki/Single-responsibility_principle)（每个模块只做一件事）

🔍 **当前状态**

| 文件 | 行数 | 内含职责 |
|---|---|---|
| `services/voice/interview_analysis_service.py` | 904 | 转录 → 解析 → 段落分析 → 全局汇总 → mock 批量分析 |
| `services/interview/mock_interview_service.py` | 883 | 简历/JD 加载 → brief 生成 → director 决策 → 状态机 → 摘要 |
| `api/chat/mock_interview.py` | 800 | start/in-progress/abandon/answer/finish/parse_jd/transcribe/tts 8 个 endpoint |
| `agent_runtime/context_compactor.py` | 633 | 截断/摘要/dedup/3-pass pruning/容量监控 |

⚠ **为什么是问题**

- 单个文件超过 500 行后，IDE 跳转、PR review、新人理解都吃力
- 多个职责放一起 → 改一处不小心影响别处
- 测试粒度被迫变粗：想测一个小函数得 import 一大堆

🛠 **改进方案**：按职责切片

### 10A. `interview_analysis_service.py` (904 行) 拆 3 个模块

```
services/voice/
├── interview_analysis_service.py    # 仍保留入口函数 analyze_*，但只剩 100 行编排
├── analysis_stages/
│   ├── __init__.py
│   ├── transcript_parser.py         # _parse_speaker_turns, _build_qa_pairs (~150 行)
│   ├── per_question_analyzer.py     # _analyze_single_question, _build_sliding_context (~300 行)
│   └── report_synthesizer.py        # _synthesize_report (~200 行)
└── batch_analyzer.py                 # mock 批量分析逻辑 (~250 行)
```

主文件：

```python
# interview_analysis_service.py 改造后
async def analyze_interview(transcript: str, resume_context: str, jd_context: str):
    qa_pairs = _parse_speaker_turns(transcript) → _build_qa_pairs(...)
    tasks = [_analyze_single_question(...) for ...]
    per_question_results = await asyncio.gather(*tasks)
    report = await _synthesize_report(per_question_results, ...)
    return report
```

### 10B. `mock_interview_service.py` (883 行) 拆 4 个模块

```
services/mock_interview/
├── __init__.py
├── service.py            # 入口 + 协调（~150 行）
├── brief_generator.py    # 生成 interview brief / opening（~200 行）
├── director.py           # Runtime Director：每轮决策（~250 行）
├── state_machine.py      # phase 推进、turn_count 管理（~150 行）
└── history_summarizer.py # 每 N 轮压缩历史（~150 行）
```

### 10C. `api/chat/mock_interview.py` (800 行) 拆 3 个 router 文件

```
api/chat/mock_interview/
├── __init__.py           # 装配 router
├── lifecycle.py          # start/in-progress/abandon/finish (~250 行)
├── interaction.py        # answer/question/transcribe (~300 行)
└── voice.py              # parse_jd/tts (~150 行)
```

合并 router：

```python
# api/chat/mock_interview/__init__.py
from fastapi import APIRouter
from . import lifecycle, interaction, voice

router = APIRouter()
router.include_router(lifecycle.router)
router.include_router(interaction.router)
router.include_router(voice.router)
```

### 10D. `context_compactor.py` (633 行) 拆 2 个模块

```
agent_runtime/context/
├── compactor.py          # 主类 QueryLoopCompactor (~250 行)
└── pruning_passes.py     # _pass1_dedup / _pass2_summarize / _pass3_truncate / _sanitize_tool_pairs (~350 行)
```

### 拆分原则

1. **同一职责的代码放一起**（"会一起变的会一起改"）
2. **入口文件薄**（编排逻辑，<200 行）
3. **每个子模块有清晰的对外接口**（其他文件不要 `from x import *`）
4. **不要为了拆而拆**——50 行的文件没必要再拆

✅ **如何验证**

- 测试全部通过（行为不变）
- `wc -l` 看每个文件都在 300 行以下（除入口）
- 走查：随机选 3 个新文件，问自己"这个文件只做一件事吗？"

⏱ **难度估时**：每个文件 M（半天到一天）

---

## 改进 #11 · 🟡 测试加速：把 embedding 装载也 stub

📚 **概念铺垫**：见 [1.13 测试中的 mock / stub](#113-测试中的-mock--stub)

🔍 **当前状态**

`tests/conftest.py:27-35`：

```python
_MAYBE_MISSING = [
    "whisperx",
    "whisperx.diarize",
    "pyannote",
    "pyannote.audio",
]
for module_name in _MAYBE_MISSING:
    if module_name not in sys.modules:
        sys.modules[module_name] = MagicMock()
```

只 mock 了语音相关，**没 mock embedding 模型加载**。`test_resume_service` 首次跑会触发 BGE / sentence-transformers 下载或装载。

⚠ **为什么是问题**

- 第一次跑全量测试可能 5 分钟到几十分钟（取决于网络）
- CI 缓存失效后重新下载——每次几分钟
- 个别开发者本地没 GPU，CPU 跑 embedding 龟速

🛠 **改进方案**

在 conftest.py 加 embedding 模块的 stub：

```python
# conftest.py
import sys
from unittest.mock import MagicMock

import numpy as np


def _make_fake_embedding_model():
    """假的 embedding 模型：返回固定维度的随机向量。

    单测只要"形状对"，向量数值无所谓。
    """
    fake = MagicMock()
    fake.get_text_embedding = lambda text: list(np.random.rand(512).astype(float))
    fake.get_text_embedding_batch = lambda texts: [
        list(np.random.rand(512).astype(float)) for _ in texts
    ]
    # llama_index 接口
    async def _aget_text_embedding(text):
        return list(np.random.rand(512).astype(float))
    fake.aget_text_embedding = _aget_text_embedding
    return fake


# 重型 ML 模块
_MAYBE_MISSING = [
    "whisperx",
    "whisperx.diarize",
    "pyannote",
    "pyannote.audio",
]
for module_name in _MAYBE_MISSING:
    if module_name not in sys.modules:
        sys.modules[module_name] = MagicMock()


# ⭐ 关键：替换 embedding 模型工厂
# llama_index 通过 Settings.embed_model 拿全局 embedding。
# 我们在 app.rag.embeddings 模块导入时就把它换掉。
@pytest.fixture(autouse=True, scope="session")
def _stub_embedding_model():
    """Session-scoped autouse：测试启动时一次性把 embedding 替换掉。"""
    from llama_index.core import Settings
    fake = _make_fake_embedding_model()
    real = Settings.embed_model
    Settings.embed_model = fake
    yield
    Settings.embed_model = real
```

更彻底的做法：直接 mock `HuggingFaceEmbedding` 类本身：

```python
# 在 conftest.py 最顶部（早于任何 app import）
import sys
from unittest.mock import MagicMock

# 拦截 from llama_index.embeddings.huggingface import HuggingFaceEmbedding
# 让它返回一个不真正加载模型的假类
fake_hf_module = MagicMock()
fake_hf_module.HuggingFaceEmbedding = lambda **kwargs: _make_fake_embedding_model()
sys.modules["llama_index.embeddings.huggingface"] = fake_hf_module
```

**注意**：
- session-scoped fixture autouse 整个 pytest 跑期间只生效一次
- 改完后跑 `test_resume_service` 应该秒级完成

✅ **如何验证**

```bash
# 改造前
time pytest tests/test_services/test_resume_service.py
# 几十秒到几分钟

# 改造后
time pytest tests/test_services/test_resume_service.py
# 应该 < 5s
```

⏱ **难度估时**：S（半天）

---

## 改进 #12 · 🟢 schema_compat.py 清理

🔍 **当前状态**

```
backend/app/db/schema_compat.py  # 文件还在
```

文件第 38 行：`logger.warning("schema_compat is deprecated; use alembic upgrade head instead.")`

但 `main.py` 已经不再调用它。

⚠ **为什么是问题**

- 死代码增加阅读成本（新人会以为它还有用）
- 文件里可能有过时的列定义，被人误用会偏离 alembic 真相

🛠 **改进方案**

**Step 1**：确认 alembic 已经包含 schema_compat 里所有列定义

```bash
# 看 schema_compat.py 里加的所有列
grep -E "ADD COLUMN|add_column" backend/app/db/schema_compat.py

# 看 alembic 迁移里这些列是否都有
ls alembic/versions/
# 对每个列 grep 一下
```

**Step 2**：确认没有人 import 它

```bash
grep -rn "schema_compat" backend/ alembic/ --include="*.py"
# 应该只有 schema_compat.py 自己出现
```

**Step 3**：删除文件

```bash
git rm backend/app/db/schema_compat.py
```

**Step 4**：跑全量测试 + 启动应用确认正常

⏱ **难度估时**：S（半小时）

---

## 改进 #13 · 🟢 引入 pyproject.toml

📚 **概念铺垫**

`pyproject.toml` 是 Python 现代项目的"配置中心文件"（PEP 517/518/621），可以一文件管理：
- 依赖（替代 requirements.txt）
- 构建后端
- 工具配置（ruff、black、mypy、pytest）
- 项目元数据（name、version、描述）

🔍 **当前状态**

只有 `requirements.txt`（扁平依赖列表），所有工具配置散在各自文件（`pytest.ini` 等）。

🛠 **改进方案**

新建 `pyproject.toml`：

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "interview-copilot"
version = "0.1.0"
description = "AI-powered interview preparation copilot"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.110",
    "uvicorn[standard]>=0.27",
    "sqlalchemy>=2.0",
    "alembic>=1.13",
    "psycopg2-binary>=2.9",
    "redis>=5.0",
    "celery>=5.3",
    "llama-index>=0.10",
    "openai>=1.0",
    "pydantic>=2.5",
    "pydantic-settings>=2.0",
    "python-jose[cryptography]>=3.3",
    "passlib[bcrypt]>=1.7",
    "python-multipart>=0.0.6",
    "slowapi>=0.1.9",
    "sentry-sdk[fastapi]>=1.40",
    "langsmith>=0.1",
    # ... 其他核心依赖
]

[project.optional-dependencies]
# ⭐ 关键：把重型可选依赖独立出来
voice = [
    "torch>=2.0",
    "whisperx",
    "pyannote.audio",
    "edge-tts",
]
ocr = [
    "pdfplumber",
    "python-docx",
]
test = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "pytest-cov",
    "httpx",
]
dev = [
    "ruff>=0.3",
    "mypy>=1.8",
    "ipython",
]

# ── 工具配置 ──

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = [
    "E",   # pycodestyle errors
    "F",   # pyflakes
    "I",   # isort
    "B",   # flake8-bugbear
    "UP",  # pyupgrade
    "SIM", # flake8-simplify
]
ignore = [
    "E501",  # line too long (let formatter handle)
]

[tool.ruff.lint.per-file-ignores]
"tests/*" = ["S101"]  # allow assert in tests
"alembic/versions/*" = ["E501"]  # auto-generated, long lines OK

[tool.mypy]
python_version = "3.11"
strict = false  # 先宽松，逐步收紧
plugins = ["pydantic.mypy"]

[[tool.mypy.overrides]]
module = ["whisperx.*", "pyannote.*"]
ignore_missing_imports = true

[tool.pytest.ini_options]
testpaths = ["backend/tests"]
asyncio_mode = "auto"
addopts = "-ra --strict-markers"

[tool.hatch.build.targets.wheel]
packages = ["backend/app"]
```

**安装方式**：

```bash
# 开发环境
pip install -e ".[test,dev]"

# 生产环境（不带 voice）
pip install -e .

# 完整功能（带 voice）
pip install -e ".[voice]"
```

这样 CI 跑测试时不下载几个 GB 的 torch+whisper。Docker 镜像可以两份：
- `Dockerfile`（基础）—— 不带 voice
- `Dockerfile.voice`（worker）—— 带 voice

⚠ **注意**

- 老的 `requirements.txt` 可以保留过渡期，CI 同时验证两种装法
- 上线脚本要更新（`pip install -r requirements.txt` → `pip install -e .`）

⏱ **难度估时**：M（一天，含 CI 调整）

---

## 改进 #14 · 🟢 Celery 任务失败回写 + 告警

📚 **概念铺垫**

Celery 是 Python 异步任务队列：
```
HTTP request → 创建 task → 写入队列（Redis）
                                ↓
                          worker 拉取执行
                                ↓
                          结果写回 / 状态更新
```

任务失败：默认重试几次后**任务彻底消失**。如果业务依赖任务结果（比如 InterviewRecord 等转录完成），就会**永远卡在中间状态**。

🔍 **当前状态**

`backend/app/worker/tasks.py` 已有 `max_retries=3` + 指数退避，但失败后：
- DB 里的 InterviewRecord 状态仍是 `TRANSCRIBING` 或 `ANALYZING`
- 用户看到"正在处理中"，永远等不到结果
- 运维不知道这个任务挂了

🛠 **改进方案**

### 14A. 任务失败时回写 DB 状态

```python
# tasks.py
from celery.exceptions import MaxRetriesExceededError

@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def process_interview_analysis(self, interview_id: int):
    db = SessionLocal()
    try:
        interview = db.query(InterviewRecord).get(interview_id)
        if not interview:
            logger.error("Interview not found: %s", interview_id)
            return
        interview.status = "TRANSCRIBING"
        db.commit()

        # ... 实际转录 + 分析 ...

        interview.status = "COMPLETED"
        db.commit()
    except (SoftTimeLimitExceeded, NetworkError) as exc:
        # 可重试错误
        logger.warning("Retryable error in task %s: %s", interview_id, exc)
        try:
            raise self.retry(exc=exc, countdown=2 ** self.request.retries * 60)
        except MaxRetriesExceededError:
            _mark_failed(db, interview, f"Max retries exceeded: {exc}")
            _alert_ops("Interview analysis exhausted retries", interview_id, exc)
            raise
    except Exception as exc:
        # 不可重试错误（数据问题、bug 等）
        logger.exception("Fatal error in task %s", interview_id)
        _mark_failed(db, interview, str(exc))
        _alert_ops("Interview analysis fatal error", interview_id, exc)
        raise
    finally:
        db.close()


def _mark_failed(db: Session, interview: InterviewRecord, reason: str):
    """统一的失败状态回写。"""
    interview.status = "FAILED"
    interview.error_message = reason[:500]   # 截断防溢出
    interview.failed_at = datetime.utcnow()
    try:
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Failed to mark interview %s as FAILED", interview.id)


def _alert_ops(title: str, interview_id: int, exc: Exception):
    """发告警到 Sentry / 钉钉。"""
    try:
        import sentry_sdk
        sentry_sdk.capture_exception(exc)
    except Exception:
        pass
    # 如果有钉钉 webhook，这里发
```

### 14B. 用户能查到失败状态

InterviewRecord model 加一个 `error_message` 字段：

```python
# models/interview_record.py
class InterviewRecord(Base):
    # ... 现有字段 ...
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
```

Alembic 迁移加这两个字段。

### 14C. acks_late 防丢任务

```python
# worker/celery_app.py
celery_app.conf.update(
    task_acks_late=True,                # worker 跑完才 ack；崩了任务还在队列里
    task_reject_on_worker_lost=True,    # worker 进程挂掉时把任务还回去
    worker_prefetch_multiplier=1,       # 一次只拿一个任务，避免 worker 死了带走一批
)
```

⏱ **难度估时**：M（一天，含 alembic 迁移和告警接入）

---

## 改进 #15 · 🟡 nginx per-location 上传上限（已在 #3 一起做）

见 [改进 #3](#改进-3---nginx-加安全头与-tls)，这里不重复。

---

# Part 3 · 执行顺序建议

按 ROI 由高到低排：

## 🚀 第一波（一周内可完成）

| 顺序 | 改进 | 难度 | 收益 |
|---|---|---|---|
| 1 | #1 Docker 非 root | S | 安全 ⭐⭐⭐⭐ |
| 2 | #2 SECRET_KEY 硬阻断 | S | 安全 ⭐⭐⭐⭐⭐ |
| 3 | #12 schema_compat 清理 | S | 维护性 ⭐⭐ |
| 4 | #8 transcript 分页 | S | 稳定性 ⭐⭐⭐ |
| 5 | #11 测试 stub embedding | S | 开发体验 ⭐⭐⭐ |
| 6 | #5 Milvus 单例 | S | 性能 ⭐⭐⭐⭐ |

## 🛠 第二波（两周内）

| 顺序 | 改进 | 难度 | 收益 |
|---|---|---|---|
| 7 | #3 nginx 安全头 + TLS | M | 安全 ⭐⭐⭐⭐ |
| 8 | #4 magic-byte 校验 | S | 安全 ⭐⭐⭐ |
| 9 | #9 mock_interview to_thread | S | 并发 ⭐⭐⭐ |
| 10 | #6 BM25 epoch 升级 | M | 性能 ⭐⭐⭐ |
| 11 | #14 Celery 失败回写 | M | 可观测性 ⭐⭐⭐⭐ |

## 🏗 第三波（按需）

| 顺序 | 改进 | 难度 | 收益 |
|---|---|---|---|
| 12 | #13 pyproject.toml | M | 工程化 ⭐⭐ |
| 13 | #10A `interview_analysis_service` 拆分 | M | 维护性 ⭐⭐⭐ |
| 14 | #10B `mock_interview_service` 拆分 | M | 维护性 ⭐⭐⭐ |
| 15 | #10C `api/chat/mock_interview` 拆分 | M | 维护性 ⭐⭐⭐ |
| 16 | #7 Milvus collection 合并评估 | M | 运维 ⭐⭐ |

---

# Part 4 · 总验证清单

每一波改完跑：

```bash
# 1. 单测全过
cd backend
pytest --tb=line -q

# 2. 应用能起
python -c "from app.main import app; print(len(app.routes))"

# 3. 容器能起
docker build -t ic:test backend/
docker run -d --name ic-test ic:test
sleep 5
curl -f http://localhost:8080/ping

# 4. 启动用户是非 root（#1 验证）
docker exec ic-test id
# 期望：uid=1001(app)

# 5. SECRET_KEY 硬阻断（#2 验证）
docker exec -e SENTRY_ENVIRONMENT=production \
    ic-test python -c "from app.core.config import settings"
# 期望：RuntimeError

# 6. nginx 安全头（#3 验证）
curl -I https://yourdomain.com/ | grep -iE "x-frame|hsts|csp|content-type-options"

# 7. 上传校验（#4 验证）
# 试上传 .exe 改名 .pdf，期望 400

# 8. 性能基线（#5/#6 验证）
# 跑 wrk 或 locust，对比改造前后的 P95 延迟

docker rm -f ic-test
```

---

# 附录：术语速查表

| 术语 | 中文 | 一句话解释 |
|---|---|---|
| Reverse Proxy | 反向代理 | nginx 之类，公网前台 |
| TLS | 传输层安全 | HTTPS 的加密层 |
| HSTS | HTTP 严格传输安全 | 强制浏览器走 HTTPS |
| CSP | 内容安全策略 | 限制页面能加载什么资源 |
| CORS | 跨域资源共享 | 浏览器跨域请求的白名单制 |
| JWT | JSON Web Token | 签名过的认证令牌 |
| RBAC | 基于角色的访问控制 | 用户 → 角色 → 权限 |
| Event Loop | 事件循环 | asyncio 的单线程调度器 |
| Coroutine | 协程 | `async def` 函数返回的对象 |
| Singleton | 单例 | 整进程只有一个实例 |
| TTL | 生存时间 | 缓存条目过期前能活多久 |
| BM25 | （算法名）| 词频检索算法 |
| Embedding | 嵌入向量 | 把文本变成数值向量 |
| RAG | 检索增强生成 | 先检索再让 LLM 生成 |
| HNSW | 分层可导航小世界图 | Milvus 用的近似最近邻索引 |
| IDOR | 不安全直接对象引用 | 没检查权限直接用 ID 访问 |
| DLQ | 死信队列 | 反复失败的任务最终去处 |
| Idempotent | 幂等 | 多次执行结果相同 |
| Magic Bytes | 魔数 | 文件头几个字节，标识真实类型 |

---

完。这份文档以"先讲概念再讲改"的节奏组织，每个改进都能独立执行不依赖其他改进。建议从第一波开始按顺序做，做完每一项跑一遍验证清单确认无 regression 再进下一项。
