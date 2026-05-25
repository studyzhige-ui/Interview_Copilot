# 提示词 ① · 项目技术深度详解

> **使用方法**：把这整份 `.md` 的内容（从下面的"--- 提示词正文从这里开始 ---"那行往下）整段复制，贴给 Codex CLI / Claude Code / 网页版 Claude / ChatGPT 等大模型。如果你用的模型有读文件工具（Codex CLI、Claude Code），它会自己去读源码；网页版的话需要你额外贴上"必读文件清单"里那些源码内容。

---

--- 提示词正文从这里开始 ---

# 任务

你是一位资深技术写作者。请为开源项目 **Interview Copilot**（路径 `D:/Projects/Python/Interview_Copilot`，仓库根目录）撰写一份**完整、详尽、面向基础薄弱读者**的项目技术详解文档。

## 输出位置

把最终文档写到：
```
docs/interview-prep/01-project-deep-dive.md
```
（这个文件夹现在还不存在，需要你创建。）

# 读者画像（请把每句话都当成不可妥协的约束）

- 读者是**基础较薄弱**的开发者：会 Python、会写过简单接口、做过小项目，但**没有系统接触过** RAG、Agent、向量数据库、BM25、JWT、Celery、Milvus、LlamaIndex、SSE、HNSW、Reranker、Embedding 等概念。
- 读者读这份文档的目标是：**通读一次就能完整、清晰地理解整个项目**——每个模块的边界、每个链路的流程、每个亮点为什么这样设计。
- 读者的**最痛点**：被术语吓退。一个术语第一次出现时如果没用"大白话"解释，读者会卡住。

# 文风要求（违反任何一条都要重写）

1. **全文简体中文**。代码、文件名、专有名词（class 名）保留英文，其余全中文。
2. **几乎不出现代码**。整份文档允许的代码总量上限 = 10 个 1–3 行的伪代码片段（用于点睛）。其余全部用**自然语言**讲解。**不允许**把整段源码贴出来当解释。
3. **概念第一次出现必须从零讲解**。比如第一次写到 "JWT" 时，要用 30-80 字白话说"它是一段服务器签过名的字符串，里面装着'你是谁'+'什么时候过期'，浏览器以后每次请求都带着它去后端，后端验签就知道是你"。每个术语只讲一次（之后再用不重复解释），但**第一次出现一定要讲透**。
4. **流程描述必须是 step-by-step**：固定句式"当用户做了 X，系统首先 ……，然后 ……，接着 ……，最终 ……"。每一步必须说清四件事：
   - **输入**是什么（来自哪个上一步、什么字段）
   - **做了什么**（这一步的内部逻辑）
   - **输出**是什么（传给下一步什么）
   - **为什么需要这一步**（如果省掉会怎样、为什么这个顺序）
5. **每个大段落都要有架构图**。架构图用 Mermaid 或 ASCII，**必须有中文标注**——不能只画英文 box 和箭头。例如不允许只画 `[Frontend] → [API] → [DB]`，必须画成 `[前端 React]  → [FastAPI 后端 :8080]  → [PostgreSQL 主库]`，并在图下用 3-5 行文字描述这张图想说什么。
6. **每个"亮点设计"用统一三段式**：
   - **① 这是干嘛的**（一句话场景）
   - **② 怎么做到的**（流程级，不写代码，3-8 步骤）
   - **③ 为什么这样做**（动机 + 至少 1 个被否决的备选方案 + 取舍权衡）
7. **覆盖优先于篇幅**。整份文档可以很长（预计 30000-60000 字），但不能跳过任何模块。
8. **绝不允许"省略号式描述"**：不能写"等等"、"诸如此类"、"其他细节略"。所有内容讲透为止。

# 必读源码清单（你必须读完这些再开写）

> 如果你有文件读取工具，请逐个读完。如果你是网页版无法读文件，假定下面"项目事实速查"里的描述准确即可。

**入口与配置**：
- `backend/app/main.py`（启动顺序、CORS、Sentry、LangSmith、安全头、限流接入）
- `backend/app/core/config.py`（所有可配置项 + SECRET_KEY 校验逻辑）
- `backend/app/db/database.py`、`backend/app/db/redis.py`
- `docker-compose.yml`（dev / full 两套 profile）
- `backend/Dockerfile` + `backend/docker-entrypoint.sh`（非 root 容器）
- `nginx/conf.d/default.conf`（dev 反向代理）+ `nginx/conf.d/frontend.conf`（prod SPA）+ `nginx/conf.d/frontend.tls.conf`（prod TLS 终结）

**L1 QA 对话管道**：
- `backend/app/api/chat/streaming.py`（`POST /chat/sse/{session_id}` SSE 端点）
- `backend/app/api/chat/sessions.py`、`memory_items.py`
- `backend/app/qa_pipeline/agent_executor.py`（`stream_chat_with_agent`）
- `backend/app/qa_pipeline/planner.py`（`plan_query` → `QueryPlan`）
- `backend/app/qa_pipeline/rewriter.py`、`tools.py`
- `backend/app/services/chat/context_assembly_pipeline.py`（六槽位组装）
- `backend/app/services/chat/chat_history_service.py`、`session_state.py`

**L2 ReAct Agent 管道**：
- `backend/app/api/agent/react_agent.py`、`chat_compat.py`、`runs.py`
- `backend/app/agent_runtime/query_engine.py`（核心循环）
- `backend/app/agent_runtime/context_compactor.py`（3-pass 压缩 + 反应式压缩）
- `backend/app/agent_runtime/tool_registry.py`、`tool_result_storage.py`
- `backend/app/agent_runtime/harness_events.py`
- `backend/app/agent_runtime/agent_stop_hooks.py`、`agent_progress_hooks.py`
- `backend/app/agent_runtime/tools/` 下所有文件（knowledge / memory / resume / jobs / web / interview_history / file_tool）

**L3 模拟面试管道**：
- `backend/app/api/chat/mock_interview.py`（8 个 endpoint）
- `backend/app/services/mock_interview_service.py`（`build_prefix` / `generate_brief` / `run_director` / `summarize_history`）

**L4 语音分析管道**：
- `backend/app/api/interview.py`（上传 + 分析查询端点）
- `backend/app/services/interview/analysis_orchestrator.py`
- `backend/app/services/voice/audio_transcription_service.py`（WhisperX + Pyannote）
- `backend/app/services/voice/interview_analysis_service.py`（Stage 1-3 Map-Reduce）
- `backend/app/services/voice/file_parser.py`
- `backend/app/worker/tasks.py`（`process_interview_analysis`、`process_document_ingestion`）
- `backend/app/worker/celery_app.py`

**记忆子系统**：
- `backend/app/services/memory/` 下所有文件（`compaction_service.py` / `extraction_service.py` / `retrieval_service.py` / `post_turn_maintenance.py` / `vector_service.py` / `recall_policy.py` / `user_profile_doc_service.py` / `_json_payload.py`）
- `backend/app/models/memory.py`

**RAG 子系统**：
- `backend/app/rag/retriever.py`（混合检索主入口 `query_knowledge_base`）
- `backend/app/rag/bm25_cache.py`（BM25 缓存）
- `backend/app/rag/hybrid.py`（融合算法）
- `backend/app/rag/ingestion.py`（文档摄取）
- `backend/app/rag/knowledge_retriever.py`（QA 管道入口包装）
- `backend/app/rag/embeddings.py`、`embedding_registry.py`、`reranker_registry.py`

**多模型抽象**：
- `backend/app/core/model_registry.py`（9 个 provider × 3 个 role）
- `backend/app/services/model_catalog_service.py`
- `backend/app/services/user_api_key_service.py`（Fernet 加密、MultiFernet 轮换）
- `backend/app/api/model_runtime.py`（运行时切换端点）

**安全 / 可观测 / 限流 / 缓存**：
- `backend/app/core/security.py`（JWT、bcrypt、刷新令牌轮换）
- `backend/app/services/token_blacklist_service.py`
- `backend/app/services/verification_code_service.py`（邮箱验证码）
- `backend/app/services/email_service.py`
- `backend/app/core/rate_limit.py`（slowapi 分层）
- `backend/app/core/llm_tracing.py`（LangSmith 双层包装）
- `backend/app/services/cache_service.py`（Redis 读穿透缓存）
- `backend/app/services/file_validation.py`（魔字节上传校验）
- `backend/app/services/telemetry_service.py`（JSONL 指标）

**评测**：
- `evaluation/` 下所有文件
- `evaluation/golden_dataset.jsonl`（抽样几行了解样本格式即可）

**数据库**：
- `alembic/versions/0001_baseline.py`（基线表结构）
- `backend/app/models/` 下所有模型文件

**前端**：
- `frontend/package.json`、`frontend/vite.config.ts`
- `frontend/src/main.tsx` 或 `App.tsx`
- `frontend/src/api/client.ts`（拦截器、JWT 刷新）
- `frontend/src/store/` 下所有 store
- `frontend/src/pages/` 主要页面（ReviewPage / MockPage / GeneralChatPage / ModelsPage 等）

# 项目事实速查（这是为你预先梳理好的，写文档时直接引用）

## 业务定位
**Interview Copilot** 是一个 **AI 面试辅助系统**，覆盖 4 大业务场景：
1. **复盘**：用户传入面试录音，系统转写 + 自动评分 + Q&A 拆解，给出改进建议
2. **模拟面试**：基于用户简历 + JD，运行一个会自适应追问的 AI 面试官
3. **知识问答**：用户问技术问题，系统从用户的知识库 / 八股文 / 个人记忆里检索后作答
4. **岗位选择 / 复合任务**：调用工具的 Agent，可以搜网页 / 查岗位 / 读简历 / 存记忆

## 技术栈速览

| 层 | 技术 |
|---|---|
| API 框架 | FastAPI 0.135 + Pydantic v2 + SQLAlchemy 2 |
| 异步任务 | Celery 5 + Redis broker |
| 关系数据库 | PostgreSQL 15 |
| 向量数据库 | Milvus 2.5 + LlamaIndex |
| 对象存储 | S3 兼容（生产）/ MinIO（本地） |
| LLM | 任何 OpenAI-compatible（DeepSeek、OpenAI、Anthropic、Qwen、Moonshot、Zhipu、Gemini、Xiaomi MiMo、NVIDIA Catalog，共 9 个 provider） |
| 嵌入 / 重排 | BGE-M3（1024 维）+ BGE-Reranker-v2-m3，可选 SiliconFlow / Jina / Cohere / DashScope 远程 |
| ASR | WhisperX（Systran/faster-whisper-large-v3）+ Pyannote 声纹分离 |
| TTS | edge-tts |
| 前端 | React 18 + Vite 5 + Tailwind + Zustand |
| 可观测 | Sentry（错误）+ LangSmith（所有 LLM 调用）+ 自家 JSONL 指标 |
| 限流 | slowapi（Redis 后端，5/10/20/60 四档） |

## 4 大业务管道核心事实

### L1 QA 对话管道
- 入口：`POST /api/v1/chat/sse/{session_id}`，SSE 流式响应
- 编排函数：`stream_chat_with_agent`（`qa_pipeline/agent_executor.py`）
- 6 步流程：**ensure_session → 规划（rewrite + planner）→ 并发召回（记忆 + 知识库）→ 6 槽位上下文组装 → LLM 流式生成 → 持久化 + 后台维护**
- 状态码层语义：响应里夹 `[status]` 行让前端展示"正在……"
- 错误用户化：`_humanize_exc()` 把 401/429/超时翻译成中文动作建议
- 记忆召回是**用户可关闭的开关**（`recall_policy.recall_enabled_for_session`）

### L2 ReAct Agent 管道
- 入口：`POST /api/v1/agent/react/stream`（SSE）和 `/agent/react/chat`（非流）
- 核心类：`QueryEngine`，三个阶段：`_prepare_context` → `_query_loop`（多步工具循环）→ `_finalize_trace` + `_finalize_hooks`
- 工具系统：`tool_registry` + 7 个内置工具（搜知识库、存/查记忆、读简历、查面试历史、搜岗位、读 URL、读/写文件）
- 上下文管理：`QueryLoopCompactor`（3 步 pruning：dedup → summarise → truncate args；外加反应式 compact）
- 预算硬限：`AGENT_MAX_STEPS=25`、`AGENT_TOOL_TIMEOUT_SECONDS=30`、`AGENT_MAX_CALLS_PER_TOOL=8`、`AGENT_MAX_RUNTIME_SECONDS=180`
- 工具超大输出（>30K 字符）会被 `tool_result_storage` 持久化到磁盘，message 里只留预览
- 流式事件协议：`harness_events.py` 定义 status / tool_start / tool_done / text_delta / text / budget / error / done 八种事件

### L3 模拟面试管道（Runtime Director）
- 端点：`/start`、`/answer`、`/finish`、`/in-progress`、`/abandon`、`/question`、`/parse-jd`、`/transcribe`、`/tts`
- 三段 LLM：
  - **LLM #1（generate_brief）**：开场前生成面试地图 + 开场白
  - **LLM #2（run_director）**：每轮答题后决策"追问 / 换话题 / 转阶段 / 结束"，输出 `DirectorOutput`
  - **LLM #3（summarize_history）**：每 6 轮把老历史压缩成短摘要
- 设计上**强依赖 DeepSeek 100K prompt cache**：`build_prefix(resume, jd, style)` 把不变的简历 / JD / 风格冻在前缀里，session_state 里存 `cacheable_prefix` + `prefix_hash`
- 状态机严格顺序：先 snapshot answered_phase → append qa_entry → 增进度 → 才能 swap pending/current 字段
- 面试阶段：`self_intro` → `resume_deep_dive` → `technical` → `behavioral` → `reverse_qa`

### L4 语音分析管道（Celery 异步 Map-Reduce）
- 入口：上传音频 `POST /api/v1/upload/audio/direct` → 创建 `InterviewRecord(status=pending)` → 触发 `process_interview_analysis.delay(record_id)`
- Stage 1 转写：WhisperX（CUDA float16 / CPU int8 自适应）+ Pyannote diarization；可选远程 ASR
- Stage 2 提取：LLM 把转写文本切成 QA 对（≤120K token 单次；超出走重叠切分 + 合并）
- Stage 3 评分（Map）：每条 QA 用 sliding window（前 3 + 当前 + 后 2）独立打分 → `asyncio.gather` 并行
- Stage 3 汇总（Reduce）：综合诊断报告 + 薄弱话题 + 学习建议
- 状态机：pending → transcribing → extracting → analyzing → completed（或 failed，error_message 详细）
- Celery 失败兜底：区分**中途重试**（不写终态、避免 UI 闪烁）vs **最终失败**（写 `failed` + 重试已耗尽信息）

## 记忆子系统核心事实

**两种长期记忆类型**：
- **`user_profile`**：单一 Markdown 文档（`users.user_profile_doc` TEXT 列）。靠 patch 列表更新（`add` / `update` / `delete` 三种操作），不全量重写。承载"你是谁"——姓名、技术栈、目标公司。每次对话都全量注入到 system prompt。
- **`interview_fact`**：`memory_items` 表里的多行记录，按 `(user_id, type, normalized_key)` 去重。承载"这场面试讨论了什么"。带 `confidence`（≥ 0.65 才入库）、`importance`、`last_evidence_seq`。Milvus 向量搜索 + lexical 兜底召回。

**会话压缩双阈值触发**：`(token_growth ≥ 6000 AND turns ≥ 4) OR turns ≥ 15`。摘要按 6 章节模板：当前状态/目标/已完成/已解决问题/关键决策/待跟进。

**混合召回公式**：`final = 0.60×vector + 0.35×lexical + 0.15×importance + 0.05×recency`。陈旧阈值 2 天，命中时给一个 `staleness_note`。

**post-turn 后台维护**：每轮聊天结束触发；per-session asyncio.Lock 防并发；先跑压缩（推进 `compaction_cursor`）再跑提取（推进 `memory_extraction_cursor`），两个游标完全独立。

**Milvus 单例**：vector_service 双检锁缓存 store + index，避免每次查询都重建 gRPC 连接（节省 30-200ms）。`overwrite=True` 路径在锁内完成"销毁 → 重建 → 失效缓存"。

## RAG 子系统核心事实

**摄取链路**：文件 → LlamaParse / PyMuPDF 解析 → 自适应分块（`.md`/`interview_qa` 用 MarkdownNodeParser；`.py`/`.java`/`.cpp` 用 CodeSplitter；默认 SentenceSplitter(512, 64)）→ 向量嵌入 → Milvus + PostgresDocumentStore 双写 → `invalidate_bm25_cache(user_id)` 主动失效

**混合检索链路**（`query_knowledge_base`）：
1. Milvus 向量检索器：按 `user_id` + `source_type` 双 metadata filter
2. BM25 retriever（per-user 缓存，1h TTL + 主动失效）
3. `QueryFusionRetriever` 用 reciprocal_rerank 模式融合
4. BGE Reranker 交叉注意力重排
5. 防幻觉：先按 reranker 分数阈值（默认 0.5）截断；若全部低于阈值但词法覆盖 ≥ 0.35 也算命中
6. 全部不命中 → 返回 `[SYSTEM_EMPTY_WARNING]` 占位

**多租户三层强制隔离**：（1）Milvus MetadataFilter（2）BM25 构建时 `metadata_matches_scope` 过滤（3）后处理再次校验 `chunk.metadata["user_id"] == requester`

**BM25 缓存 key 形式**：`{user_id}|{source_type or '*'}`；失效触发点：`ingest_document` / `ingest_text` / `delete_knowledge_document`

## 多模型抽象核心事实

- **3 个 role**：`primary`（聊天）/ `agent`（必须支持 function calling）/ `mock_interview`（驱动面试官）
- **9 个 provider** × 多 model = 几十个组合
- **per-user API key 加密存储**：`user_api_keys` 表 + Fernet（SECRET_KEY 派生）+ MultiFernet（支持 SECRET_KEYS_OLD 灰度轮换）
- **运行时切换**：`PUT /models/runtime`，原子写 `model_selection.json`（`APP_DATA_DIR/runtime/`），同时清 LLM client 缓存
- **优先级**：用户 API key（DB）> 环境变量 `provider.api_key_env`
- **24 小时模型目录缓存**：`/models/refresh-catalog` 触发刷新

## 安全 / 可观测 / 限流

- **JWT**：HS256 + jti 撤销列表（Redis）；access 30min / refresh 7d；刷新轮换（旧 jti 立即撤销）
- **bcrypt 密码哈希**
- **限流分层**（slowapi + Redis）：auth 5/min / expensive 10/min / upload 20/min / default 60/min
- **LangSmith**：模块级 monkey-patch + 实例级 `wrap_existing_client` 双层包装，保证 100% LLM 调用可追溯
- **Sentry**：FastAPI / Starlette / SQLAlchemy / Redis / Celery 五大 integration，before-send 钩子清洗 Authorization / Cookie 头
- **文件上传**：纯 Python 魔字节校验（不依赖 libmagic），4 类 purpose（audio_clip 25MB / audio_upload 500MB / resume 10MB / jd 10MB）
- **生产 SECRET_KEY 硬阻断**：`SENTRY_ENVIRONMENT in {staging,prod,production}` 且 SECRET_KEY 是默认值 → `raise RuntimeError`
- **Docker 非 root**：UID 1001 `app` 用户 + entrypoint 用 gosu 切换权限 + 自动 chown `/app/data`

## 评测指标速查（必须在文档里有专章）

- 检索层：Hit Rate@3 = **96.9%**，MRR@5 = **0.950**，P95 延迟 = **98 ms**（835 样本）
- 生成层（RAGAS，200 样本）：忠实度 **92.5%**，上下文精确度 **93.2%**，上下文召回率 **98%**
- 端到端 P95 ≈ **8 秒**

# 文档结构（必须按这个顺序与目录组织）

## 第 0 章 · 写在前面（约 800 字）
- 文档定位、读法建议
- 读完之后你能掌握什么
- 名词速查表（JWT / SSE / RAG / Embedding / Reranker / BM25 / Milvus / HNSW / Celery / LlamaIndex / Pydantic / SQLAlchemy / Alembic / Fernet / slowapi / WhisperX / Pyannote / Sentry / LangSmith — 每个 20-50 字白话解释）

## 第 1 章 · 项目全景（约 2500 字）
1.1 解决的问题（面试备战的痛点 → 4 大业务场景）
1.2 用户旅程（从注册 → 上传简历 → 配置模型 → 模拟面试 → 复盘 → 提问的全链路）
1.3 **整体架构图**（前端 / 反向代理 / FastAPI / Celery worker / 数据存储四件套 / LLM 厂商）+ 中文图说
1.4 4 大业务管道一句话介绍
1.5 技术栈表 + **为什么选这套**（每项 1-2 句话理由，给出至少 1 个被否决的备选）

## 第 2 章 · 一次完整对话发生了什么（约 4000 字）
> 这是全文最重要的章节之一。把"用户在前端发送一句话"展开成一条完整的链路。

2.1 用户在前端点"发送"那一刻发生了什么（前端拦截器、JWT 注入、SSE 建连）
2.2 请求到达 nginx → 反向代理路径
2.3 进入 FastAPI 后的鉴权（`get_current_user` → JWT 解码 → 黑名单查询）
2.4 限流中间件（slowapi 怎么算这次请求的额度）
2.5 路由到 `/chat/sse/{session_id}` 后的会话所属权校验
2.6 进入 `stream_chat_with_agent` 后**逐步**展开：
   - ensure_session（如果会话不存在，怎么自动建）
   - 规划阶段（rewriter 重写指代 + planner 出 `QueryPlan`）
   - 并发召回（记忆 + 知识库同时跑，怎么 await）
   - 用户档案直接加载（user_profile，绕过开关）
   - interview_fact 是否召回（recall_policy 怎么判断）
2.7 6 槽位上下文组装（system_prompt / reference_material / retrieved_context / session_state / recent_turns / current_input 各装什么、各有 token 预算）
2.8 LLM 流式调用（OpenAI-compatible client 怎么选、provider 切换怎么生效、`_humanize_exc` 把异常翻成什么）
2.9 SSE 协议怎么把每个 token 推回前端（status / chunk / done 三类事件）
2.10 持久化：append_turn 写 chat_messages
2.11 后台触发 `post_turn_maintenance`（脱离 HTTP 请求生命周期、不阻塞响应）
2.12 **架构图**：完整链路图，中文标注

每一小节都用"输入→处理→输出→为什么"四要素讲清楚。

## 第 3 章 · ReAct Agent 是怎么走完一轮的（约 3500 字）
3.1 ReAct 是什么（先讲透概念，30-80 字白话）
3.2 入口 `/agent/react/stream` vs `/agent/react/chat` 差别（流式 / 非流式）
3.3 `QueryEngine` 三阶段拆解：
   - Phase 1：`_prepare_context`（记忆召回、上下文组装、`create_run` 写 trace 表）
   - Phase 2：`_query_loop`（while 循环里发生了什么）
   - Phase 3：`_finalize_trace` + `_finalize_hooks`（为什么 trace 一定要先写、hooks 后跑）
3.4 工具系统（自注册机制 + 7 个内置工具职责一句话介绍）
3.5 工具调用怎么解析（streaming 模式 + `_ToolCallAccumulator` 聚合 delta）
3.6 工具超大输出怎么不撑爆 message list（`tool_result_storage` + Redis）
3.7 上下文压缩怎么自动触发（3-pass：dedup → summarize → truncate args + orphan tool pair 修复）
3.8 反应式压缩（context_too_long 错误时的紧急回退 + 电路断路器）
3.9 预算硬限触发后会发生什么（steps / runtime / per-tool）
3.10 SSE 事件协议（8 种事件） + 前端怎么消费
3.11 **架构图**：QueryEngine 状态机图

## 第 4 章 · 模拟面试是怎么实现自适应追问的（约 3500 字）
4.1 整体设计："Runtime Director" 模式是什么（先讲清楚动机：传统先生成完整 plan 再按 plan 答题的方式刻板）
4.2 `/start` 详解：怎么把简历 + JD + 风格变成开场白
4.3 cacheable_prefix 是什么、prompt cache 怎么生效（DeepSeek 100K cache 原理白话）
4.4 `/answer` 详解：每轮里 LLM 输出的 `DirectorOutput` 包含哪些字段、怎么驱动状态机
4.5 状态机严格顺序的必要性（为什么不能先 swap 再 append）
4.6 `MAX_FOLLOW_UP_DEPTH=2` 这个参数为什么是 2
4.7 每 6 轮的滚动摘要（什么时候触发、压缩什么）
4.8 `/finish` 详解：创建 InterviewRecord + 触发 Celery 分析任务 + 创建 debrief 会话
4.9 stale shell 清理逻辑（in-progress 端点为什么会顺便扫垃圾）
4.10 5 个面试阶段（self_intro / resume_deep_dive / technical / behavioral / reverse_qa）的流转规则
4.11 TTS / 短录音转写两个辅助端点
4.12 **架构图**：模拟面试状态机 + 三段 LLM 调用时序图

## 第 5 章 · 录音是怎么被自动评分的（约 3500 字）
5.1 端到端链路图（用户传文件 → Celery → ASR → QA 提取 → Map-Reduce 评分 → 入库 → 前端轮询）
5.2 文件上传校验：纯 Python 魔字节是什么、为什么不用 libmagic
5.3 S3 / MinIO 存储桶结构（`audio/{user_id}/{upload_id}`）
5.4 Celery 任务幂等性（status == "completed" 短路、retry 期间状态机如何避免闪烁）
5.5 Stage 1（ASR）：WhisperX 本地 vs 远程的选路 + Pyannote diarization 是什么、为什么需要
5.6 Stage 2（QA 提取）：120K token 阈值、句级切分 + 20% 重叠 + 合并的策略
5.7 Stage 3（Map-Reduce 评分）：sliding window 上下文（prev=3, next=2）的设计动机、`asyncio.gather` 并行、reduce 阶段的全局诊断
5.8 失败处理：mid-retry vs final-attempt 的区分逻辑 + 用户 UI 看到的状态变化
5.9 `_generate_debrief_summary`：缓存友好的摘要、为什么是 fail-safe
5.10 **架构图**：四阶段状态流转图

## 第 6 章 · 检索是怎么不出幻觉的（约 4000 字）
6.1 RAG 是什么（白话讲透：检索增强生成 = 先找资料再让 AI 据此回答）
6.2 向量数据库 / Milvus 是什么（白话 + 跟传统数据库比较）
6.3 BM25 是什么（词频检索算法，对比向量检索）
6.4 HNSW 索引（分层可导航小世界图，白话）
6.5 嵌入 / 重排模型分别做什么（Embedding = 文本→向量；Reranker = 给检索结果二次打分）
6.6 文档摄取流程：自适应分块策略（按文件类型走不同 NodeParser）、为什么 chunk_size=512、为什么 chunk_overlap=64
6.7 混合检索完整链路（向量 + BM25 → 融合 → Rerank → 阈值截断）
6.8 多租户隔离三层强制（MetadataFilter / BM25 构建过滤 / 后处理校验，为什么不能只一层）
6.9 BM25 per-user 缓存策略（key 设计、1h TTL、主动失效触发点）
6.10 防幻觉：reranker 阈值（0.5）vs 词法覆盖兜底（0.35）的两道关
6.11 `[SYSTEM_EMPTY_WARNING]` 是什么、什么时候返回、LLM 怎么处理
6.12 多 provider 嵌入抽象（local / openai / siliconflow / jina / cohere / dashscope）切换方式
6.13 **架构图**：完整混合检索流水线

## 第 7 章 · 用户长期记忆是怎么管的（约 3500 字）
7.1 为什么需要长期记忆（vs 仅仅依赖会话内上下文）
7.2 两类记忆 user_profile vs interview_fact 的本质区别（一句话：你是谁 vs 这场面试讨论了什么）
7.3 user_profile 的 patch 机制（add/update/delete 三种操作 + 为什么放弃 normalized_key 去重）
7.4 interview_fact 的 schema 字段含义（normalized_key / confidence / importance / last_evidence_seq）
7.5 提取流程：什么时候触发、LLM 提示词怎么写、置信度阈值 0.65 的依据
7.6 会话压缩：双阈值触发公式、6 章节摘要模板设计、为什么不是简单 LRU
7.7 混合召回公式拆解（0.60×vector + 0.35×lexical + 0.15×importance + 0.05×recency）每个权重的依据
7.8 陈旧标记（staleness_note）的作用（LLM 怎么用这个信息）
7.9 post-turn 后台维护：双游标（compaction_cursor vs memory_extraction_cursor）独立推进的设计
7.10 per-session asyncio.Lock 怎么防止并发污染
7.11 召回开关 recall_policy（用户能在 UI 上关闭老 Q&A 召回的设计动机）
7.12 Milvus 单例 + 双检锁（为什么这样写、之前每次新建为什么不行）
7.13 **架构图**：记忆生命周期 + 双游标推进

## 第 8 章 · 多模型怎么做到 9 厂商无缝切换（约 2500 字）
8.1 设计目标：一行环境变量 = 切厂商；一份代码 = 9 个 provider
8.2 三层抽象：role → provider → model
8.3 `ModelProfile` 是什么、`MODEL_PROFILES` 字典怎么组织
8.4 OpenAI-compatible 协议的优势（不是每家都原生 OpenAI 但都兼容）
8.5 per-user API key 加密存储：Fernet 是什么（对称加密 AES-128-CBC + HMAC）、SECRET_KEY 派生 Fernet key 的安全性、MultiFernet 怎么做密钥轮换
8.6 优先级：用户 API key（DB）> 环境变量
8.7 运行时切换 `PUT /models/runtime` 的原子性（lock + 原子写 JSON）
8.8 切换后怎么清 LLM client 缓存
8.9 24 小时模型目录缓存（`cache_service` 用 Redis 实现）
8.10 错误用户化 `_humanize_exc` 把 401/429/超时翻译成什么
8.11 **架构图**：role → provider → API key → client 的解析路径

## 第 9 章 · 安全防线（约 2500 字）
9.1 JWT 全流程（什么是签发、验签、jti、撤销列表；access 30min vs refresh 7d 的设计动机）
9.2 刷新轮换（用 refresh 换新 access 时旧 refresh 立即撤销）
9.3 邮箱验证码注册 + 反枚举（已注册邮箱也返回相同 "sent" 响应）
9.4 限流分层 5/10/20/60（auth/expensive/upload/default）四档的取舍
9.5 CORS allowlist 替代通配（动机）
9.6 文件上传魔字节校验（4 类 purpose 的真实类型检测 + 大小上限）
9.7 SECRET_KEY 生产硬阻断（启动时 raise 的逻辑、SECRET_KEYS_OLD 轮换流程）
9.8 用户 API key 加密（之前 8.5 已经讲过，这里点到即可）
9.9 nginx 安全头（X-Frame-Options / X-Content-Type-Options / Referrer-Policy / Permissions-Policy / HSTS）每个防什么
9.10 Docker 非 root（UID 1001 / gosu / entrypoint chown）
9.11 多租户三层强制隔离（之前 6.8 已经讲过，这里点到即可）
9.12 路径穿越保护（S3 key 强制 `user_id` 前缀）
9.13 **架构图**：纵深防御 7 道关

## 第 10 章 · 可观测性（约 2000 字）
10.1 三层观测：错误 / 链路 / 指标
10.2 Sentry 集成 5 件套（FastAPI / Starlette / SQLAlchemy / Redis / Celery）
10.3 before-send 钩子怎么清洗 Authorization / Cookie 头
10.4 LangSmith 双层包装机制（module-level monkey-patch + per-instance wrap_existing_client）的必要性
10.5 全局未捕获异常 handler（traceback 强制落日志）
10.6 telemetry_service 写 JSONL 指标（写什么字段、`asyncio.to_thread` 不阻塞响应）
10.7 Agent trace 持久化（agent_trace + agent_trace_step 两表，前端能看完整工具调用链）
10.8 **架构图**：观测数据流向图

## 第 11 章 · 评测体系（约 2000 字）
11.1 为什么需要离线评测（不是上线了就完了）
11.2 评测分三层：检索 / 生成 / 轨迹
11.3 检索层指标：Hit Rate@K / MRR@K / nDCG@K / P95 latency（白话讲每个指标看什么）
11.4 生成层 RAGAS 三件套：忠实度 / 上下文精确度 / 上下文召回率（一句话定义 + 实际值）
11.5 多租户隔离单测（user_A 查询绝不返回 user_B 数据，0 violations 才算过）
11.6 golden_dataset.jsonl 的样本结构
11.7 eval_runner.py 的三种 --layer 模式
11.8 实测基线：检索 Hit@3 = 96.9%，MRR@5 = 0.950，P95 = 98ms；生成忠实度 92.5%，CP 93.2%，CR 98%；E2E P95 ≈ 8s
11.9 这些数字怎么读、为什么够好（举例 P95 98ms 意味着什么）

## 第 12 章 · 数据模型与数据库（约 1500 字）
12.1 alembic 基线策略（19 → 1 squash 的取舍）
12.2 主要表清单 + 每表一句话职责（users / user_api_keys / chat_sessions / chat_messages / interview_records / interview_qa / mock_interview_sessions / upload / knowledge / memory / agent_trace / resume_section）
12.3 关键索引（哪些字段建索引、为什么）
12.4 session_state JSONB 字段的 schema 演化策略（v1 → v2）
12.5 **ER 图**（中文标注）

## 第 13 章 · 前端架构（约 1500 字）
13.1 技术栈一句话介绍（React 18 + Vite 5 + Zustand + Tailwind）
13.2 主要页面（AuthPage / ModelsPage / GeneralChatPage / MockPage / ReviewPage / LibraryPage）
13.3 API 拦截器（client.ts）做了什么（自动注入 JWT、捕获 401 触发刷新、错误统一处理）
13.4 SSE 消费方式（fetch + ReadableStream + 解析事件流）
13.5 状态管理：authStore vs uiStore 职责划分
13.6 dev 与 prod 的代理链路差异（dev 直连 8080 / prod 走 nginx）

## 第 14 章 · 部署与运维（约 1500 字）
14.1 docker-compose 两套 profile（dev / full）的区别
14.2 数据卷映射（`./data:/app/data`）
14.3 启动顺序（Postgres → Redis → MinIO → Milvus → API → Worker → Frontend）
14.4 健康检查机制
14.5 alembic upgrade head 何时跑
14.6 CI 流程（push 到 main/develop 触发什么）
14.7 nginx dev / prod / TLS 三套配置怎么切换
14.8 生产部署 checklist

## 第 15 章 · 全部亮点设计汇总（约 3000 字）

> 这一章把全文散落的亮点统一抽出来，每个亮点用三段式：**① 这是干嘛的 ② 怎么做到的 ③ 为什么这样做**

请至少覆盖以下 15 个亮点（不限于这些，你读源码时如果发现更多请补充）：

1. SSE 流式响应（vs WebSocket 的选型动机）
2. `_humanize_exc` 用户友好错误翻译
3. 6 槽位上下文组装（vs 一锅炖 prompt）
4. ReAct QueryEngine 三阶段 + finalize 顺序保证
5. 工具结果磁盘溢出（防止 message list 爆炸）
6. 3-pass + 反应式 + 电路断路器三道上下文压缩
7. mock_interview 的 cacheable_prefix prompt cache 策略
8. mock_interview 状态机严格顺序（snapshot → append → 增进度 → swap）
9. interview_analysis Map-Reduce + sliding window
10. Celery 最终失败兜底（mid-retry vs final-attempt 区分）
11. 记忆 patch 机制（user_profile 文档增量更新）
12. 双游标推进（compaction_cursor vs memory_extraction_cursor 独立）
13. 混合召回融合公式（4 项加权）+ 陈旧标记
14. BM25 缓存主动失效（vs 纯 TTL）
15. 多 provider 加密 API key（Fernet + MultiFernet 轮换）
16. SECRET_KEY 生产硬阻断
17. Docker 非 root + entrypoint 自动 chown
18. LangSmith 双层包装（保证 100% LLM 调用覆盖）
19. 限流分层 + Redis 后端（跨 worker 计数共享）
20. 防幻觉双重过滤（reranker 阈值 + 词法兜底）

## 第 16 章 · 后续路线图（约 800 字）

写一节简短的"已识别但还没做的改进"：
- async ORM 完整迁移（个人产品规模下暂不做）
- 大文件拆分（mock_interview_service / interview_analysis_service / api/chat/mock_interview 几个 ≥800 行的）
- 3 个 Milvus collection 合并评估
- 日志 PII 脱敏 + 结构化 JSON
- pyproject.toml 引入

每条用三段式简短交代。

# 自检清单（写完后逐项核对，不达标就重写对应章节）

- [ ] 每个第一次出现的术语都有 30-80 字白话解释，且只解释一次
- [ ] 每个大章节都有至少一张架构图（Mermaid 或 ASCII），且图下有中文说明
- [ ] 每条链路都用"用户做了 X → 系统首先 ……"的句式
- [ ] 每个亮点设计都按"① 这是干嘛 ② 怎么做 ③ 为什么"三段式
- [ ] 整份代码量 ≤ 30 行（不算架构图里的伪标识）
- [ ] 没有任何"等等"、"诸如此类"、"其他细节略"
- [ ] 4 大业务管道每个都有独立章节深挖（第 2/3/4/5 章）
- [ ] 9 个 provider 都被点名（第 8 章）
- [ ] 评测指标 96.9% / 0.950 / 98ms / 92.5% / 93.2% / 98% / 8s 全部出现且解释了"这意味着什么"
- [ ] 字数 ≥ 30000，覆盖完整无遗漏

# 开始写

请先创建 `docs/interview-prep/` 目录，然后开始按上述结构写作。一次性写完整份文档，不要分多次发送。如果上下文窗口不够，可以分章节顺序输出但必须按目录顺序、并在最后一段明确告诉我"已完成"。

写完后，**最后输出一个总结**：覆盖了多少字、命中了自检清单的几项、有没有任何章节因为信息不足而做了合理推测（如果有，单独列出"推测点"，方便我后续核对）。
