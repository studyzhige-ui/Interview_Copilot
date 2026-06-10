# RAG 评测优化执行文档

> 状态: 已确认
> 范围: 只覆盖 RAG 评测闭环，即 Recall -> Precision -> Faithfulness -> Trace -> Bad Case。
> 用途: 本文沉淀当前源码基线、最终优化决策和可执行规格，作为后续交给 Claude/其他 Agent 执行的依据。

## 1. 当前源码基线

关键文件:

- `evaluation/eval_runner.py`: RAG evaluation CLI，支持 retrieval / generation / trajectory 三层评测。
- `evaluation/runners.py`: 三层评测的共享 runner。
- `evaluation/metrics.py`: retrieval 相关指标计算。
- `evaluation/golden_dataset.jsonl`: 当前 golden dataset。
- `evaluation/test_retrieval_quality.py`: pytest retrieval 阈值测试。
- `evaluation/test_generation_quality.py`: pytest generation 阈值测试。
- `evaluation/test_planner_routing.py`: pytest planner routing 阈值测试。
- `evaluation/report.py`: JSON / Markdown report 输出。
- `data/evaluation/reports/`: 历史评测报告。
- `backend/app/services/analytics/telemetry_service.py`: 线上交互 metrics JSONL。
- `backend/app/core/llm_tracing.py`: LangSmith LLM trace 接入。

当前优点:

- 已有独立 `evaluation/` 目录，不是从零开始。
- 已有 CLI: `python -m evaluation.eval_runner --layer retrieval --report`。
- 已有 pytest 阈值测试。
- 已有 golden dataset，规模约 835 rows。
- 已有 retrieval 指标: Hit@3、Precision@3、Recall@3、MRR@5、nDCG@5、latency、isolation violations。
- 已有 generation 评测设计: retrieve -> answer -> RAGAS faithfulness / context precision / context recall / factual correctness。
- 已有 trajectory/planner routing 评测设计。
- 已有历史报告，例如 `data/evaluation/reports/eval_2026-05-03_120340/retrieval_details.json`。
- 线上已有 metrics.jsonl 和 LangSmith trace。

当前主要问题:

- `evaluation/runners.py` 与当前生产接口存在漂移:
  - `query_knowledge_base()` 当前参数是 `source_kind`，runner 里仍传 `source_type`。
  - `knowledge_retriever.retrieve()` 当前参数是 `source_kind`，runner 里仍传 `source_type`。
  - `plan_query()` 当前参数是 `user_message`、`recent_turns`、`learning_strategy_description`、`global_memory_on`，runner 里仍使用旧参数 `session_state`、`knowledge_index_lines`、`strategy_description`、`habit_description`。
- `pytest.ini` 当前 `testpaths = backend/tests`，旧 `evaluation/` 测试不在默认 CI 采集范围；因此旧评测漂移不会默认炸 CI，但手动运行 `pytest evaluation/` 会失败。
- retrieval 评测现在用 `reference_answer` 与 chunk text 的 overlap 判断相关性，缺少人工标注的 expected chunk_id / document_id。
- generation 评测依赖 RAGAS/LLM，成本和稳定性需要控制。
- 现有 trace 主要靠 LangSmith 和 metrics JSONL，缺少检索域结构化 trace。
- Bad Case 还没有形成采集、分类、回流优化的闭环。

最终方向:

- 不在旧 `evaluation/` 上继续小修小补。
- 新建独立 RAG 评测目录，专门服务当前 RAG 架构。
- 旧 `evaluation/` 只作为历史参考和可迁移素材，不能作为本轮目标实现；应在 README 或 pytest 标记中明确冻结，避免手动误跑旧 runner。
- 新评测体系应贴合当前已确认的 RAG 流程:

```text
建库质量
  -> Query Planner
  -> Hybrid Retrieval
  -> Rerank
  -> Source Hydration / Citation
  -> Generation Faithfulness
  -> Bad Case 回流
```

最终目录:

```text
evaluation/rag/
  README.md
  datasets/
    retrieval_gold.jsonl
    generation_gold.jsonl
    planner_gold.jsonl
    bad_cases.jsonl
  runners/
    retrieval_eval.py
    planner_eval.py
    generation_eval.py
    citation_eval.py
    ingestion_eval.py
  metrics/
    retrieval_metrics.py
    generation_metrics.py
    citation_metrics.py
    trace_schema.py
  reports/
    report_writer.py
  cli.py
```

该目录与旧 `evaluation/` 代码隔离，旧代码只作为历史参考。

## 2. 五个环节执行规格

### 2.1 Recall

当前源码基线:

- retrieval runner 计算 `hit_at_3`、`recall_at_3`。
- 历史报告显示某次 retrieval: `hit_at_3=0.9988`、`recall_at_3=0.9988`。
- 当前相关性判断来自文本 overlap，不是人工 gold chunk。

最终优化内容:

- 使用强 chunk 标注作为 Recall 主依据:

```text
Gold Recall: hydrated top-k 中是否命中 expected_chunk_ids(document_chunks.id)
```

- 不使用 `expected_terms` 或历史 overlap 弱标注作为正式指标。
- 当 chunk id 因重建漂移时，使用 `expected_content` + `min_content_coverage >= 0.75` 作为兜底内容覆盖判断。
- 对新检索策略至少评估:

```text
Recall@3
Recall@5
Recall@10 或 Hit@10
MRR@5
```

已确认:

- 使用强 chunk 标注作为主评测依据。
- 数据集由 agent 基于本地真实 `document_chunks` 构建。
- 不使用 `expected_terms` 弱标注。
- 阈值不沿用旧评测硬编码；先用新体系跑出 baseline，再在配置中定义 quality gate。

### 2.2 Precision

当前源码基线:

- retrieval pytest 中 `MIN_PRECISION_AT_3 = 0.50`。
- runner 计算 `precision_at_3` 和 `ndcg_at_5`。
- precision 仍基于 overlap relevance。

最终优化内容:

- 保留 Precision@3 / nDCG@5。
- 增加 rerank 后最终 context precision。
- 多子问题检索后，需要分别评估:

```text
sub_query coverage
final context precision
```

已确认:

- Precision 按强 chunk 或内容覆盖判断 relevant。
- 多子问题通过 `query_type=multi_query` 单独聚合指标。
- 阈值先不沿用旧 `Precision@3 >= 0.50`，新体系跑 baseline 后再配置 quality gate。

### 2.3 Faithfulness

当前源码基线:

- generation runner 设计上使用 RAGAS:

```text
Faithfulness
ContextPrecisionWithReference
ContextRecall
FactualCorrectness
```

- 当前生成优化决定不做线上 LLM 二次审核。
- 评测离线使用 LLM/RAGAS 是可以接受的，但要控制成本和频率。

最终优化内容:

- 修复 generation runner 与当前检索接口的漂移。
- 加入引用评测:

```text
citation_validity_rate: 答案中的 [K#] 是否都存在
citation_coverage_rate: 有检索证据的答案是否至少包含一个引用
ragas_faithfulness: 高成本离线指标，用于判断答案是否被 context 支持
```

已确认:

- RAGAS 纳入最终指标体系。
- generation 采用端到端真实链路，不使用固定 context。
- RAGAS 由 CLI 参数控制；日常可跳过，高成本完整评测可手动或定时运行。
- 阈值先不固定，跑出 baseline 后再配置 quality gate。

### 2.4 Trace

当前源码基线:

- LangSmith 捕获 LLM 调用。
- `metrics.jsonl` 记录 session/user/latency/tokens/retrieval_attempted/retrieval_hit/stop_reason。
- 检索日志有 top candidates，但不是结构化 trace。

需要优化:

- 增加 RAG 检索域结构化 trace，不替代 LangSmith，只补 LangSmith 不容易聚合的检索字段。
- 每次 RAG turn 至少记录:

```text
trace_id
session_id
user_id
original_query
planner_failed
needs_knowledge_retrieval
dense_query
sparse_query
sub_queries
retrieval_top_k
candidate_count_before_dedup
candidate_count_after_dedup
rerank_top_n
valid_chunk_count
empty_reason
source_refs
latency_by_stage
```

`empty_reason` 固定枚举，在 trace schema 模块定义一次，线上与离线共用（`retrieval_state.empty_reason` 使用同一枚举）:

```text
planner_no_retrieval
no_candidates
all_below_threshold
all_filtered_live_check
milvus_unavailable
principal_unresolved
```

- Trace 存储本轮采用单一路径，避免 metrics 双写重复: 线上采样 trace 优先扩展现有 metrics JSONL；离线评测 detail 写入 `data/evaluation/rag/reports/<timestamp>/*_details.jsonl`。如后续确需 `rag_trace.jsonl`，必须先定义与 metrics JSONL 的边界。

已确认:

- 离线评测必须全量输出结构化 trace。
- 线上生产 trace 可采样或按 debug 开关控制，默认不要把 `original_query/dense_query/sparse_query` 原文无条件写入长期日志。
- 如果线上 trace 记录用户原文 query，必须有明确配置开关、采样率和脱敏/保留周期策略；评测环境可全量记录，生产环境默认最小化。
- trace id 必须写入评测 detail 和 bad case，方便回查。
- per-turn 标识统一命名为 `trace_id`，不再使用 `request_id` 别名；线上由 `ConversationEngine` 每个 turn 生成一次（uuid）并写入 metrics JSONL，离线 runner 对每个样本自行生成，二者字段名一致以便关联。

### 2.5 Bad Case

当前源码基线:

- 没有专门 bad case 采集表或文件。
- 历史报告可以人工查看，但没有闭环分类。

需要优化:

- 建立 bad case JSONL 闭环，字段 schema 和 `failure_type` 枚举以本文 `3.1 Dataset 设计 / Bad Cases` 为唯一权威。

- bad case 可来源于:

```text
人工反馈
评测失败样本
线上 warning: no citation / invalid citation / retrieval_hit=false
consistency scan 异常
```

- Bad case 进入 golden dataset 前需要人工确认，避免把错误期望固化。

已确认:

- Bad case 存 JSONL，不进数据库。
- failure_type 使用 `3.1 Bad Cases` 中的固定枚举，后续如确实不够再扩展。

## 3. 新 RAG 评测体系设计

已确认:

- 新目录固定为 `evaluation/rag/`。
- 评测数据资产不进业务数据库，只使用 JSONL、fixture 文档和报告文件；runner 可以在测试数据库中临时创建 eval 用户并导入 fixture 文档。
- 数据集构建由 agent 完成，必要时人工复核。
- 评测语料必须使用专用 eval 用户和固定 fixture 文档集，不绑定开发者本机已有私人知识库数据。
- 评测流程应先导入 fixture 文档并生成稳定评测环境，再构建或校验 retrieval/generation gold；`expected_content + min_content_coverage` 是 chunk id 漂移兜底，不是替代固定语料的主路径。
- fixture 文档重导入后，`document_chunks.id/node_id` 必然整体更换，必须运行 gold 重绑步骤: 按 `expected_content` 锚定重新解析当前 `chunk_id/node_id` 并回写数据集；content coverage 只作为单次运行内的漂移兜底，不允许长期带着失效 chunk id 跑评测。
- 不做知识主题 tag，例如 Redis、Java、系统设计等；只用 `query_type` 区分 `single_query` / `multi_query`。
- 数据集文件先固定为 4 个: `planner_gold.jsonl`、`retrieval_gold.jsonl`、`generation_gold.jsonl`、`bad_cases.jsonl`。
- 每条样本只使用 `query_type=single_query|multi_query`，不引入知识主题 tag。
- 所有主流指标最终都纳入体系，包括 RAGAS；运行时通过 CLI 决定是否执行某类 runner 或某些高成本指标。
- 不区分“一阶段/二阶段”作为目标边界，只区分实现顺序和测试运行顺序。

### 3.1 Dataset 设计

新评测数据集分层，而不是所有样本混在一个 `golden_dataset.jsonl` 里。

#### Retrieval Gold

用于 Recall / Precision / Rerank 评估:

```json
{
  "id": "ret_001",
  "query": "Redis 缓存雪崩怎么解决？",
  "user_id": "eval_user",
  "expected_chunk_ids": ["chunk_..."],
  "expected_node_ids": ["node_..."],
  "expected_content": "缓存雪崩可以通过过期时间随机化、限流、降级、多级缓存缓解。",
  "min_content_coverage": 0.75,
  "query_type": "single_query",
  "notes": ""
}
```

规则:

- 优先使用 `expected_chunk_ids` 做强评测。
- 不使用 `expected_terms` 做弱标注。
- 当 chunk id 因重建发生变化时，可用 `expected_content` + `min_content_coverage >= 0.75` 做内容覆盖评测。
- 构建数据集的 agent 需要能访问本地项目、数据库和 `document_chunks`，基于真实 chunk 生成 gold 数据。
- `expected_chunk_ids` 统一指优化后 hydrated result 中的 `chunk_id = document_chunks.id`。如果某个 runner 直接检查 Milvus 原始命中，需要额外使用 `expected_node_ids`，不能把 `node_id` 和 `chunk_id` 混用。
- gold 数据必须来自专用 eval 用户导入的 fixture 文档。不要从开发者私人知识库直接抽取 gold，否则 `user_id`、租户过滤、chunk id 和文档内容在不同机器上都会漂移。

字段要求:

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `id` | 是 | 样本稳定 id。 |
| `query` | 是 | 用户问题。 |
| `user_id` | 是 | 评测用户。 |
| `query_type` | 是 | 只能是 `single_query` 或 `multi_query`。 |
| `expected_chunk_ids` | 是 | 正确 chunk id 列表，至少 1 个。 |
| `expected_node_ids` | 否 | Milvus 原始 row id，对应 `document_chunks.node_id`；只在直接验证 Milvus 命中时使用。 |
| `expected_content` | 是 | 正确答案/正确 chunk 的核心内容，用于 chunk id 漂移后的覆盖度评估。 |
| `min_content_coverage` | 是 | 默认 0.75。 |
| `notes` | 否 | 标注说明。 |

#### Planner Gold

用于 Query Planner 行为评估:

```json
{
  "id": "plan_001",
  "user_message": "那雪崩和击穿分别怎么处理？",
  "recent_turns": [
    {"role": "User", "content": "Redis 缓存异常有哪些？"},
    {"role": "Agent", "content": "常见有穿透、击穿、雪崩。"}
  ],
  "expected_needs_retrieval": true,
  "expected_dense_contains": ["Redis", "缓存雪崩", "缓存击穿"],
  "expected_sparse_terms": ["Redis", "缓存雪崩", "缓存击穿"],
  "expected_sub_query_count": 2,
  "query_type": "multi_query"
}
```

字段要求:

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `id` | 是 | 样本稳定 id。 |
| `user_message` | 是 | 当前用户问题。 |
| `recent_turns` | 是 | 最近对话，允许空数组。 |
| `query_type` | 是 | `single_query` 或 `multi_query`。 |
| `expected_needs_retrieval` | 是 | 是否应触发知识库检索。 |
| `expected_dense_contains` | 是 | dense query 应包含的必要词组。 |
| `expected_sparse_terms` | 是 | sparse query 应包含的关键词/实体。 |
| `expected_sub_query_count` | 是 | 期望子问题数；单问题为 0。 |

#### Generation Gold

用于端到端 RAG 生成评估:

```json
{
  "id": "gen_001",
  "query": "根据我的资料，Redis 缓存雪崩有哪些解决方案？",
  "query_type": "single_query",
  "expected_chunk_ids": ["chunk_..."],
  "expected_node_ids": ["node_..."],
  "expected_content": "缓存雪崩可以通过过期时间随机化、限流、降级、多级缓存缓解。",
  "min_content_coverage": 0.75,
  "reference_answer_points": [
    "过期时间随机化",
    "限流或降级",
    "多级缓存"
  ],
  "expected_citation_required": true,
  "expected_refusal": false,
  "notes": ""
}
```

规则:

- `generation_gold` 采用端到端模式，不使用固定 contexts。
- runner 必须真实执行:

```text
query
  -> Query Planner
  -> Retrieval
  -> Rerank
  -> Context Assembly
  -> L1 RAG Generation
  -> Citation / Faithfulness / Latency Evaluation
```

- 端到端评测用于同时衡量检索、上下文、生成、引用和延迟。
- 不设计固定 context generation 模式；固定 context 只适合 prompt/引用设施局部调试，不作为正式评测主线。

字段要求:

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `id` | 是 | 样本稳定 id。 |
| `query` | 是 | 用户问题。 |
| `query_type` | 是 | `single_query` 或 `multi_query`。 |
| `expected_chunk_ids` | 是 | 期望端到端链路召回并引用的 chunk。 |
| `expected_node_ids` | 否 | Milvus 原始 row id，对应 `document_chunks.node_id`；仅用于底层检索诊断。 |
| `expected_content` | 是 | 核心证据内容。 |
| `min_content_coverage` | 是 | 默认 0.75。 |
| `reference_answer_points` | 是 | 答案应覆盖的要点列表。 |
| `expected_citation_required` | 是 | 是否要求引用 `[K#]`。 |
| `expected_refusal` | 是 | 是否期望答案说明资料证据不足；普通可回答样本为 `false`。 |
| `notes` | 否 | 标注说明。 |

#### Bad Cases

用于回归:

```json
{
  "id": "bad_001",
  "query": "...",
  "failure_type": "missed_recall",
  "actual_trace_id": "...",
  "expected_behavior": "...",
  "notes": "...",
  "status": "open"
}
```

字段要求:

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `id` | 是 | bad case 稳定 id。 |
| `query` | 是 | 触发失败的问题。 |
| `query_type` | 是 | `single_query` 或 `multi_query`。 |
| `failure_type` | 是 | 固定枚举，见下方。 |
| `actual_trace_id` | 否 | 关联评测或线上 trace。 |
| `expected_behavior` | 是 | 期望系统表现。 |
| `actual_behavior` | 否 | 实际错误表现。 |
| `status` | 是 | `open` / `fixed` / `ignored`。 |
| `notes` | 否 | 备注。 |

`failure_type` 固定枚举:

```text
bad_rewrite
missed_recall
low_precision
bad_rerank
citation_error
hallucination
refusal_error
stale_index
latency_regression
```

### 3.2 Runner 设计

新 runner 要分层运行:

```text
planner_eval
  -> 只测 Query Planner 输出结构和改写质量

retrieval_eval
  -> 使用 planner 或固定 query
  -> 测 dense/sparse 分路、RRF、rerank、去重后的结果

citation_eval
  -> 给定 final answer + sources
  -> 正则校验 [K#] 合法性和覆盖率

generation_eval
  -> 端到端执行 Query Planner -> Retrieval -> Rerank -> Context Assembly -> L1 RAG Generation
  -> 评估 faithfulness / factual correctness / citation / latency

ingestion_eval
  -> 用小型固定文档集
  -> 测解析、切分、metadata、索引一致性
```

Runner 输入输出契约:

- 所有 runner 读取 `evaluation/rag/datasets/*.jsonl`。
- 所有 runner 输出 detail JSONL 和 summary JSON。
- 所有 detail 行必须包含 `sample_id`、`query_type`、`status`、`trace_id`、`latency_ms`。
- 所有 runner 支持 `--limit`、`--sample`、`--seed`。
- 高成本指标通过 CLI flag 开关，例如 `--with-ragas`。
- `citation_eval` 默认消费 `generation_eval` 输出的 detail JSONL 中的 `final_answer + sources`，不再单独维护一份 citation 专用数据集。

### 3.3 Metrics 设计

#### 3.3.1 Retrieval Metrics

K 值固定:

```text
K = 1, 3, 5
```

相关性判定:

```text
relevant(chunk) = chunk.id in expected_chunk_ids
               OR content_coverage(chunk.text, expected_content) >= min_content_coverage
```

其中 `chunk.id` 必须是 hydrated 后的 `document_chunks.id`；如果 runner 在 hydrate 前计算底层召回，应使用 `node_id in expected_node_ids` 单独输出诊断字段，不参与默认强 chunk 指标。

`content_coverage` 定义:

```text
content_coverage = LCS_token_overlap(expected_content, chunk_text) / token_count(expected_content)
```

其中 token 使用评测模块固定 tokenizer；不要和生产切分/embedding 的 tokenizer 强绑定。如果实现 LCS 成本过高，可以先用 normalized character 3-gram recall，但函数名和输出字段仍叫 `content_coverage`。

必输出指标:

```text
hit_at_1 / hit_at_3 / hit_at_5
recall_at_1 / recall_at_3 / recall_at_5
precision_at_1 / precision_at_3 / precision_at_5
mrr_at_5
ndcg_at_5
gold_chunk_best_rank
gold_chunk_found
candidate_count_before_dedup
candidate_count_after_dedup
rerank_input_count
rerank_output_count
latency_ms.total
latency_ms.embedding
latency_ms.milvus
latency_ms.rerank
latency_ms.hydrate
```

定义:

- `hit_at_k`: top-k 中是否至少有 1 个 relevant chunk。
- `recall_at_k`: top-k relevant chunk 数 / gold relevant chunk 数。
- `precision_at_k`: top-k relevant chunk 数 / k。
- `mrr_at_5`: 第一个 relevant chunk 在 top-5 的倒数排名；没有则 0。
- `ndcg_at_5`: 使用 relevance score，强 chunk 命中记 1，content coverage 命中按 coverage 记分。
- `gold_chunk_best_rank`: 第一个 gold chunk 的 1-based rank，没有则 null。
- `rerank_survival_rate`: rerank output 中 relevant chunk 数 / rerank input 中 relevant chunk 数；分母为 0 时 null。

分组:

- overall。
- `query_type=single_query`。
- `query_type=multi_query`。

#### 3.3.2 Planner Metrics

必输出指标:

```text
needs_retrieval_accuracy
dense_query_contains_required_terms
sparse_query_contains_required_terms
sub_query_count_exact_rate
sub_query_count_tolerant_rate
planner_failure_rate
fallback_rate
```

定义:

- `needs_retrieval_accuracy`: `plan.needs_knowledge_retrieval == expected_needs_retrieval` 的比例。
- `dense_query_contains_required_terms`: `expected_dense_contains` 全部出现在 `dense_query` 或任一 `sub_queries[].dense_query` 的比例。
- `sparse_query_contains_required_terms`: `expected_sparse_terms` 全部出现在 `sparse_query` 或任一 `sub_queries[].sparse_query` 的比例。
- `sub_query_count_exact_rate`: `len(sub_queries) == expected_sub_query_count` 的比例。
- `sub_query_count_tolerant_rate`: `abs(len(sub_queries) - expected_sub_query_count) <= 1` 的比例。
- `planner_failure_rate`: planner 调用异常或返回不可解析 JSON 的比例。
- `fallback_rate`: 使用 fallback plan 的比例。

#### 3.3.3 Generation Metrics

Generation runner 是端到端链路，必须真实执行检索和生成。

必输出低成本指标:

```text
answer_completeness
refusal_correctness
end_to_end_latency
retrieval_latency
ttfb
retrieval_hit_rate
answer_non_empty_rate
reference_point_coverage_rate
```

定义:

- `answer_completeness`: `reference_answer_points` 被答案覆盖的比例。
- `reference_point_coverage_rate`: 所有样本的 answer_completeness 平均值。
- `refusal_correctness`: 对 `expected_refusal=true` 样本，答案是否说明证据不足；无 refusal 样本时 null。
- `retrieval_hit_rate`: 端到端生成中检索命中的比例。
- `answer_non_empty_rate`: 非空答案比例。
- `end_to_end_latency`: 从 runner 开始处理样本到答案完成。
- `retrieval_latency`: planner/retrieval/rerank/hydrate 的合计或检索模块上报值。
- `ttfb`: 从样本开始到首 token 返回。

高成本 RAGAS 指标，通过 `--with-ragas` 启用:

```text
ragas_faithfulness
ragas_context_precision_with_reference
ragas_context_recall
ragas_factual_correctness
ragas_unsupported_claim_rate
```

说明: `ragas_unsupported_claim_rate` 只在 `--with-ragas` 或人工抽检报告中输出，不作为默认低成本必跑指标。

#### 3.3.4 Citation Metrics

必输出指标:

```text
citation_validity_rate
citation_coverage_rate
missing_citation_rate
invalid_citation_count
source_card_resolve_rate
```

定义:

- `citation_validity_rate`: 答案中出现的 `[K#]` 均存在于 sources 的样本比例。
- `citation_coverage_rate`: `expected_citation_required=true` 且答案至少出现一个合法 `[K#]` 的样本比例。
- `missing_citation_rate`: 需要引用但答案没有合法引用的样本比例。
- `invalid_citation_count`: 所有样本中非法 `[K#]` 总数。
- `source_card_resolve_rate`: sources 中每个 ref 都能解析到 document/chunk/source card 的比例。

#### 3.3.5 Ingestion Metrics

使用小型固定文档集评估建库质量。

必输出指标:

```text
parse_success_rate
fallback_used_rate
ocr_used_rate
empty_text_rate
chunk_count
chunk_token_p50
chunk_token_p95
metadata_completeness_rate
index_success_rate
consistency_missing_in_milvus
consistency_stale_in_milvus
```

#### 3.3.6 Trace Metrics

Trace metrics 来自离线 runner detail 和线上采样 trace。

```text
retrieval_attempted
retrieval_hit
empty_reason
planner_failed
reranker_fallback_rate
invalid_citation_warning_rate
latency_p50/p95
```

要求:

- 离线评测 detail 全量记录 trace。
- 线上 trace 可采样，优先扩展现有 metrics JSONL，字段名必须与离线一致。
- `trace_id` 必须能关联 bad case。

### 3.4 Report 设计

每次评测输出:

```text
data/evaluation/rag/reports/<timestamp>/
  report.json
  report.md
  retrieval_details.jsonl
  planner_details.jsonl
  generation_details.jsonl
  citation_details.jsonl
  failed_cases.jsonl
```

报告必须包含:

- 总体指标。
- 按 `query_type` 分组指标: `single_query` / `multi_query`。
- 失败样本列表。
- 与上一次 baseline 的差异。
- 可直接追加到 bad_cases.jsonl 的失败样本。
- 报告目录属于运行产物，必须加入 `.gitignore` 或沿用既有 data/evaluation 报告忽略策略。

CLI 契约:

```text
python -m evaluation.rag.cli --runner planner
python -m evaluation.rag.cli --runner retrieval
python -m evaluation.rag.cli --runner generation
python -m evaluation.rag.cli --runner citation
python -m evaluation.rag.cli --runner ingestion
python -m evaluation.rag.cli --all
python -m evaluation.rag.cli --rebind-gold

通用参数:
  --limit N
  --sample N
  --seed N
  --with-ragas
  --report
  --baseline <report_dir>
```

`--rebind-gold` 在 fixture 重导入后运行: 按 `expected_content` 重新解析并回写 `expected_chunk_ids` / `expected_node_ids`，恢复强 chunk 标注。

## 4. 执行顺序

新建体系，不修补旧 runner:

1. 新建 `evaluation/rag/`。
2. 定义 dataset schema 和 trace schema。
3. 实现 planner_eval、retrieval_eval、citation_eval、generation_eval、ingestion_eval 和 bad case 回流。
4. 所有主流指标都纳入体系；实际运行时通过 CLI 参数决定跑哪些 runner、哪些指标。
5. 数据集由 agent 构建，人工或 agent-assisted 标注 gold chunks / reference points。
6. 评测数据和 bad cases 不进数据库，保留在 JSONL/报告文件中。
7. 旧 `evaluation/` 作为历史代码保留，明确冻结或标记 skip；后续确认无用后再清理。

## 5. 决策记录

| 日期 | 环节 | 决策 | 理由 | 状态 |
| --- | --- | --- | --- | --- |
| 2026-06-09 | 总体架构 | 不在旧 `evaluation/` 上继续修补；新建独立 RAG 评测目录，按 planner/retrieval/citation/generation/ingestion 分层设计；旧 evaluation 明确冻结或 skip。 | 旧评测代码与当前生产接口已有漂移，虽然不在默认 `pytest.ini` 的 `backend/tests` 采集范围，但手动运行会失败；重建更贴合当前主流 RAG 评测方案，也便于 Bad Case 回流。 | 已确认 |
| 2026-06-09 | 目录 | 新 RAG 评测目录固定为 `evaluation/rag/`，与旧 evaluation 代码隔离。 | 评测代码仍属于 evaluation 域，但新旧体系需要边界清楚，避免继续受旧 runner 漂移影响。 | 已确认 |
| 2026-06-09 | 数据集 | 数据集由 agent 构建；评测数据和 bad cases 使用 JSONL/报告文件，不进数据库。 | 评测是测试资产，不是业务数据；JSONL 方便 review、版本管理和回归。 | 已确认 |
| 2026-06-09 | 分组 | 不做知识主题 tag，只保留 `query_type=single_query/multi_query` 分组。 | 知识主题标注成本高且文档类型不统一；当前最需要验证的是单问题和多子问题基础能力。 | 已确认 |
| 2026-06-09 | 数据集 | 新 RAG 评测数据集先固定为 `planner_gold.jsonl`、`retrieval_gold.jsonl`、`generation_gold.jsonl`、`bad_cases.jsonl` 四个文件。 | 四类数据足以覆盖 planner、retrieval、端到端 generation/citation 和 bad case 回归，避免一开始拆得过碎。 | 已确认 |
| 2026-06-09 | Retrieval Gold | retrieval gold 使用强 chunk 标注: `expected_chunk_ids=document_chunks.id`；可选 `expected_node_ids=document_chunks.node_id` 仅用于底层 Milvus 诊断；不使用 `expected_terms` 弱标注。chunk id 变化时可用 `expected_content` + `min_content_coverage >= 0.75` 做内容覆盖评测。 | RAG 检索评测需要明确正确 chunk 是否被召回；chunk_id/node_id 混用会导致 hydrate 和评测对不上；内容覆盖用于应对 chunk 重建导致 id 漂移。 | 已确认 |
| 2026-06-09 | Generation Gold | generation gold 采用端到端真实链路，不使用固定 contexts。 | 生成质量依赖 planner/retrieval/rerank/context/source/citation 全链路；端到端评测才能同时覆盖质量和延迟。固定 context 只适合 prompt 局部调试，不作为正式主线。 | 已确认 |
| 2026-06-09 | 指标 | 所有主流指标最终纳入，包括 RAGAS；实际运行时通过 CLI 选择 runner 和高成本指标。 | 评测体系要完整，但日常测试可按成本和速度选择运行范围。 | 已确认 |
| 2026-06-10 | Trace | per-turn 标识统一命名 `trace_id`（弃用 `request_id`），由 ConversationEngine 每 turn 生成 uuid；`empty_reason` 固定枚举在 trace schema 一处定义，线上离线共用。 | 同一概念两个名字会让 metrics 与评测 detail 无法关联；枚举多处定义必然漂移。 | 已确认 |
| 2026-06-10 | 数据集 | fixture 重导入后必须运行 `--rebind-gold`，按 `expected_content` 重新解析当前 chunk id 并回写数据集。 | replacement 重导入必然更换全部 chunk id；不重绑会让强 chunk 评测长期退化为内容覆盖弱评测。 | 已确认 |
