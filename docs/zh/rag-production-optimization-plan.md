# RAG 生产优化执行文档

> 状态: 已确认
> 范围: 只覆盖 RAG 生产运行策略，即 缓存 -> 异步 -> 文档级 reindex -> 权限 -> 降级。
> 用途: 本文沉淀当前源码基线、最终优化决策和可执行规格，作为后续交给 Claude/其他 Agent 执行的依据。

## 1. 核心判断

生产优化不是重新设计一套 RAG，而是把建库、检索、生成阶段已经确认的能力变成可靠运行策略。

已确认总原则:

- 不做业务结果缓存: 不缓存检索结果、不缓存最终答案、不缓存 per-user RAG context。
- 可以做基础设施缓存: 模型实例、provider client、parser client、embedding tokenizer、任务内临时文件。
- L1 RAG 相关基础设施缓存只做当前确有收益的对象；不要为模块常量形式的 prompt 文本设计缓存层。
- 系统级基础设施缓存如果会影响 embedding、reranker、ASR、LLM、parser 等多个模块，需要单独评估跨模块影响。
- BM25 不需要每次重建；当前 Milvus 2.6 server-side BM25 会维护 sparse inverted index。
- API 不直接做重活；解析、OCR、embedding、index 写入放到 worker/outbox。
- Postgres 是事实源，Milvus 是可重建索引副本。
- user_id pre-filter 是 P0 安全边界。
- 降级要显式、可观测，不做静默质量退化。

## 2. 缓存

### 2.1 不做业务结果缓存

本轮不做:

```text
embedding cache
retrieval result cache
final answer cache
per-user RAG context cache
```

原因:

- 用户权限和文档更新会让结果缓存变脏。
- RAG query 变化大，缓存命中率不一定高。
- 答案缓存容易缓存旧知识、错引用或过期 sources。
- 检索缓存需要绑定 `user_id`、embedding identity、索引状态、文档删除状态，会把版本复杂度带回来。

### 2.2 BM25 不需要每次重建

当前项目不是“每次查询时从数据库读所有 chunk 临时构建 BM25 corpus”的模式。

当前实现:

```text
document text 写入 Milvus text 字段
  -> Milvus BM25 Function 生成 sparse vector
  -> SPARSE_INVERTED_INDEX 建索引
  -> 查询时 hybrid_search 直接做 BM25 sparse search + dense search
```

因此:

- BM25 index 由 Milvus collection 维护。
- 每次检索不需要重建 BM25。
- 不需要为 BM25 单独设计业务缓存。

### 2.3 L1 RAG 相关基础设施缓存

可以直接设计:

```text
tokenizer 实例缓存
source hydrate 查询的单请求内批量缓存
parser/orchestration 单任务临时文件缓存
对象存储文件下载的任务内临时缓存
```

原则:

- 只缓存不可变或单请求/单任务内可安全复用的对象。
- 不缓存跨用户的语义结果。
- 不让缓存绕过 user_id 安全过滤。
- 缓存命中与否不能改变可见性和权限判断。

### 2.4 系统级基础设施缓存

需要跨模块评估后再做:

```text
embedding model 实例缓存
reranker model 实例缓存
LLM client / provider client 连接池
parser client 实例缓存
ASR/Whisper model 实例缓存
```

这些缓存可能同时影响:

- RAG 建库/检索
- 简历解析和匹配
- 面试录音转写
- L2 agent 工具调用
- 模型运行时 provider 配置

要求:

- provider/model/config 变化时必须可刷新或重建。
- 本地模型缓存失败要有清晰错误。
- 远程 client cache 不能泄漏用户 API key 或 provider override。
- 跨模块共享前要确认生命周期、线程安全和配置刷新边界。

## 3. 异步与 Outbox

已确认:

- 解析、OCR、embedding、索引写入属于重任务，必须在 worker 中执行。
- 当前项目已有通用 outbox 基础设施；Milvus 写入、删除、文档级 reindex 通过新增 outbox job type 和 handler 自动重试，不新建 outbox 表。
- outbox job 必须幂等。
- reindex 从 Postgres facts 重建，不从旧 Milvus rows 反推事实。

策略:

```text
API 请求
  -> 创建/更新 KnowledgeDocument 状态
  -> 投递 worker task
  -> worker 执行解析/清洗/切分/标注/向量化
  -> document_chunks 写 pending
  -> Milvus upsert/delete
  -> 成功后 document_chunks 标记 indexed
  -> 失败写 outbox 或 failed/pending 状态
```

删除策略:

```text
删除请求
  -> Postgres 标记 document deleted_at/status=deleting，让读路径立即不可见
  -> 标记或删除 chunks
  -> Milvus delete by document_id
  -> 失败写 outbox retry
```

## 4. 文档级 Reindex

已确认:

- 不做 chunk 级增量索引。
- 不做 `document_version`。
- 做文档级 reindex。

能力要求:

- 按 `document_id` 重建单文档 Milvus rows。
- 按 `user_id` / `category` 分批重建。
- 全 collection drop + reingest 作为灾难恢复手段。
- consistency scan 输出 missing_in_milvus、stale_in_milvus、metadata_mismatch、dimension_mismatch。

## 5. 权限

已确认:

- user_id 是 P0 安全边界。
- Milvus 检索必须 pre-filter: `user_id == users.id`。
- Query Planner 不生成权限或 metadata filter。
- 不做复杂 ACL / permission 字段。
- Postgres hydrate 继续确认 document/chunk live 状态。

缓存约束:

- 任何缓存都不能绕过 user_id 过滤。
- 不缓存跨用户检索结果。
- 不缓存跨用户 context。
- provider client / API key cache 必须以用户和 provider 配置隔离。

## 6. 降级策略

降级不是静默降低质量，而是明确边界、可观测、可恢复。

### 6.1 Parser 降级

已在建库优化中确认:

```text
LlamaParse / Docling 平行一等解析器
  -> 主解析器失败后使用备用一等解析器
  -> 格式专用 lightweight fallback
  -> 失败后友好错误
```

### 6.2 Planner 降级

已在检索优化中确认:

```text
Query Planner 失败
  -> 原始用户问题 fallback 检索
  -> 内部 prompt/context 标记 planner_failed
  -> 最终用户答案不提 planner 失败
```

### 6.3 Reranker 降级

策略:

- 本地 reranker 初始化失败: fail loud，提示维护者修复基础模型配置。
- 远程 reranker 单次调用失败: 返回 retriever fallback top-N，但必须标记 `score_source=retriever_fallback`。
- fallback 结果不能和正常 reranker score 混用。
- fallback 结果不能继续套用正常 reranker 的 `RAG_MIN_SCORE=0.5`；默认跳过 reranker 阈值，仅按 fallback top-N 返回并写 trace。

### 6.4 Milvus 降级

策略:

- 检索时 Milvus 不可用: RAG context 为空，L1 可按普通问题回答，但不能伪装成知识库证据。
- 写入/删除 Milvus 失败: 写 outbox retry。
- 删除失败时，Postgres document/chunk 已不可见，读路径不能返回已删除文档内容。

### 6.5 引用校验降级

策略:

- 非法引用或缺引用: 记录 warning。
- 本轮不重跑 LLM。
- 不使用 LLM 做二次审核。
- 前端 sources 映射不到的引用不展示 source card。

## 7. 跨模块执行顺序

执行顺序按风险和依赖分段，不要求一次性大改:

### Phase 0 文档与接口拍板

- 先确认 `[K#]` 编号由 context assembly 在 token 裁剪后的最终 chunks 上生成。
- 确认 source schema 以检索文档为唯一权威。
- 确认多子问题召回只影响候选，最终统一 rerank。
- 确认 eval fixture 语料、bad case schema、trace 隐私边界。
- 状态: 以上事项已全部写入五份文档并确认完毕，Phase 0 无遗留；开工直接从 Phase A 开始。

### Phase A 检索、生成、Sources 通道

- dense/sparse 真分路。
- `FUSION_TOP_K=12` 和多子问题候选召回。
- 确定性去重、reranker fallback 信号、`score_source`、fallback 阈值策略。
- Postgres hydrate + live check。
- context assembly 生成 `[K#]` 和最终 sources。
- engine / StrategyContext / StrategyResult / SSE / `content_blocks_json` / 前端 source card 打通。
- 重写 L1 `RAG_SYSTEM_RULES` 和轻量引用校验。
- 删除旧 `lexical_overlap`、`[RAG Score | Lexical Overlap]`、`[SYSTEM_EMPTY_WARNING]` 和 retriever 自拼 context 字符串。
- 多子问题（planner `sub_queries` + map-reduce 召回）放在 Phase A 末尾作为独立提交落地，与 dense/sparse 分路和 sources 通道解耦，便于隔离回归。

### Phase B 建库基础能力

- Alembic migration 增加 `document_chunks.page_start/page_end/token_count`。
- 写入顺序改为 Postgres pending -> Milvus -> Postgres indexed，同时覆盖 `ingest_document` 和 `ingest_text`。
- S0 清洗。
- `DocumentParser` 抽象先包装现有 LlamaParse / PyMuPDF / LlamaIndex reader。
- 上传格式白名单: 后端校验 + worker 防御 + 前端 `accept`。
- 解析观测、embedding 维度/数量校验和 embedding identity 检查。
- Docling / LibreOffice / OCR 作为后续独立执行包，不阻塞 Phase B 基础链路。

### Phase C Outbox 与 Reindex

- 复用现有 `OutboxJob`，新增 Milvus upsert/delete/reindex job type 和 handler。
- 扩展现有 `reingest_hybrid.py`，支持 document/user/category 维度，不另写第二套 reingest 脚本。
- consistency scan 升级为 node_id 级，替换数量级 drift 检查。

### Phase D 评测

- 建立专用 eval 用户和 fixture 文档集。
- 实现 `evaluation/rag/` 的 ingestion/planner/retrieval/citation/generation runner。
- 先跑 baseline，再定义 quality gate。
- 旧 `evaluation/` 冻结或 skip，不在旧 runner 上修补漂移。

## 8. 模块边界

应该抽象:

- `app/rag/parsing/`: `DocumentParser` 协议、LlamaParse/PyMuPDF/LlamaIndex reader 包装、orchestrator。fallback、错误翻译、观测放在 orchestrator，按格式 `if/elif` 分发即可，不做插件注册表。
- `app/rag/cleaning.py`: S0 清洗纯函数，输入 text 输出 cleaned text + profile，不做复杂 pipeline 类层次。
- source hydrate: 独立函数或 service，统一 join `document_chunks`、`knowledge_documents`、`file_assets`，供 L1、L2 工具、评测 runner 共用。
- context assembly: `[K#]` 编号和最终 sources 的唯一所有者。
- `evaluation/rag/`: datasets/runners/metrics/reports 分层，trace 字段以 `trace_schema.py` 为唯一权威。

沿用现有抽象:

- embedding provider registry。
- reranker provider registry，只补 fallback 信号，不重写 provider 体系。
- Milvus hybrid/RRF，不做应用层融合框架。
- OutboxJob/outbox_service，不新建 outbox 表或队列。

明确不抽象:

- 不做 retrieval pipeline 中间件链。
- 不做去重策略接口，一个确定性函数即可。
- 不做 prompt 模板缓存层或 prompt manager。
- 不做通用 provider 超级抽象。
- 不做 `ParseResult` tables/images/element tree，除非已有消费方。

## 9. 决策记录

| 日期 | 环节 | 决策 | 理由 | 状态 |
| --- | --- | --- | --- | --- |
| 2026-06-09 | 缓存 | 不做业务结果缓存；只做安全的基础设施缓存。L1 RAG 相关基础设施缓存限于 tokenizer、单请求 hydrate、任务内临时文件等真实收益对象；不为 prompt 模板常量单独设计缓存层。 | 检索/答案/context 缓存容易受权限、文档更新和引用过期影响；prompt 文本本身是模块常量，缓存抽象没有收益。 | 已确认 |
| 2026-06-09 | BM25 | Milvus server-side BM25 不需要每次检索重建，不为 BM25 另做业务缓存。 | 当前实现使用 Milvus BM25 Function + sparse inverted index，不是每次查询临时构建 BM25 corpus。 | 已确认 |
| 2026-06-09 | 异步/Outbox | 解析、OCR、embedding、index 写入在 worker 中执行；复用现有 OutboxJob/outbox_service/drain_outbox_jobs，为 Milvus upsert/delete/reindex 注册 job type 和 handler。 | 重任务不能阻塞 API；Milvus 是索引副本，现有 outbox 已具备重试、幂等和 handler 注册能力，不能重复造轮子。 | 已确认 |
| 2026-06-09 | 权限 | user_id 是唯一 P0 pre-filter；缓存不能绕过 user_id；不做复杂 ACL。 | 当前产品权限边界是个人知识库隔离，过早引入复杂 permission 会增加 schema 和缓存复杂度。 | 已确认 |
| 2026-06-09 | 降级 | 降级必须显式可观测: parser fallback、planner fallback、remote reranker fallback、Milvus outbox retry、引用校验 warning。 | 生产降级要避免静默质量退化，让用户体验可控、开发者可排查。 | 已确认 |
