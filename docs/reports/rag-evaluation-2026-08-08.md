# RAG 全链路重构与发布评测报告（2026-08-08）

## 结论

本轮工程重构、数据集重建和固定 GPU 检索验收均已完成，但当前 RAG 质量尚未达到
发布门禁：`release_ready=false`。因此程序按预定协议拒绝把该结果交给生成评测，
没有执行付费 RAGAS 兼容性检查或正式 50 条评测。

这不是运行错误，也不是通过降低阈值掩盖问题。校准集独立选择了
`min_score=0.81`、`score_margin=0.02`，随后 test split 只打开一次。测试集的候选召回
和无阈值 Top-3 已经较强，但证据门后的严格原子证据覆盖、排序和 Query Precision
仍有四项未过线。下一轮必须改进通用检索/重排能力并准备新的独立留出集，不能继续
查看这份 test 结果后在同一数据上调参。

## 评测对象与边界

- 生产链路：多格式解析 → 清洗 → token-safe chunk → BGE-M3 Embedding → Milvus
  Dense/BM25 → RRF → BGE Reranker → 证据门 → PostgreSQL 水合。
- 固定结构参数：chunk `384`、overlap `64`、候选池 `20`、最终上下文 `3`。
- Community 运行时仍支持 CPU；本轮维护者发布验收只使用 CUDA，没有运行纯 CPU
  性能基准。
- PDF 是 HTML、Markdown、TXT 之外的必需格式之一，不是唯一输入格式。
- 规划器输出在所有结构配置和数据切片之间冻结；金标不会进入 planner 或检索请求。

## 数据集

独立数据 agent 只依据 25 份固定哈希的真实官方语料重建并审查数据，没有调用回答
模型或 RAGAS：

| 项目 | 数量 |
|---|---:|
| 总行数 | 457 |
| Retrieval 行 | 421 |
| 可回答正例 | 373 |
| 困难负例 | 48 |
| Planner trajectory 行 | 36 |
| 显式多文档正例 | 12 |
| 原子 evidence groups | 538 |
| 等价 evidence alternatives | 541 |
| 正式 RAGAS 固定样本 | 50 |

正例覆盖 HTML `152`、Markdown `161`、TXT `16`、PDF `32` 和多文档 `12`。每个
证据组表示一个必须覆盖的原子事实；同组 alternatives 是等价 OR 表达，不会把同主题、
导航、邻接段落或反例代码算作正确证据。当前 384/64 索引上，373 条正例的 538 个
证据组全部能映射，空组为 0。数据集 SHA-256 为
`01db8a9cee586c38421d4115a1b136af143697fedb259375db635f798ecd67de`。

## 索引与硬件

| 项目 | 值 |
|---|---|
| GPU | NVIDIA GeForce RTX 5060 Ti |
| PyTorch / CUDA | 2.9.1+cu128 / 12.8 |
| Embedding | BAAI/bge-m3，1024 维 |
| Reranker | BAAI/bge-reranker-v2-m3 |
| 文档 / chunk | 25 / 1599 |
| Docling | 11 份文档，699 chunks |
| PyMuPDF fallback | RFC 9110，414 chunks |
| 纯文本解析 | 13 份文档，486 chunks |
| 索引指纹 | `96f70001f73fc82d4402ed9d8461c836b2d6e6a0d85b2e888d053ee88366faf8` |

RFC 9457 PDF 由 Docling 成功解析；RFC 9110 的 Docling 完整转换失败后按整份文档回退
到 PyMuPDF。两种结果都经过相同清洗和最终 token splitter，不会在一个 PDF 内混用两套
部分结果。

## Calibration 结果

133 条 calibration 行只用于选择证据门。绝对 reranker 分数不得低于 `0.80`；在满足
校准门禁的可行解中，程序选择 `0.81 + 0.02 margin`。

| 指标 | 结果 |
|---|---:|
| Query Precision / Recall / F1 | 0.9640 / 0.9304 / 0.9469 |
| Passage Hit@3 | 0.9304 |
| MRR@3 / nDCG@3 | 0.8754 / 0.8863 |
| Evidence-group Recall@3 | 0.9261 |
| Document Recall@3 | 0.9652 |
| Exact evidence precision（micro） | 0.6337 |
| Context evidence precision（macro） | 0.7319 |
| 困难负例 FPR | 0.0000 |

所有 calibration 发布门禁均通过，随后 campaign ledger 在 test 调用前原子领取唯一一次
held-out 运行权。更换输出文件名不能再次打开同一 campaign。

## Held-out 结果

288 条 test 行没有参与阈值选择。完整结果如下：

| 指标 | 结果 | 门禁 | 状态 |
|---|---:|---:|---|
| Candidate gold Hit@20 | 0.9961 | 0.98 | 通过 |
| Candidate source Hit@20 | 1.0000 | 0.99 | 通过 |
| Candidate evidence-group recall | 0.9916 | 0.98 | 通过 |
| 无阈值 Reranked Hit@1 | 0.8411 | 0.80 | 通过 |
| 无阈值 Reranked Hit@3 | 0.9651 | 0.95 | 通过 |
| 证据门后 Passage Hit@3 | 0.9186 | 0.92 | **失败** |
| Source Hit@3 | 0.9922 | 0.95 | 通过 |
| MRR@3 | 0.8779 | 0.85 | 通过 |
| nDCG@3 | 0.8522 | 0.87 | **失败** |
| Evidence-group Recall@3 | 0.8727 | 0.90 | **失败** |
| Document Recall@3 | 0.9922 | 0.95 | 通过 |
| Query Precision | 0.9258 | 0.95 | **失败** |
| Query Recall | 0.9186 | 0.90 | 通过 |
| Exact evidence precision（micro） | 0.6163 | 0.55 | 通过 |
| Context evidence precision（macro） | 0.6977 | 0.65 | 通过 |
| Reranker AUROC | 0.8688 | 0.85 | 通过 |
| 困难负例 FPR | 0.0000 | ≤0.05 | 通过 |
| GPU P95 检索延迟 | 1231.2 ms | <1500 ms | 通过 |

格式切片没有被总体均值掩盖：证据门后 recall 为 HTML `0.9274`、Markdown
`0.8947`、PDF `1.0000`、多文档 mixed `1.0000`；英文 `0.9292`、中文 `0.9103`。
租户 canary 的 owner hit 为真、foreign leak 为假，跨租户违规为 0。

## 指标如何理解

- Candidate Hit/Recall 看重排前有没有把正确证据放入候选池。本轮接近 100%，说明主要
  瓶颈不在候选池大小。
- Hit@3 只回答“前三名至少有一个正确证据吗”；它不保证多证据问题已经找全。
- MRR@3 更关心第一个正确证据排第几；第 1/2/3 名分别贡献 1、1/2、1/3。
- nDCG@3 同时考虑多个原子证据的覆盖和顺序，因此会比单一 Hit@3 更严格。
- Evidence-group Recall@3 衡量题目需要的所有原子事实找全多少。当前 `0.8727` 表明
  多事实/多文档合成仍是最明确的质量缺口。
- Query Precision 在这里不是“返回 chunk 的比例”，而是放行上下文后确实包含严格
  金标证据的问题比例。困难负例虽然全部拒答，但仍有正例放行了不完整或错误上下文。
- Exact evidence precision 只认人工标注的原子证据 chunk；语义相关但未直接支持原子
  事实的 chunk 会被当作噪声。RAGAS Context Precision 原计划用于补充语义裁判，但本轮
  因检索 release gate 失败而没有执行。

## 为什么没有运行 RAGAS

正式生成入口只接受 `status=completed` 且 `release_ready=true` 的 CUDA profile。本轮
profile 明确为 false，若绕过检查继续运行，不仅会花费回答与裁判费用，还会产生一个
建立在未发布检索配置上的误导性“正式分数”。因此本轮 RAGAS 状态是：

- Compatibility check：未执行；
- Formal 50：未执行；
- RAGAS 阶段回答/裁判 API 费用：0；
- 原因：检索 held-out 四项门禁失败，按协议 fail closed。

## 下一轮正确边界

本轮不能再使用相同 held-out 进行阈值或规则微调。下一轮应作为新的评测 campaign：

1. 优先改进通用的多证据重排与合并，而不是扩大候选池或为四个问题写规则；
2. 保持固定 384/64/20/3，除非新的独立实验给出足够证据改变结构；
3. 由独立数据 agent 准备新的 source/group-aware held-out，旧 test 只作历史诊断；
4. 新 calibration 全部通过后只打开一次新 test；
5. 只有新 held-out `release_ready=true`，才运行一次 live check 和正式 RAGAS50。

当前结论应表述为：RAG 工程链路、可复现评测、数据契约和安全门禁已经收口；检索质量
距离发布只剩明确、可量化的通用重排/多证据覆盖问题，但本轮不能宣称“RAG 已发布”。
