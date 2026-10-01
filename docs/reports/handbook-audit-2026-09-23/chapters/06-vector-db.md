# 06-vector-db：逐章审查

全部 16 章均有映射。判定针对本项目当前实现；“基础具备”不等于生产验收通过，“边界知识”不要求增加相应技术栈。知识点提纲来自该章二级及三级标题，保留原手册链接供逐点追问；本表的工程判断聚焦章节在项目中的实际落点。

[总报告](../README.md) · [代码证据索引](../代码证据索引.md)

## 01｜Vector DB 在 AI Application 中负责什么

**判定：基础具备**。pgvector 为派生检索索引；SQL 文档与分块仍为规范事实。

**工程证据：** [R1](../代码证据索引.md#r1)。缺陷编号见总报告。

**手册知识点：** 1. 先看一个 AI Knowledge Base；Embedding Model；Vector DB；Q：Vector DB 是做什么的？；Q：为什么不用 MySQL 直接存 JSON 向量？。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/06-vector-db/docs/01-VectorDB%E5%9C%A8AI%E5%BA%94%E7%94%A8%E4%B8%AD%E7%9A%84%E8%81%8C%E8%B4%A3.md)

## 02｜Vector Space & Similarity：Dimension、Normalization 与距离度量

**判定：基础具备**。模型/维度/metric 指纹和向量校验齐全；同维度换模型不能复用。

**工程证据：** [R3](../代码证据索引.md#r3)。缺陷编号见总报告。

**手册知识点：** 1. Vector 最直观的样子；2. Dimension 不只是数组长度；3. 同维度不代表同一个向量空间；4. 向量的方向与长度；5. Cosine / Dot Product / L2 到底在比较什么；Cosine Similarity；Dot Product / Inner Product；L2 / Euclidean Distance；6. Normalized Vector 上三种 Metric 的关系；7. 为什么不能无脑 Normalize；8. Metric 选错会发生什么；9. 一个简单例子；10. Score Threshold 为什么不能抄固定值；11. Vector Record 应记录哪些契约；12. 高频易错点；13. 面试怎么答；Q：Cosine、Dot Product、L2 怎么选？；Q：Dimension 对系统有什么影响？；14. 自测。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/06-vector-db/docs/02-VectorSpace%E4%B8%8ESimilarity.md)

## 03｜Exact Search vs ANN：从 Top-K Ground Truth 到 Recall / Latency Trade-off

**判定：需改进**。exact/HNSW 两种路径存在；缺实际数据 ANN 相对 exact recall 曲线 F13。

**工程证据：** [R1](../代码证据索引.md#r1)。缺陷编号见总报告。

**手册知识点：** 1. Top-K Nearest Neighbor 是什么；2. Exact Search 最直接怎么做；3. Top-K Selection 本身怎么优化；4. Exact Search 为什么是 ANN 的 Ground Truth；5. 为什么规模上来以后 Exact 会变贵；6. GPU / SIMD 为什么不能完全替代 ANN；7. ANN 的 Approximate 到底近似什么；8. ANN 的核心 Trade-off；9. ANN 为什么能少看很多向量；Graph-based；Partition-based；Compression / Quantization；10. ANN 不是免费加速器；11. ANN 参数应该怎么调；12. RAG 召回差，怎么判断是不是 ANN 导致；13. 什么时候 Exact Search 就够了；14. 常见错误；15. 面试怎么答；Q：为什么不能一直用暴力 Vector Search？；Q：ANN 牺牲什么换什么？；16. 自测。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/06-vector-db/docs/03-ExactSearch%E4%B8%8EANN.md)

## 04｜ANN Index 谱系：Graph、Partition、Quantization

**判定：边界知识**。有 HNSW 就无需集齐 ANN 算法；能解释图/分区/压缩权衡即可。

**工程证据：** [R1](../代码证据索引.md#r1)。缺陷编号见总报告。

**手册知识点：** 1. ANN Index 在解决什么；Q：ANN 常见索引思路有哪些？。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/06-vector-db/docs/04-ANN%E7%B4%A2%E5%BC%95%E8%B0%B1%E7%B3%BB.md)

## 05｜HNSW：机制、M、efConstruction、efSearch 与调优

**判定：需改进**。M/efConstruction/efSearch/iterative scan 已配置；无规模调参证据 F13。

**工程证据：** [R1](../代码证据索引.md#r1)。缺陷编号见总报告。

**手册知识点：** 1. 从普通近邻图开始；2. 为什么普通近邻图还不够；3. 查询过程；4. 为什么叫 Small World；5. HNSW 为什么仍然是 Approximate；6. Build 时发生什么；7. M：图连接密度；8. efConstruction：建图时搜多宽；9. efSearch：查询时探索多宽；10. efSearch 和 Top-K 不是一个东西；11. 为什么 HNSW 很吃内存；12. Filter 会改变最佳参数；13. 参数调优的正确流程；14. 数据变化后还要不要重新调；15. HNSW 的 Update / Delete 边界；16. HNSW 不解决什么；17. 常见错误；18. 面试怎么答；Q：HNSW 为什么高效？；Q：M、efConstruction、efSearch 分别控制什么？；19. 自测。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/06-vector-db/docs/05-HNSW%E6%9C%BA%E5%88%B6%E4%B8%8E%E8%B0%83%E4%BC%98.md)

## 06｜IVF：Coarse Quantizer、nlist 与 nprobe

**判定：边界知识**。未用 IVF 是选型边界；需要训练与 nprobe 知识，不要求补实现。

**工程证据：** [R1](../代码证据索引.md#r1)。缺陷编号见总报告。

**手册知识点：** 1. 从“全库扫描”到“先分区”；Q：IVF 是怎么做 ANN 的？；Q：IVF_FLAT 和 IVF_PQ 有什么区别？。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/06-vector-db/docs/06-IVF%E5%8E%9F%E7%90%86.md)

## 07｜Quantization：SQ / PQ 与压缩检索

**判定：边界知识**。未做 PQ 合理；先证实内存瓶颈再引入量化误差。

**工程证据：** [R1](../代码证据索引.md#r1)。缺陷编号见总报告。

**手册知识点：** 1. Scalar Quantization 直觉；Q：PQ 解决什么问题？。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/06-vector-db/docs/07-Quantization%E4%B8%8EPQ.md)

## 08｜HNSW vs IVF 与 Index Selection

**判定：需改进**。选 pgvector 简化运维有理由；需 ANN recall、过滤率、P95、内存对照。

**工程证据：** [R1](../代码证据索引.md#r1)。缺陷编号见总报告。

**手册知识点：** 1. 先看最核心的比较维度；场景 A：500 万条知识库向量；场景 B：5 亿条向量；Q：HNSW 和 IVF 怎么选？。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/06-vector-db/docs/08-IndexSelection.md)

## 09｜Collection / Schema / Primary Key / Metadata

**判定：基础具备**。generation 表、tenant/document/source/node 身份完整。

**工程证据：** [R3](../代码证据索引.md#r3)。缺陷编号见总报告。

**手册知识点：** 1. 一个典型 Vector Record；5.1 只存 Vector + ID；5.2 Vector + Chunk Text 一起存；5.3 存一部分 Retrieval Metadata；Q：Vector DB 的 Schema 应该怎么设计？。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/06-vector-db/docs/09-Vector%E6%95%B0%E6%8D%AE%E5%BB%BA%E6%A8%A1.md)

## 10｜Metadata Filter、Pre-filter 与 Post-filter

**判定：基础具备**。参数绑定且检索前 owner/filter、附件范围已实现。

**工程证据：** [R1](../代码证据索引.md#r1)。缺陷编号见总报告。

**手册知识点：** 1. Filter 为什么是 Vector DB 的核心能力；Q：Vector Search 的 Metadata Filter 怎么做？。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/06-vector-db/docs/10-MetadataFilter.md)

## 11｜Partition / Namespace / Tenant Isolation

**判定：需改进**。首层过滤和候选复核存在；hydrate 未接受 owner 是纵深防御缺口 F15。

**工程证据：** [R1](../代码证据索引.md#r1)。缺陷编号见总报告。

**手册知识点：** 1. 为什么需要 Partition；Q：多租户 Vector DB 怎么设计？。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/06-vector-db/docs/11-Partition%E4%B8%8ETenantIsolation.md)

## 12｜Vector Index Lifecycle：写入、删除、Tombstone、Compaction、Re-embedding 与 Rebuild

**判定：需改进**。原子替换/墓碑/发布指纹/outbox 已有；全量代际切换及旧代际回收待验收。

**工程证据：** [R3](../代码证据索引.md#r3)。缺陷编号见总报告。

**手册知识点：** 1. Insert 不只是 Append；2. Upsert / Update 为什么比关系字段复杂；3. Metadata Update 和 Vector Update 要区分；4. Delete 为什么常用 Tombstone；5. Tombstone 不能无限积累；6. Compaction 在做什么；7. Segment 为什么重要；8. Compaction 为什么会影响前台 SLA；9. Index Maintenance 不只是 Compaction；10. 为什么 Embedding Model 升级通常要 Re-embedding；11. Vector Version 与 Index Version 要分开；12. Chunk Strategy 变化为什么也会触发 Rebuild；13. Blue-Green Index；14. 全量 Rebuild 期间的新数据怎么办；15. Delete / Update 必须有 Source Mapping；16. Upsert 不自动解决并发一致性；17. Delete 成功后为什么仍可能搜到旧数据；18. 怎样验证一个新 Index Generation；Infrastructure Layer；Retrieval / RAG Layer；19. Maintenance 需要监控什么；20. 常见错误；21. 面试怎么答；Q：Embedding 模型升级后怎么迁移 Vector DB？；Q：Vector DB Delete 为什么还需要 Compaction？；22. 自测。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/06-vector-db/docs/12-VectorIndex%E7%94%9F%E5%91%BD%E5%91%A8%E6%9C%9F.md)

## 13｜Shard / Replica / Segment：分布式 Vector DB 基础

**判定：边界知识**。单 PostgreSQL 无分片 fanout；不能宣称分布式向量吞吐。

**工程证据：** [D1](../代码证据索引.md#d1)。缺陷编号见总报告。

**手册知识点：** 1. 为什么要 Shard；Q：分布式 Vector DB 怎么扩展查询？。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/06-vector-db/docs/13-%E5%88%86%E5%B8%83%E5%BC%8FVectorDB.md)

## 14｜Performance、Capacity 与 Production Diagnosis

**判定：需改进**。缺大 tenant BM25/ANN 并发与 EXPLAIN 数据 F13。

**工程证据：** [R1](../代码证据索引.md#r1)。缺陷编号见总报告。

**手册知识点：** 1. Vector DB 的性能不是单指标；2. Recall：先分清 Index Recall 和业务 Recall；3. Latency 不要只看 Average；4. QPS 和 Latency 必须一起看；5. Memory 怎么估；6. HNSW 为什么要单独算 Graph Overhead；7. Build Cost 为什么是一等指标；8. Dynamic Workload 还要测 Update Cost；9. Filter Cost 为什么经常被低估；10. 一份容量规划输入清单；12. Query Latency 突然变慢怎么查；13. Recall 下降的四层对照法；Exact + No Filter 都找不到；Exact 能找到，ANN 找不到；No Filter 找得到，加 Filter 找不到；14. Memory 暴涨怎么查；15. Index Size 一直涨但业务数据没涨；16. Write / Upsert 越来越慢；17. 某个 Tenant 特别慢；18. Rebuild 后 Recall 突变；19. Distributed Query 偶发超时；20. 一张 Production 排查树；21. 常见错误；22. 面试怎么答；Q：Vector DB 选型和压测看哪些指标？；Q：Vector DB Recall 下降怎么排查？；Q：P99 突然变差怎么查？；23. 自测。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/06-vector-db/docs/14-%E6%80%A7%E8%83%BD%E5%AE%B9%E9%87%8F%E4%B8%8EProduction%E8%AF%8A%E6%96%AD.md)

## 15｜FAISS / pgvector / Elasticsearch Vector / Milvus / Qdrant 怎样选

**判定：基础具备**。PostgreSQL+pgvector 符合当前简化目标；历史 Milvus 报告不能证明新后端 F12。

**工程证据：** [R1](../代码证据索引.md#r1)。缺陷编号见总报告。

**手册知识点：** 1. 先分四种架构类别；Q：Milvus、FAISS、pgvector、Elasticsearch Vector 怎么选？。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/06-vector-db/docs/15-%E4%BA%A7%E5%93%81%E4%B8%8E%E6%9E%B6%E6%9E%84%E9%80%89%E5%9E%8B.md)

## 16｜Graph DB vs Vector DB，以及 Vector DB 在 AI 系统中的位置

**判定：边界知识**。Graph DB/GraphRAG 尚非本项目必要组件；先定义多跳失败集。

**工程证据：** [R1](../代码证据索引.md#r1)。缺陷编号见总报告。

**手册知识点：** 8.1 业务 Source of Truth；8.2 短期高速状态；8.3 语义检索；8.4 显式关系；Vector Infrastructure；Retrieval System；Q：Vector DB 和 Graph DB 有什么区别？；Q：为什么不把所有数据都放 Vector DB？；Q：Vector DB 在 RAG 里负责到哪里？。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/06-vector-db/docs/16-GraphDB%E8%BE%B9%E7%95%8C%E4%B8%8E%E7%B3%BB%E7%BB%9F%E8%AE%BE%E8%AE%A1.md)
