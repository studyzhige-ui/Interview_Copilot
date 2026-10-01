# 08-rag：逐章审查

全部 14 章均有映射。判定针对本项目当前实现；“基础具备”不等于生产验收通过，“边界知识”不要求增加相应技术栈。知识点提纲来自该章二级及三级标题，保留原手册链接供逐点追问；本表的工程判断聚焦章节在项目中的实际落点。

[总报告](../README.md) · [代码证据索引](../代码证据索引.md)

## 01｜RAG 的职责与 Production End-to-End Pipeline

**判定：基础具备**。解析→分块→embedding→索引→混合召回→重排→证据链完整。

**工程证据：** [R2](../代码证据索引.md#r2)。缺陷编号见总报告。

**手册知识点：** 1. 为什么需要 RAG；2. RAG 改变的不是模型参数；3. 一个 Production RAG 的两条主链；Offline / Ingestion Plane；Online / Query Plane；4. Source of Truth 在哪里；5. RAG 的核心不是 Recall 单指标；6. 为什么要 Dense + Sparse + Rerank；7. Context Construction 不是简单拼接 Top-K；8. Grounding 与 Citation；9. RAG Evaluation 必须从第一天设计；10. RAG 和 Vector DB 的边界；11. RAG 和 Agent 的边界；12. 一条 Trace 应该能看到什么；13. 常见错误；14. 面试怎么答；Q：RAG 完整链路是什么？；Q：为什么用了 RAG 仍然会答错？；15. 自测。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/08-rag/docs/01-RAG%E8%81%8C%E8%B4%A3%E4%B8%8E%E5%AE%8C%E6%95%B4%E9%93%BE%E8%B7%AF.md)

## 02｜Corpus Governance：Audit、Identity、Lineage、Version 与 Source of Truth

**判定：需改进**。事实/版本/删除有边界；freshness SLO、漂移和代际回滚需产物。

**工程证据：** [R3](../代码证据索引.md#r3)。缺陷编号见总报告。

**手册知识点：** 1. Corpus Audit 先回答什么；2. Source of Truth 和 Retrieval Index 要分开；3. Document Identity 为什么重要；4. Version 要表达什么；5. Lineage 是什么；6. 为什么 Chunk ID 也要稳定；7. Duplicate 与 Version Duplicate 不一样；8. Corpus Freshness 要定义 SLA；9. Permission 是 Corpus Contract 的一部分；10. Delete / Right-to-be-forgotten；11. Corpus Manifest；12. Audit 最终产出什么；13. 常见错误；14. 面试怎么答；Q：RAG 知识库怎样做增量更新？；Q：为什么 RAG 需要 Lineage？；15. 自测。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/08-rag/docs/02-CorpusGovernance.md)

## 03｜Document Processing：Parsing、OCR、Layout、Multimodal、Cleaning 与 Dedup

**判定：基础具备**。多格式/质量/清洗模块实际存在；复杂 PDF/OCR 质量待真实语料验收。

**工程证据：** [R2](../代码证据索引.md#r2)。缺陷编号见总报告。

**手册知识点：** 1. 为什么不能直接 `extract_text()` 就结束；2. 不同 Source 的解析难点；Markdown / HTML；PDF；Office；3. OCR 什么时候需要；4. Layout 为什么重要；5. Table 为什么不能简单 Flatten；6. Image / Multimodal Document 怎么处理；7. 保留结构，再决定 Chunk；8. Cleaning 解决什么；9. Normalization 要谨慎；10. Exact Dedup；11. Near Duplicate 更难；12. Boilerplate 为什么特别危险；13. Parser Version 必须可追踪；14. Parsing 质量怎么评估；15. Failure Attribution；16. 常见错误；17. 面试怎么答；Q：复杂 PDF 怎么做 RAG？；Q：为什么要 Dedup？；18. 自测。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/08-rag/docs/03-DocumentProcessing.md)

## 04｜Chunking Design：原则、Strategy、Size、Overlap 与实验方法

**判定：基础具备**。token chunk/overlap/结构信息已有；参数不能以直觉证明最优。

**工程证据：** [R2](../代码证据索引.md#r2)。缺陷编号见总报告。

**手册知识点：** 1. 为什么不能整篇文档直接 Embedding；2. 但 Chunk 越小也不是越好；3. Chunk Size 的核心矛盾；Large Chunk；Small Chunk；4. Fixed-size Chunk；5. Recursive / Separator-based Chunk；6. Structure-aware Chunk；7. Semantic Chunk；8. Overlap 为什么存在；9. Overlap 不是越大越好；10. Chunk Size 应由 Query Pattern 决定；11. 不同内容类型应有不同策略；API Doc；Contract；FAQ；Table；Code；12. Chunk Header / Context Enrichment；13. Chunk 参数必须通过实验选择；14. Chunking Failure 怎么看；Answer span 被切断；Chunk 太大；Chunk 太小；Duplicate overlap；15. Chunking 和 Embedding Model 有关系；16. Chunking 和 Reranker 有关系；17. 常见错误；18. 面试怎么答；Q：Chunk Size 怎么定？；Q：Overlap 为什么需要？；19. 自测。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/08-rag/docs/04-ChunkingDesign.md)

## 05｜Advanced Chunk Structure：Parent-child、Neighbor、Semantic Boundary 与 Chunk Data Model

**判定：需改进**。chunk 元数据与来源完善；parent-child/邻接扩展是否有收益需实验，不要求盲加。

**工程证据：** [R2](../代码证据索引.md#r2)。缺陷编号见总报告。

**手册知识点：** 1. Small Chunk / Large Context 的矛盾；2. Parent-child Retrieval；3. Parent 为什么不能无限大；4. Neighbor Window；5. Semantic Boundary Failure；Definition 与 Exception 分离；Table Header 与 Row 分离；Pronoun / Reference 分离；6. Retrieval Unit 不等于 Storage Unit；7. 一个成熟 Chunk Data Model；8. Hierarchy 怎么设计；9. Chunk Metadata 为什么不能无限塞正文；10. Contextualized Chunk；11. Chunk ID 应该怎样生成；12. Parent-child 如何影响 Index 数量；13. Duplicate Context 怎么合并；14. Citation Unit 设计；15. 常见错误；16. 面试怎么答；Q：小 Chunk 和完整上下文怎么兼顾？；Q：Chunk Data Model 为什么重要？；17. 自测。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/08-rag/docs/05-AdvancedChunkStructure.md)

## 06｜Query Understanding & Retrieval Planning：Lifecycle、Rewrite、Clarification、Decomposition、HyDE 与 No-hit

**判定：基础具备**。意图规划、多查询、限制和快照评测具备；需要误路由/漂移当前基线。

**工程证据：** [C2](../代码证据索引.md#c2)。缺陷编号见总报告。

**手册知识点：** 1. 一次 Retrieval Request 的完整入口；2. Query Normalization；3. Query Rewrite 解决什么；4. Rewrite 最大风险：Query Drift；5. Clarification：信息不足时不要猜；6. Query Decomposition；7. Multi-query；8. HyDE 的直觉；9. History-aware Query；10. Query Planning 要考虑 Retriever 类型；11. Metadata / Permission Scope 应先进入 Plan；12. No-hit 是正常结果，不是异常；13. Threshold 为什么不能只看 Vector Score；14. Conflict Evidence 怎么办；15. Query Plan 的可观测性；16. 常见错误；17. 面试怎么答；Q：Query Rewrite 为什么有用？；Q：什么时候做 Multi-query / HyDE？；Q：RAG 没召回结果怎么办？；18. 自测。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/08-rag/docs/06-QueryPlanning.md)

## 07｜Retrieval Stack：Dense、BM25、Hybrid 与 Fusion

**判定：基础具备**。dense+中文 BM25+加权 RRF；缺规模及效果对照 F13。

**工程证据：** [R1](../代码证据索引.md#r1)。缺陷编号见总报告。

**手册知识点：** 1. Dense Retrieval 擅长什么；2. Sparse / BM25 擅长什么；3. Dense 和 Sparse 不是谁淘汰谁；Query A；Query B；4. Hybrid Retrieval 是什么；5. 为什么不能直接比较 Dense Score 和 BM25 Score；6. RRF 的核心思想；7. RRF 参数 k 怎么理解；8. Candidate Dedup；9. Hybrid 的成本不是免费；10. Query Routing vs Always Hybrid；11. Metadata Filter 应在哪一层；12. Hybrid 为什么可能变差；13. Exact Keyword / Identifier 的特殊处理；14. Retrieval 评估怎么比较方案；15. 常见错误；16. 面试怎么答；Q：为什么 RAG 常用 Hybrid Search？；Q：RRF 为什么适合 Dense + BM25？；17. 自测。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/08-rag/docs/07-RetrievalStack.md)

## 08｜Rerank 与 Candidate Budget：从高 Recall 候选到高 Precision Evidence

**判定：基础具备**。candidate/final/intent budget 与 reranker timeout 明确；阈值需新后端校准。

**工程证据：** [R1](../代码证据索引.md#r1)。缺陷编号见总报告。

**手册知识点：** 1. 为什么第一阶段不直接追求最终 Top5；2. Reranker 为什么更精确；3. Candidate Budget 是什么；4. Top-K 应该在哪里定义；5. Reranker Score 能直接设通用 Threshold 吗；6. 为什么加 Reranker 可能反而变差；Candidate 根本没召回 Ground Truth；Domain mismatch；Input Truncation；Query Rewrite Drift；Candidate Duplicate；Score Calibration / Top-K 不合适；7. Rerank 的输入应该是什么；8. Diversity 为什么重要；9. Multi-hop 问题需要什么；10. Rerank Latency 怎么控制；11. Top-K 为什么必须和 Context Budget 联动；12. No-hit 和 Reranker 的关系；13. Eval 应怎样验证 Candidate Funnel；14. 常见错误；15. 面试怎么答；Q：为什么常见 Top20 再 Rerank Top5？；Q：Rerank 后效果反而变差怎么排查？；16. 自测。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/08-rag/docs/08-Rerank%E4%B8%8ECandidateBudget.md)

## 09｜Context Construction、Grounding 与 Citation：从 Candidate 到可验证 Evidence

**判定：需改进**。canonical hydrate/证据门/引用可追溯；补 owner 强约束及引用正确率 F15/F12。

**工程证据：** [R4](../代码证据索引.md#r4)。缺陷编号见总报告。

**手册知识点：** 1. Retriever Result 不能直接全部塞给 LLM；2. Context Builder 的输入；3. Dedup / Merge；4. Context Budget；5. Evidence Ordering；6. Context Compression；7. Grounding 是什么；8. Citation 为什么需要 Stable Mapping；9. Citation 不等于 Claim Supported；10. 冲突 Evidence 怎么处理；11. Multi-hop Evidence Coverage；12. Permission 必须在 Context 前已生效；13. Prompt Injection 与 Retrieved Content；14. Context Trace；15. 常见错误；16. 面试怎么答；Q：RAG 检索结果怎么放进 Context？；Q：为什么 Citation 不能只让模型自由生成？；17. 自测。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/08-rag/docs/09-EvidenceDelivery.md)

## 10｜Retrieval Evaluation：Metrics、Ground Truth、Dataset 与 LLM Judge

**判定：不合格**。旧 release_ready=false，且运行契约仍是 Milvus；当前 pgvector 未有发布证据 F12。

**工程证据：** [Q2](../代码证据索引.md#q2)。缺陷编号见总报告。

**手册知识点：** 1. 先区分 Retrieval Eval 和 Answer Eval；Retrieval Eval；Generation Eval；2. Evaluation Dataset 至少包含什么；3. Ground Truth 从哪里来；4. Synthetic Data 为什么有用又危险；5. Recall@K；6. Precision@K；7. MRR；8. NDCG；9. Metric 必须和任务对齐；QA；Search UI；Multi-hop；10. Query Slice 比总体平均更重要；11. Ground Truth 粒度问题；12. Label 不是绝对客观；13. LLM Judge 能做什么；14. LLM Judge 的风险；15. Judge Prompt 也要版本化；16. Online Signal 和 Offline Eval；17. Eval Dataset 应持续增长；18. 常见错误；19. 面试怎么答；Q：RAG 怎么评估？；Q：Evaluation Dataset 怎么建设？；20. 自测。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/08-rag/docs/10-RetrievalEvaluation.md)

## 11｜End-to-End Evaluation：Baseline、Ablation、Regression 与 Bad Case Attribution

**判定：不合格**。单元测试和质量脚本不等于真实问答达标；需答案/拒答/证据联合门禁。

**工程证据：** [Q2](../代码证据索引.md#q2)。缺陷编号见总报告。

**手册知识点：** 1. 为什么 Retrieval 指标好不等于最终答案好；2. End-to-end Eval 看什么；3. Baseline 为什么重要；4. Ablation 是什么；5. 为什么一次只改一个变量；6. Regression Set；7. Bad Case Attribution 的第一原则；8. 一张标准 Attribution 表；9. Retrieval Bad Case 怎样进一步拆；Exact 也找不到；Exact 找到、ANN 找不到；No-filter 找到、Filter 后找不到；Retriever 找到、Reranker 掉了；10. Generation Bad Case 怎样拆；11. No-answer Case 必须单独测；12. A/B 与 Offline Eval 的关系；13. 需要同时看成本；14. Version Lock；15. Bad Case Taxonomy；16. Evaluation Flywheel；17. 常见错误；18. 面试怎么答；Q：RAG 怎么证明优化有效？；Q：RAG 召回不准怎么定位？；19. 自测。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/08-rag/docs/11-EndToEndQualityEngineering.md)

## 12｜Production Governance：Freshness、Version、Permission、Tenant、Snapshot 与 Rollback

**判定：需改进**。增量与对账已做；broker/worker 崩溃下用户文档终态需验收 F07。

**工程证据：** [R3](../代码证据索引.md#r3)。缺陷编号见总报告。

**手册知识点：** 1. Freshness 是 RAG 的系统属性；2. 先定义 Freshness SLA；3. 增量更新的基本链路；4. Blue-Green Knowledge Generation；5. Full Rebuild 为什么需要 Snapshot Boundary；6. Version 应该存在哪些层；7. Rollback 为什么必须保留旧 Generation；8. Permission 不是最后的 Post-filter；9. ACL 怎样传播到 Chunk；10. Permission Change 也需要增量同步；11. Pre-filter vs Post-filter 的安全边界；12. Cache 也会造成权限与 Freshness 问题；13. Time-aware Retrieval；14. Delete / Revocation 要定义传播时间；15. Production 对账；16. 监控指标；17. 常见错误；18. 面试怎么答；Q：RAG 知识库怎么不停服更新？；Q：多租户 RAG 权限怎么做？；19. 自测。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/08-rag/docs/12-ProductionGovernance.md)

## 13｜Large-scale Ingestion、Latency / Cost、Cache 与 Observability

**判定：需改进**。每查询重算租户统计；规模/成本/时延尚不能量化 F13/F17。

**工程证据：** [R1](../代码证据索引.md#r1)。缺陷编号见总报告。

**手册知识点：** 1. 从 Demo 到 Production，问题发生了什么变化；2. Ingestion 应该是可恢复 Pipeline，不是一段 for-loop；3. Idempotency 要围绕“输入版本 + 处理版本”设计；4. Backpressure：为什么“加并发”经常让 Ingestion 更慢；5. Ingestion State Machine；6. 大规模 Rebuild 怎样不停服；7. Delta Catch-up 为什么需要；8. 在线 Query Latency 必须按 Stage 拆；9. Tail Latency 比平均值更重要；10. SLO 应该和用户体验对应；11. 成本要分 Offline 和 Online；Offline / Ingestion；Online；12. Candidate Budget 是成本控制点；13. Cache 可以放在哪里；Embedding Cache；Retrieval Cache；Rerank Cache；Answer Cache；14. Cache Invalidation 应该跟 Version 走；15. Production Trace 要保存什么；16. Trace 和 Log 不一样；17. Quality Monitoring 不能只靠线上用户投诉；18. Freshness Observability 是 RAG 特有核心指标；19. Degradation / Load Shedding；20. 三个典型 Failure Timeline；20.1 Embedding Provider 429；20.2 Rebuild 切换后质量暴跌；20.3 Vector DB P99 抖动；21. 🎯 30 秒回答；22. ⚠️ 易错点；23. 🔍 深挖追问。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/08-rag/docs/13-ScaleCostObservability.md)

## 14｜GraphRAG、Agentic RAG 与 Production Architecture

**判定：边界知识**。agent search 已可调用，GraphRAG/HyDE 不是合格必选；按失败集决定。

**工程证据：** [C2](../代码证据索引.md#c2)。缺陷编号见总报告。

**手册知识点：** 1. 先把三种问题分开；普通 Retrieval 问题；Relation / Multi-hop 问题；Dynamic Retrieval 问题；2. GraphRAG 解决什么；3. GraphRAG 不是“把 Chunk 全转成图”这么简单；4. Graph 中的 Relation 也需要 Provenance；5. Graph Retrieval 常见模式；5.1 Neighbor Expansion；5.2 Path Query；5.3 Constraint Query；5.4 Community / Cluster Summary；6. Graph Retrieval 最后仍要回到 Evidence；7. Vector + Keyword + Graph 怎样组合；8. GraphRAG 的更新为什么难；9. GraphRAG 的主要 Failure；Entity Extraction Error；Entity Resolution Error；Relation Hallucination；Stale Graph；Over-expansion；Summary Distortion；10. GraphRAG 怎样评估；Graph Construction Quality；End-to-end QA；12. Agentic RAG 的 Runtime State；13. Evidence Sufficiency：什么时候可以停止搜；14. No-new-evidence Detection；15. Query Drift 怎样防；16. Agentic RAG 的 Cost Budget；17. Multi-source Routing；18. Agentic RAG Failure Timeline；Infinite Loop；Query Drift；Cost Explosion；Unsupported Stop；Source Selection Error；Permission Escalation；19. Agentic RAG 怎样评估；20. 什么时候不应该用 GraphRAG / Agentic RAG；不需要 GraphRAG；不需要 Agentic RAG；21. Production Architecture；22. 🎯 30 秒回答；23. ⚠️ 易错点；24. 🔍 深挖追问。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/08-rag/docs/14-GraphRAG%E4%B8%8EAgenticRAG.md)
