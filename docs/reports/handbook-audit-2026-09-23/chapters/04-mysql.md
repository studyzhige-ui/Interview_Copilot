# 04-mysql：逐章审查

全部 23 章均有映射。判定针对本项目当前实现；“基础具备”不等于生产验收通过，“边界知识”不要求增加相应技术栈。知识点提纲来自该章二级及三级标题，保留原手册链接供逐点追问；本表的工程判断聚焦章节在项目中的实际落点。

[总报告](../README.md) · [代码证据索引](../代码证据索引.md)

## 01. MySQL 在 AI Application 中负责什么

**判定：基础具备**。项目实际使用 PostgreSQL；关系库事实职责适用，不应为了课程换 MySQL。

**工程证据：** [D3](../代码证据索引.md#d3)。缺陷编号见总报告。

**手册知识点：** 1. 先讲人话：MySQL 更像“业务事实账本”；2.1 用户与租户；2.2 Conversation / Message；2.3 Agent Run / Task State；2.4 Tool Execution / 外部副作用记录；2.5 Knowledge Base Metadata；一个常见组合；误区一：所有聊天记录都丢 Redis；误区二：有 Vector DB 就不需要关系库；误区三：事务能解决所有分布式一致性；Q：AI 应用里 MySQL 通常存什么？；Q：为什么默认讨论 InnoDB？。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/04-mysql/docs/01-MySQL%E5%9C%A8AI%E5%BA%94%E7%94%A8%E4%B8%AD%E7%9A%84%E8%81%8C%E8%B4%A3.md)

## 02. SQL 基础与一条 SQL 的执行链路

**判定：基础具备**。SQLAlchemy→psycopg2→PostgreSQL 链明确；解释 SQL 与事务发起时机。

**工程证据：** [D3](../代码证据索引.md#d3)。缺陷编号见总报告。

**手册知识点：** 1. 先从最小 SQL 开始；一个非常重要的表达；Server 层关心；InnoDB 关心；9.1 `SELECT`；9.2 `INSERT`；9.3 `UPDATE`；9.4 `DELETE`；Query A；Query B；Query C；Q：一条 SQL 从进入 MySQL 到返回，大致经历什么？。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/04-mysql/docs/02-SQL%E5%9F%BA%E7%A1%80%E4%B8%8E%E6%89%A7%E8%A1%8C%E9%93%BE%E8%B7%AF.md)

## 03. Index 基础：索引到底在优化什么

**判定：需改进**。模型有唯一/复合索引；没有业务规模查询计划证据 F13。

**工程证据：** [D3](../代码证据索引.md#d3)。缺陷编号见总报告。

**手册知识点：** 1. 没有合适索引时发生什么；4.1 按业务约束；Primary Key；Unique Index；Non-unique Secondary Index；4.2 按列数；4.3 按 InnoDB 数据组织；7.1 Filter；7.2 Range；7.3 Join Lookup；7.4 ORDER BY；7.5 Covering；INSERT；UPDATE；额外成本；Q：什么是索引？为什么能提高查询性能？；Q：是不是 WHERE 字段都应该建索引？。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/04-mysql/docs/03-Index%E5%9F%BA%E7%A1%80.md)

## 04. 为什么 InnoDB 使用 B+Tree

**判定：边界知识**。讲 B-tree 页与范围访问；不能将 InnoDB 聚簇细节套给 PostgreSQL。

**工程证据：** [D3](../代码证据索引.md#d3)。缺陷编号见总报告。

**手册知识点：** 1. 先从“磁盘 / Page 友好”理解；5.1 非叶子节点主要用于导航；5.2 数据集中在 Leaf；5.3 Leaf Page 有序相连；B+Tree vs 红黑树；B+Tree vs Hash；B+Tree vs B-Tree。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/04-mysql/docs/04-B%2BTree%E7%B4%A2%E5%BC%95%E5%8E%9F%E7%90%86.md)

## 05. 聚簇索引与二级索引

**判定：边界知识**。PostgreSQL heap/index 与 InnoDB 主键聚簇不同；无须模拟 MySQL 物理层。

**工程证据：** [D3](../代码证据索引.md#d3)。缺陷编号见总报告。

**手册知识点：** 1. 先讲人话：InnoDB 的“表数据”和主键索引绑在一起；方案 A；方案 B；Q：什么是聚簇索引？；Q：什么是二级索引？为什么会回表？；Q：为什么 Primary Key 不建议太长？。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/04-mysql/docs/05-%E8%81%9A%E7%B0%87%E7%B4%A2%E5%BC%95%E4%B8%8E%E4%BA%8C%E7%BA%A7%E7%B4%A2%E5%BC%95.md)

## 06. 联合索引与最左前缀

**判定：需改进**。租户/会话/状态复合索引需按真实 where+order 验证左前缀。

**工程证据：** [D3](../代码证据索引.md#d3)。缺陷编号见总报告。

**手册知识点：** 1. 先讲人话：联合索引是一套“按列顺序排序”的结构；5.1 B+Tree Lookup Range 能缩小到哪里？；5.2 那 C 完全没用了吗？；第一步：A 能否用于 Index Range？；第二步：B=0 能否把所有结果继续缩成一个连续范围？；第三步：B 是否可能继续被用来过滤？；Q：什么是最左匹配？；Q：范围查询以后后面的列是不是完全失效？；Q：WHERE 条件必须按联合索引顺序写吗？。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/04-mysql/docs/06-%E8%81%94%E5%90%88%E7%B4%A2%E5%BC%95%E4%B8%8E%E6%9C%80%E5%B7%A6%E5%89%8D%E7%BC%80.md)

## 07. 覆盖索引、回表与 ICP

**判定：边界知识**。PostgreSQL index-only scan/visibility map 不等同 MySQL ICP；需要实际 explain。

**工程证据：** [D3](../代码证据索引.md#d3)。缺陷编号见总报告。

**手册知识点：** 1. 先复习：为什么会回表；`Using index`；`Using index condition`；Q：什么是回表？；Q：什么是覆盖索引？；Q：ICP 有什么用？。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/04-mysql/docs/07-%E8%A6%86%E7%9B%96%E7%B4%A2%E5%BC%95-%E5%9B%9E%E8%A1%A8-ICP.md)

## 08. 索引“失效”与 Optimizer 成本选择

**判定：需改进**。过滤选择性与 HNSW 扫描同样重要；无法由有索引直接断言高效 F13。

**工程证据：** [R1](../代码证据索引.md#r1)。缺陷编号见总报告。

**手册知识点：** 1. 先把“索引失效”拆成三种情况；情况 A：Predicate 无法形成有效 Index Lookup / Range；情况 B：可以使用 Index，但使用程度有限；情况 C：Index technically 可用，但 Optimizer 认为别的方案更便宜；前缀固定；前导通配符；Q：常见索引失效场景有哪些？；Q：为什么低选择性字段可能不走索引？。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/04-mysql/docs/08-%E7%B4%A2%E5%BC%95%E5%A4%B1%E6%95%88%E4%B8%8EOptimizer.md)

## 09. EXPLAIN 与 Slow SQL 排查

**判定：需改进**。缺 EXPLAIN ANALYZE BUFFERS 和规模样本，无法证明慢 SQL 优化 F13。

**工程证据：** [R1](../代码证据索引.md#r1)。缺陷编号见总报告。

**手册知识点：** 1. EXPLAIN 到底是什么；`const`；`eq_ref`；`ref`；`range`；`index`；`ALL`；`possible_keys`；`key`；`Using index`；`Using index condition`；`Using where`；`Using filesort`；`Using temporary`；Step 1：先确认“慢”是真的慢；Step 2：拿完整 SQL + 参数；Step 3：看 Table / Index / Data Distribution；Step 4：EXPLAIN；Step 5：必要时 EXPLAIN ANALYZE；Step 6：确认是不是 Lock Wait；Step 7：确认是不是资源问题；Step 8：修改后重新验证；Q：你怎么排查 Slow SQL？；Q：看到 `type=ALL` 怎么办？；Q：`rows` 是实际扫描行数吗？。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/04-mysql/docs/09-EXPLAIN%E4%B8%8ESlowSQL.md)

## 10. 主键设计与索引生命周期

**判定：需改进**。业务 ID 与唯一约束已有；索引维护、膨胀和 vacuum 数据缺失。

**工程证据：** [D3](../代码证据索引.md#d3)。缺陷编号见总报告。

**手册知识点：** 1. 一个好主键通常希望具备什么；10.1 Selectivity 变化；10.2 Index Size 变大；10.3 Query 返回规模变大；10.4 Page Split / Fragmentation；10.5 Workload 改变；Q：为什么 InnoDB 常推荐自增主键？；Q：数据量增长后原来有用的 Index 为什么可能效果变差？。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/04-mysql/docs/10-%E4%B8%BB%E9%94%AE%E8%AE%BE%E8%AE%A1%E4%B8%8E%E7%B4%A2%E5%BC%95%E7%94%9F%E5%91%BD%E5%91%A8%E6%9C%9F.md)

## 11. ACID 与事务

**判定：基础具备**。事实+Outbox 同事务有价值；外部效果仍非数据库 ACID 的一部分。

**工程证据：** [D2](../代码证据索引.md#d2)。缺陷编号见总报告。

**手册知识点：** 1. 先讲人话：事务是在保护“一个业务动作的边界”；5.1 数据库内部约束；5.2 业务不变量；Q：ACID 分别是什么？MySQL 怎么实现？；Q：事务能保证业务绝对正确吗？。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/04-mysql/docs/11-ACID%E4%B8%8E%E4%BA%8B%E5%8A%A1.md)

## 12. 四种事务隔离级别

**判定：需改进**。需明确 PG 实际隔离级别及并发不变量；SQLite 测试不能证明行锁。

**工程证据：** [D3](../代码证据索引.md#d3)。缺陷编号见总报告。

**手册知识点：** 1. 先讲人话：隔离级别是在调“并发自由度”；2. InnoDB 的四种隔离级别；3.1 Dirty Read：脏读；3.2 Non-repeatable Read：不可重复读；3.3 Phantom Read：幻读；8.1 普通 Consistent Read；8.2 Locking Read；9.1 普通快照读；9.2 Locking Read / UPDATE / DELETE 范围操作；RC；RR 的普通一致性读；Q：MySQL 四种隔离级别是什么？；Q：RR 是否完全没有幻读？；继续学习；官方参考。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/04-mysql/docs/12-%E4%BA%8B%E5%8A%A1%E9%9A%94%E7%A6%BB%E7%BA%A7%E5%88%AB.md)

## 13. MVCC、Undo 与 ReadView

**判定：边界知识**。PG tuple/xmin/xmax/vacuum 对照 MySQL undo/read-view；必须说明实现不同。

**工程证据：** [D3](../代码证据索引.md#d3)。缺陷编号见总报告。

**手册知识点：** 1. 先讲人话：同一行可以有“历史版本”；情况 1：是我自己事务写的；情况 2：在我的 Snapshot 建立前已经提交；情况 3：Snapshot 建立时事务还活着；情况 4：Snapshot 建立以后才启动的新事务；REPEATABLE READ；READ COMMITTED；Q：MVCC 是什么？；Q：Undo Log 只用于 Rollback 吗？；Q：MVCC 为什么不能替代锁？；继续学习；官方参考。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/04-mysql/docs/13-MVCC-Undo-ReadView.md)

## 14. Record Lock、Gap Lock、Next-Key Lock 与 Deadlock

**判定：需改进**。FOR UPDATE SKIP LOCKED 已使用；lease 过期后的旧 owner 写回需 fencing F07。

**工程证据：** [D2](../代码证据索引.md#d2)。缺陷编号见总报告。

**手册知识点：** 1. 先讲人话：锁是在保护“当前世界”；Shared Lock（S）；Exclusive Lock（X）；15.1 固定访问顺序；15.2 缩短 Transaction；15.3 建正确 Index；15.4 不需要锁时不要 FOR UPDATE；15.5 Retry；Q：Record Lock、Gap Lock、Next-Key Lock 区别？；Q：怎么减少 Deadlock？；继续学习；官方参考。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/04-mysql/docs/14-%E9%94%81%E4%B8%8E%E6%AD%BB%E9%94%81.md)

## 15. redo、undo、binlog 与两阶段提交

**判定：边界知识**。PG WAL/备份恢复替代 MySQL redo-binlog 内部 2PC 论述；不是分布式 exactly-once。

**工程证据：** [O2](../代码证据索引.md#o2)。缺陷编号见总报告。

**手册知识点：** 1. 先看总图；Redo；Binlog；STATEMENT；ROW；MIXED；Q：redo、undo、binlog 有什么区别？；Q：为什么需要两阶段提交？；继续学习；官方参考。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/04-mysql/docs/15-%E6%97%A5%E5%BF%97%E4%B8%8E%E4%B8%A4%E9%98%B6%E6%AE%B5%E6%8F%90%E4%BA%A4.md)

## 16. Deep Pagination 与查询优化

**判定：需改进**。列表查询需稳定游标和大页计划；未建立深分页性能基线。

**工程证据：** [D3](../代码证据索引.md#d3)。缺陷编号见总报告。

**手册知识点：** 1. 先讲人话：OFFSET 不是“瞬移”；Q：为什么 `LIMIT 100000,20` 会慢？；Q：Cursor Pagination 的缺点？；继续学习；官方参考。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/04-mysql/docs/16-DeepPagination%E4%B8%8E%E6%9F%A5%E8%AF%A2%E4%BC%98%E5%8C%96.md)

## 17. Schema Design：从访问模式设计表

**判定：基础具备**。Turn/ToolCall/Interaction 等显式表优于单个万能 JSON；需统一 operation 边界 F16。

**工程证据：** [D3](../代码证据索引.md#d3)。缺陷编号见总报告。

**手册知识点：** 1. 先讲人话：先问“怎么用”，再问“怎么存”；ID；状态；时间；Q：你怎样设计一张业务表？；Q：为什么不能把 Agent 所有状态存一个 JSON？；继续学习。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/04-mysql/docs/17-SchemaDesign.md)

## 18. Replication 与读写分离

**判定：边界知识**。无读副本不扣实现分；如扩展需把审批/读后写留在主库并量化延迟。

**工程证据：** [D1](../代码证据索引.md#d1)。缺陷编号见总报告。

**手册知识点：** 1. 先讲人话：复制是在维护“同一份数据的多个副本”；Read Scale；Backup / Data Safety；Analytics；Geo Distribution；Failover 基础；6.1 刚写完的一段时间读 Source；6.2 关键读永远走 Source；6.3 等待 Replica 追到某个位置 / GTID；6.4 接受 Eventual Consistency；Q：MySQL 主从复制怎么工作？；Q：Replication 能不能当 Backup？；继续学习；官方参考。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/04-mysql/docs/18-Replication%E4%B8%8E%E8%AF%BB%E5%86%99%E5%88%86%E7%A6%BB.md)

## 19. Sharding：什么时候才需要分库分表

**判定：边界知识**。未达到分片必要性证据；先池预算与 SQL 计划，不能用分库掩盖阻塞。

**工程证据：** [D1](../代码证据索引.md#d1)。缺陷编号见总报告。

**手册知识点：** 1. 先讲人话：Sharding 是“把一份大数据拆开”；Range；Hash；分表；分库；Vertical；Horizontal；Q：什么时候需要分库分表？；Q：Sharding Key 怎么选？；继续学习。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/04-mysql/docs/19-Sharding.md)

## 20. CDC / Data Sync：把 MySQL 变化同步到下游

**判定：基础具备**。已有 transactional outbox；可解释为何当前不引入 CDC。

**工程证据：** [D2](../代码证据索引.md#d2)。缺陷编号见总报告。

**手册知识点：** 1. CDC 是什么；Q：CDC 是什么？；Q：为什么不用应用代码直接同时写 MySQL 和 Elasticsearch？；继续学习。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/04-mysql/docs/20-CDC%E4%B8%8E%E6%95%B0%E6%8D%AE%E5%90%8C%E6%AD%A5.md)

## 21. Bulk Write 与 MySQL Write Path

**判定：需改进**。向量 executemany/单文档原子替换已有；批大小/锁时长/导入吞吐待测。

**工程证据：** [R2](../代码证据索引.md#r2)。缺陷编号见总报告。

**手册知识点：** 1. 先讲人话：每次写入不是“只改一行”；Q：一亿条数据如何快速写入 MySQL？；继续学习。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/04-mysql/docs/21-BulkWrite%E4%B8%8E%E5%86%99%E5%85%A5%E8%B7%AF%E5%BE%84.md)

## 22. AI Application Data Modeling

**判定：基础具备**。SQL 事实、Redis 热事件、向量派生、记忆引用职责清楚。

**工程证据：** [M1](../代码证据索引.md#m1)。缺陷编号见总报告。

**手册知识点：** 1. 先讲人话：不是所有 AI 数据都应该存 Vector DB；结构化业务事实；高频临时状态；语义检索数据；当前状态表；事件 / Step 表；Q：为什么 Agent 项目里同时需要 MySQL、Redis、Vector DB？；Q：RAG 文档为什么还要存 MySQL？；继续学习。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/04-mysql/docs/22-AI%E5%BA%94%E7%94%A8%E6%95%B0%E6%8D%AE%E5%BB%BA%E6%A8%A1.md)

## 23. MySQL + Redis Consistency 的边界

**判定：不合格**。普通缓存可降级；撤销状态丢失不能用 TTL 或缓存一致性话术掩盖 F06。

**工程证据：** [S1](../代码证据索引.md#s1)。缺陷编号见总报告。

**手册知识点：** 1. 先讲人话：为什么有 MySQL 还要 Redis；Read；Write；Write-through；Write-behind / Write-back；Q：MySQL 和 Redis 如何保证一致性？；Q：为什么更新 DB 后删 Cache，而不是同时更新 Cache？；MySQL 主体完成；下一环。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/04-mysql/docs/23-MySQL-Redis%E4%B8%80%E8%87%B4%E6%80%A7%E8%BE%B9%E7%95%8C.md)
