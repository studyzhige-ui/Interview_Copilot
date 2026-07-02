# RAG 检索优化执行文档

> 状态: 已确认
> 范围: 只覆盖 RAG 检索链路，即 Query 改写 -> Metadata 过滤 -> 多路召回 -> 结果融合 -> Rerank 精排 -> 去重和补上下文 -> 上下文组装。
> 用途: 本文沉淀当前源码基线、最终优化决策和可执行规格，作为后续交给 Claude/其他 Agent 执行的依据。

## 1. 当前源码基线

关键文件:

- `backend/app/conversation/query_planner.py`: 每轮对话的 Query Planner，负责判断是否需要知识库检索，并生成 `dense_query` / `sparse_query`。
- `backend/app/conversation/engine.py`: L1 chat 在 `_prepare()` 阶段调用 planner 和知识库检索；L2 agent 模式跳过 engine-side RAG。
- `backend/app/agent_runtime/tools/knowledge.py`: L2 agent 的 `search_knowledge` 工具。
- `backend/app/rag/knowledge_retriever.py`: 检索 facade，统一给 chat 和 agent 调用。
- `backend/app/rag/retriever.py`: 核心检索逻辑，负责 Milvus hybrid search、rerank、阈值过滤、结果封装。
- `backend/app/rag/milvus_hybrid.py`: Milvus dense + BM25 hybrid search 和 RRF 融合。
- `backend/app/rag/reranker_registry.py`: reranker provider registry。
- `backend/app/services/chat/context_assembly_pipeline.py`: 把 rerank 后的 chunks 装配进 `[Retrieved Context]`。

当前优点:

- 已有 Query Planner，能基于当前问题和最近对话判断是否需要检索。
- 已有 dense + BM25 hybrid search，Milvus 内部用 RRF 融合。
- 检索阶段强制 `user_id == users.id`，有明确租户隔离。
- 已有 reranker，且 reranker 作为质量闸门。
- 已有 `RAG_MIN_SCORE`，低相关结果会被拦截，避免低质量 context 污染生成。
- 删除文档后有 `_live_document_ids()` 兜底过滤，避免 Milvus 残留 rows 被返回。
- L2 agent 不在 engine 阶段自动注入 RAG，而是通过工具按需检索，避免双重检索。

当前主要问题:

- planner 产出 `dense_query` / `sparse_query`，但 `KnowledgeRetriever` 当前用 `query = sparse_query or dense_query` 合并成单 query，dense/BM25 没有真正使用不同 query。
- Metadata filter 在普通检索路径只需要 `user_id` 安全隔离；`source_kind` 是来源标识，不作为普通检索过滤字段；`category` 是知识库列表/管理标签，不作为默认检索过滤字段。
- `FUSION_TOP_K=6`、`RERANK_TOP_N=5` 候选量偏小，给 reranker 的选择空间有限。
- 没有显式去重逻辑，重复 chunk 或相似 chunk 可能一起进入 context。
- 没有相邻 chunk 回填，也没有 parent chunk 回填。
- source 返回和 `[Retrieved Context]` 里缺少 document title、page、chunk_index、heading_path 等溯源信息。
- context 组装只按 token budget 截断，不做来源多样性、文档多样性或证据压缩。
- remote reranker 失败时会返回 unranked top-N；这些 score 与 reranker score 标尺不同，需要诊断标识。
- 检索日志有 top candidates，但缺少结构化 trace，难以复盘 query 改写、召回、rerank、过滤各阶段发生了什么。
- retriever 当前还会拼接 `RAG Score` / `Lexical Overlap` 文本和 `lexical_overlap` 字段；新链路应由 hydrated sources + reranker score 替代，避免旧分数字段和新引用格式并存。

## 2. 检索链路执行规格

### 2.1 Query 改写

当前源码基线:

- `plan_query()` 使用 fast LLM 输出:

```json
{
  "needs_knowledge_retrieval": true,
  "dense_query": "...",
  "sparse_query": "...",
  "load_strategy": false
}
```

- planner 会用最近对话做指代消解。
- planner fallback 是保守策略: 不检索知识库。
- L1 chat 使用 planner 结果触发检索。
- L2 agent 不使用 engine-side RAG，改由 `search_knowledge` 工具按需检索。

已确认:

- Query 改写主要解决: 指代不清、问题过短、表达不一、包含多个子问题。
- Query Planner 现在同时承担 RAG 路由、query rewrite、memory/material load 决策，prompt 需要正式规范重写。
- `dense_query` / `sparse_query` 必须真正分开使用: dense query 用于向量检索，sparse query 用于 BM25。
- 当前源码分路主要需要改两层调用方: `KnowledgeRetriever.retrieve()` 不再 `query = sparse_query or dense_query` 合并；`retriever.query_knowledge_base()` 接收 dense/sparse 两个 query 并分别传给 embedding/BM25。`milvus_hybrid.hybrid_search()` 当前已经支持 `query_text` 与 `query_dense` 分离，不需要重写其签名。
- Query Planner 不生成 metadata filter，避免把权限/分类过滤交给 LLM 判断。
- 必须保留 `original_query`、`dense_query`、`sparse_query`、`needs_knowledge_retrieval` 到 trace，方便排查改写是否改坏。
- planner 失败时用原始用户问题 fallback 检索，不能直接放弃检索。
- planner 失败信息可以进入内部 prompt/context，提醒生成模型自行判断检索内容是否足够可靠；最终用户答案中不要提到 planner 失败。
- planner fallback 会把原本“失败时不检索”的保守策略反转为“使用原始问题检索”，实现时必须记录 `planner_failed=true` 并观察 fallback_rate，避免 planner 持续故障导致每条闲聊都触发 embedding/Milvus/rerank。
- 对明显多子问题允许拆分为多个子查询；正常单问题不拆。
- 每个子问题有自己的召回 top_k；多子问题每个子问题候选量小于单问题，避免 fan-out 撑爆候选集。
- L2 agent 链路不修改，`search_knowledge` 继续由 agent 自己提供 query，不额外套 planner rewrite。
- L2 agent 调用知识工具时可把同一个 query 同时作为 dense/sparse query 传入新接口，保持现有行为。

输出标准:

- `dense_query`: 自然语言、语义完整、独立可理解；必须消解“这个/它/上面那个”等指代；适合向量语义检索。
- `sparse_query`: 短关键词串，保留技术名词、实体、框架名、错误码、API 名称；适合 BM25。
- 不编造用户没提到的技术栈、版本、约束或场景。
- 多子问题拆分只在问题明显包含多个独立目标时触发，例如“分别解释 A 和 B，并比较 C”；普通长句、追问和单一复杂问题不拆。
- `sub_queries` 只允许一层数组，不做嵌套/递归子问题结构。

最终 Query Planner 输出结构:

```json
{
  "needs_knowledge_retrieval": true,
  "planner_failed": false,
  "dense_query": "Redis 缓存击穿、缓存穿透和缓存雪崩的区别与解决方案",
  "sparse_query": "Redis 缓存击穿 缓存穿透 缓存雪崩 解决方案",
  "sub_queries": [
    {
      "dense_query": "Redis 缓存击穿是什么以及如何解决",
      "sparse_query": "Redis 缓存击穿 解决方案"
    }
  ],
  "load_strategy": false
}
```

实现规则:

- 没有明显多子问题时，`sub_queries` 为空或省略，只使用顶层 `dense_query` / `sparse_query`。
- 有明显多子问题时，优先使用 `sub_queries` 检索；每个子问题单独召回，再汇总候选进入统一去重和 rerank。
- planner 输出的 `sub_queries` 需要有纯防御性硬上限 `MAX_SUB_QUERIES = 4`；这不是产品语义限制，而是防止 LLM 生成过多子问题导致 embedding/Milvus/rerank fan-out 失控。
- `planner_failed` 是代码在异常分支设置的运行时字段（`QueryPlan` 默认 `false`），不进入 planner prompt 的输出 JSON schema；LLM 不输出该字段，避免模型误报失败。
- planner 异常时构造 fallback plan:

```json
{
  "needs_knowledge_retrieval": true,
  "planner_failed": true,
  "dense_query": "<original user query>",
  "sparse_query": "<keyword fallback from original user query>",
  "sub_queries": [],
  "load_strategy": false
}
```

`sparse_query` fallback 应复用现有 `query_planner._keyword_query()` 或等价确定性函数，不再另写一套关键词提取逻辑。

### 2.2 Metadata 过滤

当前源码基线:

- Milvus expr 强制 `user_id == users.id`。
- 历史实现可选过滤 `source_kind`。
- 检索后再次用 `_metadata_matches_scope()` 做 user/source 防御性过滤。
- 排除 `personal_memory`。
- 通过 `_live_document_ids()` 过滤已删除或删除中的 knowledge document。

已确认:

- 用户隔离是 P0 安全边界，必须作为 Milvus server-side pre-filter: `user_id == users.id`。
- 普通知识库检索的 pre-filter 本轮只支持用户隔离。
- `source_kind` 更适合作为来源/溯源字段，不作为普通问答检索 filter。
- `category` 是用户查看和管理知识库文档时的 tag，不作为普通问答检索 filter。
- 删除态文档、chunk `index_status`、`deleted_at` 等属于 live check / consistency safety net，通过 Postgres hydrate/post-filter 确认。
- Query Planner 不生成 metadata filter。
- 不为了过滤而引入 LLM 分类判断。

明确不做:

- 不做 Query Planner 生成 `category` / `source_kind` filter。
- 不做复杂 ACL / permission filter。
- 不做 category 检索过滤和无结果自动放宽 filter。

### 2.3 多路召回

当前源码基线:

- `milvus_hybrid.hybrid_search()` 同时发起 dense ANN 和 BM25 sparse search。
- dense 使用 query embedding。
- sparse 使用同一个 `query_text`。
- Milvus 内部用 `RRFRanker()` 融合。
- `FUSION_TOP_K=6`。

已确认:

- 保持当前 Milvus hybrid search 主架构。
- 多路召回包含两路: dense vector retrieval + BM25 sparse retrieval。
- dense 使用 `dense_query`，BM25 使用 `sparse_query`。
- Milvus 内部执行两路召回并进入 RRF 融合。
- 放宽 rerank 前初始检索 top_k，给 reranker 更大候选空间。
- 明显多子问题采用 map-reduce 风格召回: 每个子问题单独召回候选，然后合并去重，再统一 rerank。
- 多子问题每个子问题的候选量比单问题更小，避免多问题把 context 撑爆。

最终参数:

- 单问题: `FUSION_TOP_K = 12`，`RERANK_TOP_N = 5`。
- 多子问题: 每个子问题 `SUB_QUERY_FUSION_TOP_K = 6`；合并去重后所有候选进入同一个 reranker，统一按 `RERANK_TOP_N = 5` 截断。
- `MAX_SUB_QUERIES = 4` 作为防御性硬上限。
- 检索参数面只保留 `FUSION_TOP_K`、`SUB_QUERY_FUSION_TOP_K`、`MAX_SUB_QUERIES`、`RERANK_TOP_N` 四个；不引入 `SUB_QUERY_RERANK_TOP_N`、`SUB_QUERY_CANDIDATE_QUOTA` 等额外参数。每子问题候选量已由 `SUB_QUERY_FUSION_TOP_K` 天然限定，再叠加配额参数是空操作。
- 最终进入 context 的数量仍由统一 reranker top_n 和 token budget 控制。

明确不做:

- 不实现 dense-only / BM25-only fallback。
- 不引入更多召回路，例如 query expansion、多 query paraphrase、web search。

### 2.4 结果融合

当前源码基线:

- Milvus 在一次 `hybrid_search()` 中用 RRF 融合 dense 和 sparse。
- 代码层没有额外融合逻辑。

已确认:

- 本轮继续使用 Milvus RRF，不在应用层重写融合算法。
- RRF 是第一层粗排融合，后续 reranker 是第二层精排。
- 应记录融合前/后候选数量和最终候选数量，用于 trace。

明确不做:

- 不做应用层自定义 RRF。
- 不做加权融合调参。
- 不做按 source_kind/category 的分桶融合。

### 2.5 Rerank 精排

当前源码基线:

- 系统级基础模型，由 `RERANKER_PROVIDER` / `RERANKER_MODEL` 配置。
- 默认本地 `BAAI/bge-reranker-v2-m3`。
- 支持 provider registry: `local`、`siliconflow`、`dashscope`、`jina`、`cohere`。
- `RERANK_TOP_N=5`。
- `RAG_MIN_SCORE=0.5`。
- reranker 初始化失败会 fail loud。
- remote reranker 调用失败时当前返回 unranked top-N，但没有把 fallback 状态显式传回 retriever；实现时必须补 `fallback_used` 或等价信号，否则 `score_source` 无法正确标记。

已确认:

- reranker 属于系统级基础模型，由开发者/维护者配置，不开放给普通用户运行时切换。
- 保持本地 reranker 和远程 API reranker 两种部署方式。
- 增大 rerank 前候选量。
- 多子问题召回后的候选统一进入同一个 reranker，由 reranker 做最终跨子问题排序。
- 保持 `RERANK_TOP_N` 控制最终候选数量。
- reranker 的 query 输入固定为顶层 `dense_query`；如果 planner fallback 或顶层 dense_query 为空，则使用 original user query。多子问题统一 rerank 不使用单个 sub-query 作为最终 rerank query。
- 由于 reranker 实例当前 top_n 在初始化时固定，实现时可让 provider 返回较大 top_n，再由调用方按 `RERANK_TOP_N` 截断；不要为了多问题动态 top_n 重建 reranker 实例。
- remote reranker fallback 结果必须标记 `score_source=retriever_fallback` 或等价字段，避免和正常 reranker score 混用。
- `score_source` 取值固定为 `reranker` / `retriever_fallback` 两个枚举值；旧实现中的 `retriever` 取值随哨兵协议一并退役，不再出现在新 sources/trace 中。
- remote fallback 不能继续套用 `RAG_MIN_SCORE=0.5` 这个 reranker 分数阈值；当前 fallback 返回的是 Milvus/RRF 排名分数，量级与 reranker score 不同，直接套用会把 fallback 结果全部过滤掉。

评测校准:

- 正常 reranker 分支保留当前 `RAG_MIN_SCORE=0.5`。
- `score_source=retriever_fallback` 分支使用独立策略: 跳过 reranker 阈值，仅按 top-N 返回，或使用单独配置 `RAG_FALLBACK_MIN_SCORE`；默认采用“跳过 reranker 阈值，仅按 top-N 返回”。
- 后续只通过 bad case 和评测数据校准阈值；不在实现阶段为不同 provider 设计复杂分数归一化。

明确不做:

- 不为不同 provider 设计复杂分数归一化。
- 不做多 reranker ensemble。

### 2.6 去重和补上下文

当前源码基线:

- 没有显式去重。
- 没有相邻 chunk 回填。
- 没有 parent chunk 回填。
- context assembly 只按 `RETRIEVED_CONTEXT_BUDGET=8000` 截断。

已确认:

- 只做快速保守去重: 同 `id`、同 `text_hash` 去重。
- 不做语义去重，避免引入模型成本和不稳定性。
- 不做相邻 chunk 回填，避免徒增上下文污染。
- 父子 chunk 已在建库阶段决定不做，因此这里不做 parent 回填。

去重位置:

- 单问题: Milvus RRF 后、rerank 前做一次去重。
- 多子问题: 每个子问题召回后先合并候选，再做一次全局去重，然后统一 rerank。
- 单查询单次 Milvus RRF 输出按 primary key 基本不会重复；id/node_id 去重主要用于多子问题合并路径。
- pre-rerank 的 `text_hash` 去重需要先 hydrate 少量候选，或对 Milvus 返回 text 现算规范化 hash。默认策略: 合并后先按 `node_id` 去重，再按规范化全文 exact hash 去重，统一 rerank 后对最终 top-N 做完整 hydrate。
- rerank 后可再做一次轻量去重，防止 remote fallback 或异常路径带入重复项。

去重规则:

```text
1. chunk id / node_id 相同 -> 去重
2. text_hash 相同 -> 去重
3. fallback: 规范化后的全文 exact hash 相同 -> 去重
```

保留策略:

- 保留分数更高的候选。
- 分数相同则保留 rerank/RRF 排名更靠前的候选。
- 多子问题命中同一 chunk 时，在 trace 中保留 matched_sub_queries，方便诊断。

明确不做:

- 不做语义相似度去重。
- 不做 LLM 判断重复。
- 不做相邻 chunk 回填。
- 不做 parent chunk 回填。

### 2.7 上下文组装

当前源码基线:

- context 形态:

```text
[K1] [source_kind score=0.873] chunk text
```

- 只包含 source_kind 和 score。
- 不包含 document title、file name、page、heading_path、chunk_index。
- token budget 使用 `RETRIEVED_CONTEXT_BUDGET=8000`。

已确认:

- 溯源机制需要单独设计: 既要让最终回答能直接看到来源，也要让前端能挂载文档、页码和 chunk。
- 上下文继续按 rerank 顺序组织，不按文档聚合，避免破坏相关性排序。
- `[K#]` 编号的唯一所有者是 `ContextAssemblyPipeline` 或等价 context assembly 层，不是 retriever。
- 编号必须在 token budget 裁剪后的最终 chunks 上生成；只有实际进入 `[Retrieved Context]` 的 chunks 才能进入最终 sources 数组，避免 context 中没有 `[K4]` 但前端展示 K4 source card 的错位 bug。
- context 中展示轻量来源头，sources 数组中保留与最终 context 一一对应的完整溯源字段。
- 生成 prompt 后续要求模型使用 `[K#]` 引用证据；这属于生成优化阶段继续收紧。
- sources 不是前端局部渲染问题，而是后端到前端的端到端数据通道；当前源码在 engine 边界只取 `knowledge_result.chunks`，会丢弃 sources，必须补齐透传、持久化和前端消费。

sources 端到端通道要求:

```text
retriever 统一 rerank 后对最终 top-N hydrate，产出 hydrated top-N chunks + retrieval_state
  -> KnowledgeResult 携带 hydrated top-N chunks 和 retrieval_state
  -> ConversationEngine._prepare() 把 hydrated chunks 交给 ContextAssemblyPipeline
  -> ContextAssemblyPipeline 按 token budget 裁剪最终 chunks，生成 [K#] 编号和最终 sources
  -> engine 把 context assembly 产出的最终 sources 和 retrieval_state 放入 StrategyContext
  -> L1 SSE 在答案完成前或 done 时发送 sources 事件
  -> assistant message 持久化 sources，历史重载后仍能点击引用
  -> 前端 chat stream 类型、ChatPanel state、Markdown 渲染、source card 侧栏消费 sources
```

实现边界:

- `query_knowledge_base()` 的消费方不只有 L1 engine，还包括 L2 `search_knowledge` 工具、`POST /rag/query` API、相关后端测试和新评测 runner；修改返回结构时必须同步适配这些调用方。
- 新增 SSE event type 可命名为 `sources`，或把 sources 挂到 terminal `done` payload；二者择一即可，必须保证前端未知事件向后兼容。
- `StrategyResult` / `StrategyContext` 或等价数据结构需要携带最终 `sources` 与轻量 `retrieval_state`。
- `retrieval_state` 最小字段: `retrieval_hit`、`empty_reason`、`planner_failed`、`fallback_used`；`empty_reason` 取值以评测文档 trace schema 的固定枚举为唯一权威，代码中在 trace schema 模块定义一次，线上与离线共用。
- `AssembledContext` 或 assemble 返回值需要新增最终 `sources` 字段，由 engine 读取放入 `StrategyContext`；`[K#]` 编号与 sources 终稿不在 retriever 内生成。
- 持久化采用 assistant message `content_blocks_json` 中新增 `{"type":"sources", ...}` block；该方案不需要新增数据库列，旧前端会跳过未知 block type，历史会话重新打开后可以恢复 citation/source card。

source hydrate:

- Milvus 返回候选后必须通过 Postgres hydrate:

```text
document_chunks -> id(chunk_id) / node_id / chunk text / chunk_index / page_start / page_end / metadata_json / text_hash / token_count
knowledge_documents -> document_title / category / source_kind / status / deleted_at / file_asset_id
file_assets -> original_filename / content_type / size_bytes
```

- hydrate 同时做 live check:

```text
knowledge_documents.deleted_at is null
knowledge_documents.status not in deleting/delete_failed
document_chunks.deleted_at is null
document_chunks.index_status != deleted
```

chunk 身份规则:

- Milvus row `id` 等于 `document_chunks.node_id`，hydrate join key 使用 `node_id`。
- API/source 返回中的 `chunk_id` 使用 `document_chunks.id`，同时返回 `node_id` 方便诊断和兼容旧链路。
- 评测和 bad case 若以最终优化后的 hydrated 结果为准，使用 `chunk_id=document_chunks.id`；如果直接检查 Milvus 命中，则使用 `node_id`。

上下文格式:

```text
[K1] title="Redis 面试题" page=3 chunk=12 score=0.873
Redis 缓存击穿是指热点 key 失效后，大量请求同时打到数据库...

[K2] title="缓存设计笔记" section="缓存异常场景" chunk=4 score=0.821
缓存穿透通常是查询不存在的数据...
```

source 返回结构:

```json
{
  "ref": "K1",
  "chunk_id": "...",
  "node_id": "...",
  "document_id": "...",
  "document_title": "...",
  "file_name": "...",
  "category": "...",
  "source_kind": "...",
  "page_start": 3,
  "page_end": 3,
  "section_title": "异常场景",
  "heading_path": ["缓存", "异常场景"],
  "chunk_index": 12,
  "score": 0.873,
  "score_source": "reranker",
  "text_preview": "Redis 缓存击穿是指..."
}
```

token 预算:

- 本轮继续使用 `RETRIEVED_CONTEXT_BUDGET=8000`。
- 优先按 chunk 整体加入，超过预算时停止追加后续 chunk。
- 如果单个 chunk 自身超过预算，截断该 chunk 并记录 `truncated=true`。
- context 预算是 LLM prompt 预算，继续使用现有 L1/L2 context tokenizer 估算；不要用建库阶段的 embedding tokenizer `token_count` 直接替代。
- 建库 `token_count` 只用于切分超长判定、embedding 输入保护和统计诊断，可作为预算预估参考但不能作为唯一裁剪依据。

## 3. 执行方向

本轮检索优化目标:

- 保持当前 Milvus hybrid + reranker 主架构。
- 优先修正 dense_query/sparse_query 未真正分路的问题。
- Metadata filter 本轮只保留用户隔离 pre-filter；`source_kind` 和 `category` 不进入普通问答检索过滤。
- 增大 rerank 前候选量，给 reranker 更大选择空间。
- 增加 hash/id 级保守去重。
- 增加 source hydrate 和可展示溯源字段。
- 删除旧的 `lexical_overlap` 计算、`[RAG Score: ... | Lexical Overlap: ...]` 文本拼接和 retriever 自拼 context 字符串，统一由 context assembly 使用 hydrated chunks/sources 生成 `[K#]` context。
- 不引入复杂 query expansion、多轮多 query 并发召回、语义去重、相邻 chunk 回填、parent chunk 回填。

旧逻辑清理:

- 删除 `_lexical_overlap` / `_query_terms` 及 `lexical_overlap` 输出字段。
- 删除 `[RAG Score: ... | Lexical Overlap: ...]` 文本拼接。
- 删除 retriever 返回值里的旧 `answer` / `context_text` 作为 RAG 上下文协议的使用；对 `/rag/query` API 如需保留兼容字段，应由新结构派生，不能继续作为内部主协议。
- 删除 `[SYSTEM_EMPTY_WARNING]` 哨兵协议，改为结构化 `retrieval_state.empty_reason` / `retrieval_hit`；`empty_reason` 取值使用评测文档 trace schema 的固定枚举。
- 删除 `query = sparse_query or dense_query` 合并行，改为 dense/sparse 双 query 透传。
- `_score_passes` 的“单一阈值、无放宽”注释必须随 reranker fallback 策略同步修改，避免代码注释与行为矛盾。
- `personal_memory` 检索后排除逻辑可在确认历史 chunks 已由迁移清理且 hydrate live check 覆盖后删除；删除时在 PR 中说明依赖条件。

## 4. 决策记录

| 日期 | 环节 | 决策 | 理由 | 状态 |
| --- | --- | --- | --- | --- |
| 2026-06-09 | Query 改写 | Query Planner prompt 正式重写，职责限定为检索路由、dense/sparse query 改写、多子问题拆分和 memory/material load 决策；不生成 metadata filter。 | Query 改写要解决指代不清、问题过短、表达不一、多子问题；metadata filter 交给业务显式参数和安全边界，避免 LLM 参与权限/分类判断。 | 已确认 |
| 2026-06-09 | Query 改写 | planner 失败时用原始问题 fallback 检索，并在内部 prompt/context 标记 planner 失败；最终用户答案不得提到 planner 失败。 | 检索结果还会经过融合、rerank 和生成阶段判断，直接放弃检索容易漏答；失败提示应只作为模型内部可靠性提醒，不暴露给用户。 | 已确认 |
| 2026-06-09 | Query 改写 | 只对明显多子问题拆分为 `sub_queries`；每个子问题单独召回，再合并去重并统一 rerank；单问题不拆；`MAX_SUB_QUERIES=4` 作为防御性硬上限。 | 多子问题拆分能提升覆盖率，但过度拆分会增加噪声和 token 成本；统一 rerank 可避免各子问题低质候选直接进入 context；硬上限用于控制 LLM 输出异常时的 fan-out。 | 已确认 |
| 2026-06-09 | Query 改写 | `dense_query` 使用完整自然语言语义查询；`sparse_query` 使用短关键词/实体/术语查询；两者分别进入向量检索和 BM25。 | dense 与 BM25 的最佳查询形态不同，当前只用一个 query 会浪费 planner 的改写结果。 | 已确认 |
| 2026-06-09 | Query 改写 | L2 agent 的 `search_knowledge` 不套额外 rewrite，由 agent 自己生成 query。 | Agent 本身已有推理能力，再套 planner 容易二次改坏查询；先保持链路简单。 | 已确认 |
| 2026-06-09 | Metadata 过滤 | 普通知识库检索 pre-filter 本轮只做 `user_id` 隔离；`source_kind` 是来源字段，`category` 是知识库管理 tag，二者不作为普通问答检索 filter；deleted/status/index_status 通过 Postgres hydrate 做 live check。 | 用户隔离是 P0 安全边界，必须在 Milvus 检索前过滤；其他字段不是当前检索范围控制需求，删除态等可变状态以 Postgres 事实源为准，避免在 Milvus 复制可变状态。 | 已确认 |
| 2026-06-09 | 多路召回 | 保持 Milvus hybrid search，两路召回为 dense vector + BM25 sparse；dense 使用 `dense_query`，BM25 使用 `sparse_query`；单问题 `FUSION_TOP_K=12`、`RERANK_TOP_N=5`；多子问题每个子问题 `SUB_QUERY_FUSION_TOP_K=6`，统一 rerank 后最终仍按 `RERANK_TOP_N=5` 截断。 | 当前架构已经覆盖向量语义和关键词召回，主要问题是未正确使用两类 query 且候选量偏小；多子问题分路召回能提升覆盖率，同时每个子问题较小 top_k 可控制噪声。 | 已确认 |
| 2026-06-09 | 结果融合 | 继续使用 Milvus RRF 做第一层融合，不在应用层重写融合算法；RRF 后统一进入 reranker 精排。 | Milvus 已原生支持 dense + sparse hybrid RRF，本轮不需要引入自定义融合复杂度。 | 已确认 |
| 2026-06-09 | Rerank 精排 | reranker 是系统级基础模型，由 `RERANKER_PROVIDER` / `RERANKER_MODEL` 配置，支持本地和远程 API provider；增大 rerank 前候选量；多子问题候选统一 rerank；remote fallback 要显式标记 `score_source=retriever_fallback`，且 fallback 分支不套用正常 `RAG_MIN_SCORE=0.5`。 | Rerank 是最终相关性闸门，候选量过小会限制效果；远程 fallback 的 RRF 分数和 reranker 分数标尺不同，直接套用同一阈值会导致 fallback 空召回。 | 已确认 |
| 2026-06-09 | 去重和补上下文 | 只做确定性去重: `id/node_id`、`text_hash`、规范化全文 exact hash；不做语义去重、不做相邻 chunk 回填、不做 parent chunk 回填。 | 确定性去重成本低且稳定；语义去重需要模型或额外相似度判断，回填相邻 chunk 容易污染 context。 | 已确认 |
| 2026-06-09 | 上下文组装 | 检索结果通过 Postgres hydrate 补齐来源字段并做 live check；context 按 rerank 顺序组织，只有 token budget 裁剪后实际进入 context 的 chunk 才分配 `[K#]` 引用编号；context 放轻量来源头，sources 数组保留与最终 context 一一对应的完整溯源字段；sources 必须从 context assembly 透传到 engine、SSE、持久化和前端 source card。 | 让最终回答可引用 `[K#]`，同时前端可以用 sources 挂载文档、页码、chunk 和预览；当前源码会在 engine 边界丢弃 sources，且提前编号会导致 sources 与最终 context 错位，必须补端到端通道。 | 已确认 |
| 2026-06-10 | 多路召回 | 检索参数面收敛为 `FUSION_TOP_K / SUB_QUERY_FUSION_TOP_K / MAX_SUB_QUERIES / RERANK_TOP_N` 四个；删除 `SUB_QUERY_RERANK_TOP_N` 和 `SUB_QUERY_CANDIDATE_QUOTA`。 | 每子问题候选量已由 `SUB_QUERY_FUSION_TOP_K` 限定，配额参数是空操作；无效配置面本身就是过度设计。 | 已确认 |
| 2026-06-10 | Rerank 精排 | `score_source` 枚举固定为 `reranker` / `retriever_fallback`；`planner_failed` 为代码运行时字段，不进 planner LLM 输出 schema。 | 枚举一处冻结避免多模块各自定义字符串；LLM 输出 `planner_failed` 会引入误报。 | 已确认 |
