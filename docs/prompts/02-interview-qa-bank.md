# 提示词 ② · 面试问答库（两阶段协作）

> **使用方法**：把下面"--- 提示词正文从这里开始 ---"以下的全部内容贴给一个**有 sub-agent 能力**的大模型（Claude Code、Codex CLI 等都可以）。如果你用的是没有 sub-agent 能力的网页版模型，提示词里有备选方案——同一个 LLM 顺序扮演两个角色也能做。

> **建议在执行 ① 之后再执行 ②**：因为本提示词会要求 LLM 大量引用第 ① 份文档（`docs/interview-prep/01-project-deep-dive.md`）里的事实描述。

---

--- 提示词正文从这里开始 ---

# 任务

你是一位资深技术面试专家。请为开源项目 **Interview Copilot**（路径 `D:/Projects/Python/Interview_Copilot`）撰写一份**面试问答库**，作为候选人面试时的核心复习资料。

## 输出位置

把最终文档写到：
```
docs/interview-prep/02-interview-qa-bank.md
```

# 这是怎样一份文档

候选人简历上写了 Interview Copilot 这个项目。面试官读过简历会问什么？

- 项目链路细节："你刚才说混合检索，具体怎么融合的？"
- 选型对比："为什么用 Milvus 不用 Chroma？为什么用 BM25 不用 TF-IDF？"
- 参数取舍："chunk_size=512 为什么是 512 不是 256 或 1024？"
- 异常路径："如果 LLM 厂商 429 限流了你怎么办？"
- 监控反推："你怎么知道 P95 真的是 98ms？测试集是怎么准备的？"
- 设计动机："为什么不直接用 LangChain？为什么不上 async ORM？"
- 数字追问："你说 96.9% Hit@3，样本是 835 条，是怎么标注的？"

这份文档就是**把这些可能被问的问题全部列出来 + 给出像样的答案**。读者拿着它能应对面试官从浅入深、从横向到纵向的各种追问。

# 两阶段协作流程（核心机制）

> 这份文档**必须用两个角色协作产出**，因为单一视角容易遗漏问题或给出敷衍答案。

## 如果你有 sub-agent 能力（推荐）

请按下面流程做：

### 阶段 1 · 出题 Agent

**角色**：硬核技术面试官。Senior+ 级别，10 年以上经验。看过候选人简历，看过项目代码，知道哪些是"漂亮话"哪些是真活。

**任务**：基于"项目事实速查"（见后文）和必读源码，**穷尽**地列出面试官可能问的问题。每个技术点至少 3-5 个不同切入角度的问题。

**输出格式**：纯问题列表，按主题分组。每个问题独立编号。**不要写答案**。每个问题后面附一个 1-句"问这道题的目的"（面试官想考察什么）。

**目标问题数**：**不少于 200 条**。少于 200 条说明覆盖不够，重出。

**特别要求**：
- 每个主题至少包含 1 个"为什么不用 X"的对比题
- 每个主题至少包含 1 个"参数为什么是这个值"的取舍题
- 每个主题至少包含 1 个"异常路径"问题（X 失败了你怎么办）
- 不要出 "什么是 RAG" 这种背书题；要出"这个项目里 RAG 链路的某个具体设计"
- 不要出"项目用了什么技术"这种综合题；要出"这个具体决策的动机"

### 阶段 2 · 答题 Agent

**角色**：候选人本人。基础较薄弱、但项目是真做过的开发者。需要在面试时把答案讲清楚，遇到不懂的概念时承认不懂（但用大白话尽量推理）。

**任务**：拿到阶段 1 的题目列表，对**每一题**给出**详尽的答案**。

**答案要求**：
- **每个答案 3 段式**：
  - 段 1 · **直接回答**（1-3 句给结论，应付时间紧的面试官）
  - 段 2 · **展开讲流程**（"我们项目里这块是这么做的：当 X 发生时，系统首先……然后……"。讲清流程和动机）
  - 段 3 · **可能被追问的点 + 怎么接**（列出 2-4 个面试官可能追问的小钩子 + 简短的承接方向）
- **必须用源码事实支撑**：答案里出现的字段名、参数值、流程顺序必须和源码一致；不允许编造。
- **对比题必须列出至少 2 个备选 + 你为什么不选它们**（每个备选 1-2 句话理由）
- **不懂的诚实说不懂**：如果某个深技术点（比如 HNSW 内部图遍历算法）超出项目范围，直接说"这块我没深入到底层算法实现，只知道它是分层小世界图的一种近似最近邻索引，比暴力扫快很多——具体内部图怎么走我答不上来"。**不要瞎编**。
- **追问钩子**要现实：每个钩子都是面试官**真的会问**的下一步，不是凑数。

### 阶段 3 · 合并 + 校对

把阶段 1 + 2 的产出整合成最终文档，按主题分章节。每章节先列"本章高频问题清单"（只编号 + 题目），然后逐题展开 3 段式答案。

## 如果你只有单 LLM、没有 sub-agent 能力

按"阶段 1 → 阶段 2 → 阶段 3" 顺序在一次输出里完成，把自己想象成两个角色轮流扮演。先把所有题目都列完（阶段 1），然后再回头逐题答（阶段 2）。**不要边出题边答**——这会导致出题视角被答题难度污染。

# 读者画像

- **基础较薄弱**的开发者
- 面试前用这份文档做最后冲刺复习
- 不允许跳过任何术语解释

# 文风要求（违反任何一条都要重写）

1. 全文简体中文，代码/类名保留英文
2. 答案里**几乎不出现代码**，最多 1-3 行伪代码
3. 概念第一次出现必须 30-80 字白话解释（之后不重复）
4. 流程必须用 "首先…然后…接着…" 的句式
5. 任何"魔法数字"（如 0.5 阈值、0.65 置信度、6 轮压缩、25 步预算）出现时必须解释**为什么是这个值**而不是别的
6. 任何技术选型出现时必须列对比 + 否决原因
7. **不允许写"这是个好实践"这种空话**——要么解释为什么是好实践，要么不写

# 必读源码（同 ① 号文档相同清单）

> 完整清单见提示词 ① `01-project-technical-doc.md` 的"必读源码清单"。这里不重复列。请优先读：
> - `backend/app/qa_pipeline/agent_executor.py`
> - `backend/app/agent_runtime/query_engine.py` + `context_compactor.py`
> - `backend/app/services/mock_interview_service.py`
> - `backend/app/services/interview/analysis_orchestrator.py`
> - `backend/app/services/voice/interview_analysis_service.py`
> - `backend/app/services/memory/` 全部
> - `backend/app/rag/retriever.py` + `bm25_cache.py` + `hybrid.py`
> - `backend/app/core/model_registry.py`
> - `backend/app/core/security.py` + `services/user_api_key_service.py`
> - `backend/app/services/file_validation.py`
> - `evaluation/` 全部

# 项目事实速查

（同 ① 号文档"项目事实速查"那一节，此处不重复展开。请直接引用以下关键数据：）

| 数据点 | 值 | 来源 |
|---|---|---|
| 检索 Hit Rate@3 | 96.9% | 835 样本评测 |
| 检索 MRR@5 | 0.950 | 同上 |
| 检索 P95 延迟 | 98ms | 同上 |
| RAGAS 忠实度 | 92.5% | 200 样本 |
| RAGAS 上下文精确度 | 93.2% | 同上 |
| RAGAS 上下文召回率 | 98% | 同上 |
| E2E P95 响应 | ~8s | 端到端 |
| 嵌入维度 | 1024 | BGE-M3 |
| Agent 最大步数 | 25 | `AGENT_MAX_STEPS` |
| Agent 工具超时 | 30s | `AGENT_TOOL_TIMEOUT_SECONDS` |
| 单工具最多调用 | 8 次 | `AGENT_MAX_CALLS_PER_TOOL` |
| Agent 总运行时上限 | 180s | `AGENT_MAX_RUNTIME_SECONDS` |
| 工具结果磁盘溢出阈值 | 30K 字符 | `AGENT_PERSIST_THRESHOLD` |
| 单轮工具结果总预算 | 100K 字符 | `AGENT_TURN_BUDGET_CHARS` |
| 记忆置信度阈值 | 0.65 | `MIN_CONFIDENCE` |
| 压缩双阈值 | tokens≥6000 + turns≥4，或 turns≥15 | `compaction_service` |
| 摘要 token 上限 | 2500 | `SESSION_STATE_MAX_TOKENS` |
| 召回融合权重 | 0.60 vector + 0.35 lexical + 0.15 importance + 0.05 recency | `hybrid.py` |
| 陈旧阈值 | 2 天 | `STALENESS_THRESHOLD_DAYS` |
| chunk_size | 512 tokens | SentenceSplitter |
| chunk_overlap | 64 tokens | 同上 |
| RAG 防幻觉分数阈值 | 0.5（reranker 后） | `RAG_MIN_SCORE` |
| RAG 词法兜底覆盖率 | 0.35 | `RAG_LEXICAL_FALLBACK_MIN_OVERLAP` |
| Reranker top_n | 5 | `RERANK_TOP_N` |
| 限流 4 档 | 5 / 10 / 20 / 60 per min | `rate_limit.py` |
| JWT access 寿命 | 30 分钟 | `ACCESS_TOKEN_EXPIRE_MINUTES` |
| JWT refresh 寿命 | 7 天 | `REFRESH_TOKEN_EXPIRE_MINUTES` |
| HNSW M / efC / efS | 16 / 200 / 64 | Milvus 索引参数 |
| Mock follow-up 最大深度 | 2 | `MAX_FOLLOW_UP_DEPTH` |
| Mock 每 6 轮摘要 | `SUMMARY_EVERY_N_TURNS=6` | 同上 |
| 文件上限 audio_clip / audio_upload / resume / jd | 25M / 500M / 10M / 10M | `file_validation.py` |

# 必须覆盖的主题清单（不许漏，缺一项都算不达标）

按这个目录组织最终文档：

## 主题 A · 整体架构与选型
- 为什么 FastAPI 而不是 Django / Flask
- 为什么 Celery 而不是 RQ / Dramatiq / 直接用 asyncio.create_task
- 为什么 SQLAlchemy 而不是 Tortoise ORM / Peewee
- 为什么 LlamaIndex 而不是 LangChain / Haystack
- 为什么 SSE 而不是 WebSocket / 轮询
- 为什么 nginx 而不是 Caddy / Traefik
- 为什么 Redis 而不是 Memcached / Valkey
- 为什么 Postgres 而不是 MySQL / SQLite for prod
- 为什么 Milvus 而不是 Chroma / Weaviate / Qdrant / pgvector
- 为什么 MinIO 而不是直接本地文件系统
- 单体架构 vs 微服务（为什么不拆）
- 异步 ORM 没用，那 async 优势在哪
- 这个栈在多大规模上还能撑住

## 主题 B · L1 QA 对话管道
- SSE 是什么、跟 WebSocket 怎么选
- `stream_chat_with_agent` 6 步流程细节
- planner 是怎么决定走 RAG 还是直接回答的
- query rewriter 解决什么问题（指代消解）
- 6 槽位上下文每个槽位装什么、预算怎么分
- 记忆和知识库为什么并发召回不串行
- 用户档案为什么绕过召回开关直接注入
- recall_policy 召回开关的设计动机
- `_humanize_exc` 把哪些异常翻成什么
- 持久化为什么放在响应后
- post_turn_maintenance 为什么不阻塞响应

## 主题 C · L2 ReAct Agent 管道
- ReAct 模式是什么
- function calling 跟 prompt-based tool use 怎么选
- QueryEngine 三阶段（prepare / loop / finalize）
- 为什么 finalize 用 try/finally 保证写 trace
- 工具自注册机制怎么工作
- 7 个内置工具职责拆分
- streaming 模式下 tool_call 怎么聚合
- 工具结果磁盘溢出阈值为什么是 30K
- 上下文压缩 3 步骤（dedup / summarize / truncate args）
- 反应式压缩 + circuit breaker
- 步数预算 25、单工具 8 次的依据
- harness_events 8 种事件协议
- agent_trace 表怎么用于复盘

## 主题 D · L3 模拟面试管道
- "Runtime Director" 模式 vs 传统先生成完整 plan
- DeepSeek 100K prompt cache 怎么用、`cacheable_prefix` 怎么冻结
- `generate_brief` 阶段 LLM 产出什么
- `run_director` 输出的 `DirectorOutput` 字段
- 状态机严格顺序（snapshot → append → 增进度 → swap）的必要性
- MAX_FOLLOW_UP_DEPTH=2 的依据
- 每 6 轮 summarize_history 触发逻辑
- 5 个面试阶段流转规则
- stale shell 自动清理设计
- session_state schema v1 → v2 演化怎么处理向后兼容

## 主题 E · L4 录音分析管道
- Celery 异步是必须的吗、能放到 BackgroundTasks 吗
- 任务幂等性（status check gate）
- WhisperX 选型理由 vs OpenAI Whisper / 直接 ffmpeg + faster-whisper
- Pyannote 声纹分离作用、为什么不靠声学差异硬切
- ASR 本地 vs 远程的选路策略
- Stage 2 QA 提取 120K 阈值的依据
- 句级切分 + 20% 重叠 + 合并的策略动机
- Stage 3 sliding window（prev=3, next=2）的设计动机
- Map-Reduce 模式 vs 单次大 prompt
- 失败处理 mid-retry vs final-attempt 区分
- `_generate_debrief_summary` 为什么 fail-safe

## 主题 F · 记忆子系统
- 为什么要两类记忆而不是一类
- user_profile 为什么放弃 normalized_key 改 patch 文档
- patch 的 3 种操作（add/update/delete）
- interview_fact 的 confidence 阈值 0.65 怎么定的
- 压缩双阈值公式的取舍
- 6 章节摘要模板的设计意图
- 混合召回 4 项加权 0.60/0.35/0.15/0.05 的依据
- 陈旧标记 staleness_note 的作用
- 双游标（compaction / memory_extraction）独立推进的设计
- per-session asyncio.Lock 避免什么并发问题
- Milvus 单例（双检锁）解决什么性能问题
- overwrite=True 路径为什么要锁内重建

## 主题 G · RAG 子系统
- RAG 是什么、为什么不直接让 LLM 答
- 嵌入模型工作原理
- 向量数据库 / Milvus 跟普通数据库的区别
- BM25 跟向量检索互补在哪
- HNSW 是什么（白话）、M=16 / efC=200 / efS=64 这三个参数控制什么
- 自适应分块（按文件类型选 NodeParser）的动机
- chunk_size=512 / overlap=64 的依据
- 混合检索完整链路（向量 → BM25 → 融合 → Rerank → 阈值）
- reciprocal_rerank 融合算法是什么
- BGE-Reranker 跟单纯 cosine 差在哪
- 阈值 0.5 跟兜底 0.35 怎么定的
- `[SYSTEM_EMPTY_WARNING]` 占位符跟直接返回 [] 的差别
- 多租户隔离三层强制（为什么不能只一层）
- BM25 缓存 1h TTL + 主动失效的取舍
- BGE-M3 跟 BGE-large / text-embedding-3 怎么选
- 嵌入模型多 provider 抽象的好处

## 主题 H · 多模型抽象
- role / provider / model 三层为什么这么分
- OpenAI-compatible 协议是什么
- per-user API key 加密存储为什么不 hash
- Fernet 是什么、为什么够用（128 位 AES）
- MultiFernet 怎么做密钥轮换
- SECRET_KEY 派生 Fernet key 安全吗
- 运行时切换的原子性怎么保证
- 切换后 LLM client 缓存怎么清
- 24h 模型目录缓存的依据
- 401/429/超时为什么要 humanize

## 主题 I · 安全
- JWT vs Session Cookie
- access 30min / refresh 7d 的依据
- refresh 轮换为什么
- jti 黑名单存哪、为什么 fail-closed
- 邮箱验证码反枚举设计
- bcrypt 的 work factor
- 限流 4 档（5/10/20/60）的设计
- slowapi Redis 后端解决什么问题
- 文件上传魔字节校验为什么不 libmagic
- 4 类 purpose 上限怎么定的
- SECRET_KEY 生产硬阻断
- Docker 非 root 的攻击面收益
- nginx 5 个安全头各防什么
- HSTS 为什么只在 HTTPS server block
- CSP 怎么写不过严
- CORS allowlist 替代通配
- 路径穿越保护（S3 key 强制 user_id 前缀）

## 主题 J · 可观测性
- 错误监控 vs APM vs 指标
- Sentry 5 个 integration 各做什么
- before-send 钩子的必要性
- LangSmith 双层包装（monkey-patch + 实例级）
- 为什么单层不够
- 全局未捕获异常 handler 强制 traceback
- 自家 JSONL metrics 跟 Prometheus 怎么选
- agent_trace 持久化的复盘价值

## 主题 K · 评测体系
- Hit Rate@K 怎么算、跟 Recall@K 区别
- MRR 是什么、为什么取倒数
- nDCG 是什么、为什么对位置敏感
- 837 条 golden_dataset 是怎么构造的
- 200 条 RAGAS 跑要多久、成本
- RAGAS 4 件套（忠实度/CP/CR/factual_correctness）每个看什么
- 这些指标真能反映线上效果吗
- 多租户隔离 0 violations 怎么测
- P95 怎么测的（统计学解释）
- 离线评测的局限

## 主题 L · 数据库与迁移
- 19 → 1 alembic squash 的动机和风险
- session_state 用 JSONB 而不是建子表的取舍
- 关键索引设计（chat_messages.session_id+seq、interview_records.user_id+created_at）
- 软删除 vs 硬删除策略
- 跨表事务怎么处理（mock_interview /finish 的 4 个写）

## 主题 M · 前端
- React 18 + Vite 5 vs Next.js 怎么选
- Zustand vs Redux / Context
- SSE 消费用 fetch + ReadableStream 还是 EventSource
- 拦截器自动刷新 JWT 的边界条件（并发 401 怎么办）
- Tailwind 跟 styled-components 怎么选

## 主题 N · 部署与运维
- docker-compose 两套 profile
- 卷映射 `./data:/app/data` 的权限处理
- entrypoint 用 gosu 切用户的设计
- alembic upgrade head 何时跑（启动时 vs CI 时）
- 健康检查 endpoint 设计
- nginx TLS 终结的部署链路
- 生产部署 checklist 至少 10 条

## 主题 O · 性能与扩展性
- 当前架构能撑多少并发用户
- 瓶颈是 LLM 调用、数据库、还是别的
- Milvus 单例修复了什么性能问题
- BM25 缓存命中率怎么估
- async ORM 完整迁移的成本和收益
- 如果用户量翻 100 倍，哪几个地方先撑不住

## 主题 P · 工程细节
- 测试覆盖率怎么估（260 个测试是什么粒度）
- 测试为什么用 in-memory SQLite 而不是 testcontainers
- mock LLM / mock embedding 的策略
- conftest fixture 设计（db_session SAVEPOINT 模式）
- CI 流程（push 到 main 触发什么）
- 整套代码量大概多少行

# 自检清单（写完后逐项核对）

- [ ] 总问题数 ≥ 200 条
- [ ] 16 个主题（A-P）每个至少 8 个问题
- [ ] 每个问题都按 3 段式（直接回答 / 流程展开 / 追问钩子）
- [ ] 选型对比题数 ≥ 30
- [ ] 参数取舍题数 ≥ 25
- [ ] 异常路径题数 ≥ 15
- [ ] 不懂的诚实说不懂（如果碰到深技术点）
- [ ] 没有编造源码不支持的字段名 / 参数 / 流程
- [ ] 全中文，几乎不出现代码
- [ ] 概念第一次出现都有白话解释
- [ ] 字数 ≥ 50000

# 开始写

请先确保 `docs/interview-prep/` 目录存在，然后开始。

**严格按"阶段 1 → 阶段 2 → 阶段 3"流程**：先列完所有问题（按主题分组），再回头逐题答。**不要边出题边答**。

写完后输出总结：覆盖了多少题、各主题分布、是否所有 16 个主题都达到下限、有没有任何问题答案做了合理推测（如果有，单独列出"推测点"）。
