# 10-system-design：逐章审查

全部 19 章均有映射。判定针对本项目当前实现；“基础具备”不等于生产验收通过，“边界知识”不要求增加相应技术栈。知识点提纲来自该章二级及三级标题，保留原手册链接供逐点追问；本表的工程判断聚焦章节在项目中的实际落点。

[总报告](../README.md) · [代码证据索引](../代码证据索引.md)

## 01｜System Design 的职责与完整答题框架

**判定：需改进**。有架构契约和纵向切片；缺数值化 workload/SLO 及本次发布证据。

**工程证据：** [O1](../代码证据索引.md#o1)。缺陷编号见总报告。

**手册知识点：** 1. 为什么这门课放在最后；Step 1：Clarify Requirement；Step 2：Define SLO / Constraint；Step 3：Estimate Order of Magnitude；Step 4：Define API / Data / State；Step 5：Draw Happy Path；Step 6：Find Bottleneck / Hot Path；Step 7：Break the System；Step 8：Verify；Functional；Non-functional。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/10-system-design/docs/01-SystemDesign%E8%81%8C%E8%B4%A3%E4%B8%8E%E7%AD%94%E9%A2%98%E6%A1%86%E6%9E%B6.md)

## 02｜Requirement、SLO、Constraint 与 Scope

**判定：需改进**。应定义接纳率、首事件/TTFT、任务完成率、取消/删除时限 F17。

**工程证据：** [O1](../代码证据索引.md#o1)。缺陷编号见总报告。

**手册知识点：** 1. Functional Requirement：系统必须做什么；SLI；SLO；SLA。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/10-system-design/docs/02-Requirement%E4%B8%8ESLO.md)

## 03｜Workload、Capacity、Hotspot 与数量级估算

**判定：不合格**。API/worker/线程池/DB/Redis/模型预算未统一 F09。

**工程证据：** [D1](../代码证据索引.md#d1)。缺陷编号见总报告。

**手册知识点：** 1. 先把“高并发”翻译成数字；Compute；Memory；Storage；Network。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/10-system-design/docs/03-Workload%E4%B8%8ECapacityEstimation.md)

## 04｜API、Data Model 与 State Ownership

**判定：基础具备**。Canonical facts、derived index、ephemeral events 有明确区分。

**工程证据：** [M1](../代码证据索引.md#m1)。缺陷编号见总报告。

**手册知识点：** 1. API 先表达业务，不要先暴露存储细节；Primary State；Derived State；Ephemeral State。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/10-system-design/docs/04-API%E6%95%B0%E6%8D%AE%E6%A8%A1%E5%9E%8B%E4%B8%8EStateOwnership.md)

## 05｜Sync / Async、Data Flow 与 State Machine

**判定：需改进**。正常链清楚；pending、失联、取消、未知副作用转移需故障覆盖 F03/F07。

**工程证据：** [A1](../代码证据索引.md#a1)。缺陷编号见总报告。

**手册知识点：** 1. Sync Path 解决“现在就要答案”；Command；Event。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/10-system-design/docs/05-DataFlow%E4%B8%8EStateMachine.md)

## 06｜Cache、Hot Path 与 Read / Write Path

**判定：需改进**。轻量 cache-aside 可解释；热 key 重建与 Redis 共故障需预算。

**工程证据：** [S2](../代码证据索引.md#s2)。缺陷编号见总报告。

**手册知识点：** 1. 先找 Hot Path；Penetration；Breakdown / Stampede；Avalanche。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/10-system-design/docs/06-Cache%E4%B8%8EHotPath.md)

## 07｜Partition、Routing、Fan-out 与 Rebalance

**判定：边界知识**。暂不分片；多意图 fanout 有上界，跨租户并发没有部署预算 F09。

**工程证据：** [D1](../代码证据索引.md#d1)。缺陷编号见总报告。

**手册知识点：** 1. 为什么要 Partition / Shard。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/10-system-design/docs/07-PartitionRouting%E4%B8%8EFanout.md)

## 08｜Consistency、Idempotency、Transaction 与 Compensation

**判定：不合格**。业务幂等基础强；auth 原子消费和 outbox stale writer 不闭合 F05/F07。

**工程证据：** [S1](../代码证据索引.md#s1)。缺陷编号见总报告。

**手册知识点：** 1. 先写业务 Invariant。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/10-system-design/docs/08-Consistency%E4%B8%8EIdempotency.md)

## 09｜Queue、Backpressure 与 Long-running Task

**判定：不合格**。没有独立排队期限/调度 lease；普通 pending 会被失联清扫 F03。

**工程证据：** [A1](../代码证据索引.md#a1)。缺陷编号见总报告。

**手册知识点：** 1. Queue 解决什么。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/10-system-design/docs/09-QueueBackpressure%E4%B8%8ELongRunningTask.md)

## 10｜Timeout、Retry、Failover、Degradation 与 Load Shedding

**判定：需改进**。局部超时与重试存在；无系统级过载模型和可验证故障恢复 F07/F08。

**工程证据：** [D1](../代码证据索引.md#d1)。缺陷编号见总报告。

**手册知识点：** 1. Timeout 是资源保护，不只是用户体验。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/10-system-design/docs/10-Reliability%E4%B8%8EOverload.md)

## 11｜Multi-tenancy、Security、Permission 与 Isolation

**判定：需改进**。共享表租户过滤可用；外部执行隔离、审计留存和删除策略待闭环 F15/F18。

**工程证据：** [S3](../代码证据索引.md#s3)。缺陷编号见总报告。

**手册知识点：** 1. Authentication 与 Authorization 要分清；Shared；Dedicated。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/10-system-design/docs/11-MultiTenancy%E4%B8%8ESecurity.md)

## 12｜Observability、Evaluation、Cost 与 Evolution

**判定：不合格**。缺可发布的新检索结果；场景清单和代码漂移 F11/F12。

**工程证据：** [Q2](../代码证据索引.md#q2)。缺陷编号见总报告。

**手册知识点：** 1. Observability 不等于“有日志”；Offline；Online。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/10-system-design/docs/12-ObservabilityEvaluation%E4%B8%8EEvolution.md)

## 13｜High-concurrency Transactional Systems：秒杀、库存、Rate Limit、Token Refresh

**判定：边界知识**。非秒杀/支付产品；转化为 ToolCall 唯一执行、审批 CAS 等业务不变量。

**工程证据：** [D3](../代码证据索引.md#d3)。缺陷编号见总报告。

**手册知识点：** 1. 共同抽象：Scarce Resource + Concurrent Contention；Strong Global Limit；Local Token Allocation；Redis 成功，DB 失败；DB 成功，Response 丢失；MQ 重复投递；Hot Key 过载；Worker 全挂。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/10-system-design/docs/13-HighConcurrencyTransactionalSystems.md)

## 14｜Realtime Read-heavy Systems：排行榜、Feed、Autocomplete、Notification

**判定：需改进**。SSE 与页面历史投影存在；大事件/慢读者/缓存过期重同步待验证 F04/F09。

**工程证据：** [A1](../代码证据索引.md#a1)。缺陷编号见总报告。

**手册知识点：** 1. 共同抽象：Read-heavy + Derived View；Fan-out on Write；Fan-out on Read。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/10-system-design/docs/14-RealtimeReadHeavySystems.md)

## 15｜Large-scale Data & Processing：10TB Storage、Migration、Dedup、Large-file

**判定：需改进**。文档摄取/重建有流程；大批次 checkpoint、恢复成本和吞吐需测。

**工程证据：** [R2](../代码证据索引.md#r2)。缺陷编号见总报告。

**手册知识点：** 1. 第一原则：不要把整个数据集当一个任务；Migration Worker 崩溃；Batch 重试；Upload 某 Part 丢失；Processing 失败；Source 继续更新。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/10-system-design/docs/15-LargeScaleDataProcessingSystems.md)

## 16｜LLM Gateway 与 Multi-tenant AI Platform

**判定：需改进**。多模型适配有基础；缺部署配额/价格账本/总成本限制 F08。

**工程证据：** [A4](../代码证据索引.md#a4)。缺陷编号见总报告。

**手册知识点：** 1. 为什么需要 LLM Gateway；Provider 429；Provider A outage；Streaming client disconnect；Tenant runaway Agent；Usage service temporarily down。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/10-system-design/docs/16-LLMGateway%E4%B8%8EMultiTenantAIPlatform.md)

## 17｜Enterprise / Large-scale RAG System Design

**判定：需改进**。可作为个人知识检索基础；企业 ACL 分级、在线代际切换和规模尚未证明。

**工程证据：** [R3](../代码证据索引.md#r3)。缺陷编号见总报告。

**手册知识点：** 1. 先定义 Scope；Embedding Provider 429；New Generation 构建一半失败；ACL 改了；Rerank down；Vector DB partial shard failure。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/10-system-design/docs/17-EnterpriseRAGSystemDesign.md)

## 18｜Production Agent Backend 与 Long-running Agent

**判定：不合格**。已有核心 harness；生产恢复、资源与验证控制面未达标 F02/F03/F07。

**工程证据：** [A2](../代码证据索引.md#a2)。缺陷编号见总报告。

**手册知识点：** 1. 先定义 Run 是什么。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/10-system-design/docs/18-ProductionAgentBackend.md)

## 19｜Vertical AI Agent Patterns：Analysis、Customer Service、Multimodal、Game、Content

**判定：需改进**。职业事实→确认→操作→验证→记忆链有基础；需要完整真实用户旅程验收。

**工程证据：** [M1](../代码证据索引.md#m1)。缺陷编号见总报告。

**手册知识点：** 1. 垂直 Agent 的共同框架。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/10-system-design/docs/19-VerticalAIAgentPatterns.md)
