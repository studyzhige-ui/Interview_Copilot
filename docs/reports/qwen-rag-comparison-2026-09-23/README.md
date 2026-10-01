# BGE / Qwen 本地检索对照（2026-09-23）

结论：当前瓶颈主要是重排模型，不是已经证实的 PostgreSQL/Milvus 差异。Qwen 组合在本轮提高最终召回、降低检索耗时，但原始重排和证据精度下降，没有通过现有全部发布质量门槛。

## 实验设计

- 同一 RTX 5060 Ti 16GB、隔离 PostgreSQL 15.18 + pgvector 0.8.6，单请求依次执行；没有调用 Milvus，因此不能报告二者的直接性能差值。
- BGE：BAAI/bge-m3 + BAAI/bge-reranker-v2-m3。Qwen：用户本机 D:/Models/Qwen 下 Qwen3-Embedding-0.6B + Qwen3-Reranker-0.6B，均为 1024 维 embedding。
- 对照使用同一 133 条 calibration（115 可答、18 不可答）、同一规划器快照、每意图 20 候选、最终最多 3 个片段。未新生成题目、未使用 288 条 held-out 检索题调参、未重新付费调用 planner。
- 主对照冻结原分块：1588 条索引输入（包含租户隔离 canary）在 BGE 和两个 Qwen generation 中逐行一致、SHA-256 一致；只重算向量、更换重排器。见 [输入验证](qwen-frozen-input-verification.json)。
- Qwen 按官方协议：query-only instruction、归一化 embedding；重排使用 causal LM 的 yes/no 概率，不加载随机分类头。CUDA 用 BF16 + SDPA；BGE 保留默认精度与原适配器。因此速度是当前运行配置比较，不能全部归因于模型结构。
- 主表 Qwen 重排上限 1024，BGE 保留 512。补测证实 512 与 1024 下 Qwen 的主要质量指标相同。Qwen 全部输入长度保守上界为 687 tokens，1024 足以覆盖；不能把主要质量差异归因于 512 截断。见 [输入长度](qwen-token-bound.json)。
- 查询 planner 不计入检索耗时；上一轮 planner 平均约 1.01 秒、p95 约 1.29 秒，实际用户端还要加上规划、答案生成、网络等时间。不能把两阶段 p95 直接相加当作整体 p95。
- 使用同一隔离 Python 环境重跑 BGE 与 Qwen：torch 2.8.0+cu129、transformers 4.57.6、sentence-transformers 5.7.0；其余版本见各 JSON。没有修改原 Conda 环境和部署默认模型。

## 冻结输入的主结果

| 指标 | BGE | Qwen（1024 上限） |
| --- | ---: | ---: |
| 候选金标准证据命中 | 99.13% | 100.00% |
| 原始重排 Top-1 命中 | 82.61% | 73.91% |
| 原始重排 Top-3 命中 | 95.65% | 93.04% |
| 最终 Top-3 命中 | 88.70% | 93.04% |
| 证据组召回 | 87.97% | 92.32% |
| 查询 precision | 91.07% | 93.04% |
| 证据 precision | 64.20% | 35.60% |
| 平均检索耗时 | 736.94ms | 633.64ms |
| p95 检索耗时 | 1319.47ms | 1080.32ms |

最终选择使用原部署阈值 0.87 / margin 0.01。这组阈值不能视为对两个模型同样合适；另外执行了既有独立 calibration 搜索，BGE 与 Qwen 都没有满足全部约束的阈值组合。没有降低门槛、修改金标或将失败报告变成发布通过。

BGE 最终返回 162 个片段，其中 104 个匹配金标；Qwen 返回 309 个，其中 110 个匹配金标。Qwen 多保留的片段提升了命中率，也引入更多非金标证据。其原始 Top-1/Top-3 更低，所以不能将更高最终命中解释为重排能力整体更好。

## 延迟分解（平均毫秒）

| 阶段 | BGE | Qwen（1024） |
| --- | ---: | ---: |
| 解析请求身份 | 2.16 | 2.15 |
| query embedding + 并行 BM25/向量召回 | 88.96 | 152.27 |
| 重排 | 640.46 | 473.73 |
| 权威内容回填 | 5.10 | 5.23 |
| 检索链路合计 | 736.94 | 633.64 |

BGE 平均重排 640.46ms，占平均总耗时约 87%。单个 dense SQL 调用 p95 44.05ms，sparse/BM25 调用 p95 113.79ms；这些包括连接获取、网络、Python 处理等，并不是纯数据库 EXPLAIN 时间。通道并行，不能把其分位数相加。

这里只做了暖机后的单轮校准测量，不是高并发容量测试，也没有多轮统计置信区间。Qwen 512/1024 的耗时差包含运行波动，不能据此声称更长输入一定更快。

## 这些指标究竟是什么意思

| 指标 | 项目内实际计算口径 | 上轮 BGE 的直观解释 |
| --- | --- | --- |
| 候选金标命中 | 可答题中，候选集至少包含一个匹配金标准证据的片段的题目比例 | 114 / 115 = 99.13% |
| 原始重排 Top-3 命中 | 应用最低分和分差筛选之前，前三至少有一个金标片段的题目比例 | 110 / 115 = 95.65% |
| 最终 Top-3 命中 | 筛选后最多三个片段中至少命中一个金标的题目比例 | 102 / 115 = 88.70% |
| 查询 precision | 所有返回了片段的问题中，至少命中一个金标的问题比例；有返回但不含金标也算错 | 102 / 112 = 91.07% |
| evidence-group recall | 每道可答题“覆盖的必需证据组 / 总证据组”的平均值；不等于全局事实数比例 | 87.97%；需要三个事实只找到两个，该题计 2/3 |
| evidence precision | 全部返回片段中，匹配金标的片段数比例 | 104 / 162 = 64.20% |

这些是证据检索指标，**不是最终 LLM 回答正确率**。金标以原文短语的 AND/OR 组映射到当前 chunk；并非所有语义等价表述都一定被标注，因此低 precision 表示非金标片段比例高，不能把所有这类片段直接称为事实错误。

18 个不可答校准题两套模型均未返回证据。样本量很小，不能外推生产“零误召回”。

## 语料与题目来源

语料是公开官方文档，清单固定 URL、许可证及 SHA-256：[corpus_manifest.json](../../../evaluation/corpus_manifest.json)。题目与参考证据则是项目自建评测集：[rag_dataset.jsonl](../../../evaluation/rag_dataset.jsonl)，不是公开标准 benchmark，也不是本轮新生成。仓库说明记载由独立 agent 构建；457 条中 361 条 ID 以 generated- 开头，包含问答/检索、困难负例及路由/轨迹样本。本轮使用其中 133 条校准题，脚本校验原文证据和 split 隔离不等同于全量人工复核。

25 份文档：

- [python-3.12-asyncio-task.html](https://docs.python.org/3.12/library/asyncio-task.html)
- [postgresql-17-transaction-isolation.html](https://www.postgresql.org/docs/17/transaction-iso.html)
- [rfc9110-http-semantics.pdf](https://www.rfc-editor.org/rfc/rfc9110.pdf)
- [rfc9457-problem-details.pdf](https://www.rfc-editor.org/rfc/rfc9457.pdf)
- [kubernetes-1.32-deployment.md](https://raw.githubusercontent.com/kubernetes/website/release-1.32/content/en/docs/concepts/workloads/controllers/deployment.md)
- [redis-client-side-caching.md](https://raw.githubusercontent.com/redis/docs/main/content/develop/clients/client-side-caching.md)
- [docker-storage.md](https://docs.docker.com/engine/storage.md)
- [python-3.12-typing.html](https://docs.python.org/3.12/library/typing.html)
- [python-3.12-dataclasses.html](https://docs.python.org/3.12/library/dataclasses.html)
- [postgresql-17-index-types.html](https://www.postgresql.org/docs/17/indexes-types.html)
- [postgresql-17-using-explain.html](https://www.postgresql.org/docs/17/using-explain.html)
- [rfc6749-oauth2.txt](https://www.rfc-editor.org/rfc/rfc6749.txt)
- [kubernetes-1.32-probes.md](https://raw.githubusercontent.com/kubernetes/website/release-1.32/content/en/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes.md)
- [kubernetes-1.32-configmap.md](https://raw.githubusercontent.com/kubernetes/website/release-1.32/content/en/docs/concepts/configuration/configmap.md)
- [docker-network.md](https://docs.docker.com/engine/network.md)
- [docker-build-cache.md](https://docs.docker.com/build/cache.md)
- [typescript-generics.md](https://raw.githubusercontent.com/microsoft/TypeScript-Website/v2/packages/documentation/copy/en/handbook-v2/Type%20Manipulation/Generics.md)
- [typescript-narrowing.md](https://raw.githubusercontent.com/microsoft/TypeScript-Website/v2/packages/documentation/copy/en/handbook-v2/Narrowing.md)
- [react-preserving-state.md](https://raw.githubusercontent.com/reactjs/react.dev/main/src/content/learn/preserving-and-resetting-state.md)
- [react-effects.md](https://raw.githubusercontent.com/reactjs/react.dev/main/src/content/learn/synchronizing-with-effects.md)
- [fastapi-async.md](https://raw.githubusercontent.com/fastapi/fastapi/master/docs/en/docs/async.md)
- [sqlalchemy-2-session-transactions.html](https://docs.sqlalchemy.org/en/20/orm/session_transaction.html)
- [git-rebase.html](https://git-scm.com/docs/git-rebase)
- [celery-tasks.html](https://docs.celeryq.dev/en/stable/userguide/tasks.html)
- [node-event-loop.html](https://nodejs.org/en/learn/asynchronous-work/event-loop-timers-and-nexttick)

## 辅助实验与可复现材料

- [BGE 同环境基线](bge.json)。
- [Qwen 冻结原分块 / 512](qwen-frozen-512.json)：最终命中 93.04%、证据 precision 35.60%、p95 1148.91ms。
- [Qwen 冻结原分块 / 1024](qwen-frozen-1024.json)：主对照，完整输入。
- [Qwen 重新解析 / 512](qwen-reparsed-512.json)：最终命中 95.65%、证据 precision 37.12%、p95 1191.05ms。tokenizer 改变分块，并且 PDF 解析路径变化，不能用于单独归因模型效果。

重新解析时，rfc9110 的 Docling 出现内存分配失败并整份回退 PyMuPDF；旧 BGE 运行中两个 PDF 都因旧 transformers 不支持解析模型而回退。本轮 rfc9457 则由 Docling 成功解析。因此主结论采用冻结分块对照，额外保存完整重建结果，不隐藏解析差异。

运行入口：[compare_local_models.py](../../../evaluation/compare_local_models.py)。要求隔离数据库名以 rag_compare 开头、冻结 planner snapshot；参数支持 --profile、--reembed-existing、--rebuild、--rerank-input-tokens。Qwen 本地目录可用 --qwen-root 设置。索引输入、模型名称和维度不可混用；本轮已重算全部 Qwen 向量。

新增 Qwen 适配及相关回归 **30 passed**，Ruff 检查通过：[测试日志](qwen-adapter-tests-final.log)。原始对照输出、规划器快照、数据库备份位于忽略的 data/runtime/ 中，测试环境未写入生产数据库，部署默认模型未切换。

实现依据：[Qwen embedding 官方说明](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B)、[Qwen reranker 官方说明](https://huggingface.co/Qwen/Qwen3-Reranker-0.6B)。
