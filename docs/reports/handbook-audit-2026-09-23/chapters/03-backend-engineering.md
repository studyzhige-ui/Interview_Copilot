# 03-backend-engineering：逐章审查

全部 22 章均有映射。判定针对本项目当前实现；“基础具备”不等于生产验收通过，“边界知识”不要求增加相应技术栈。知识点提纲来自该章二级及三级标题，保留原手册链接供逐点追问；本表的工程判断聚焦章节在项目中的实际落点。

[总报告](../README.md) · [代码证据索引](../代码证据索引.md)

## 01. AI Backend Engineering 的职责与完整 Request Path

**判定：需改进**。主链可追踪；失败链跨 API/队列/事件/数据库仍有断口 F03/F04。

**工程证据：** [D1](../代码证据索引.md#d1)。缺陷编号见总报告。

**手册知识点：** 1. 从“一个接口”到“一个生产服务”；2. 一次请求到底经过哪些层；3. 四类资源；3.1 Compute；3.2 Memory；3.3 Connection；3.4 Downstream Capacity；4. 三种工作类型；同步短请求；Streaming 请求；Long-running Task；5. State Ownership；一个常见反例；6. Normal Path 之后必须画 Failure Path；7. AI Backend 的特殊点；长尾延迟明显；Streaming 常见；外部依赖多；成本本身是资源；Side Effect 更复杂；8. 最小 Production Checklist；9. 🎯 面试怎么答；10. ⚠️ 易错点；11. 本章自测。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/03-backend-engineering/docs/01-AIBackend%E8%81%8C%E8%B4%A3%E4%B8%8ERequestPath.md)

## 02. TCP、TLS 与 HTTP/1.1 / HTTP/2 / HTTP/3

**判定：边界知识**。nginx HTTP/1.1、TLS 外部终止；TCP/TLS/QUIC 是解释边界，不要求自研。

**工程证据：** [D1](../代码证据索引.md#d1)。缺陷编号见总报告。

**手册知识点：** 1. 先看一条完整链路；2. DNS 解决什么；3. TCP vs UDP；4. TCP 三次握手为什么不是两次；5. TCP Reliable Delivery；Retransmission；6. 四次挥手与半关闭；7. TLS 解决什么；8. 对称加密与非对称加密怎样协作；9. Certificate Trust Chain；10. HTTP/1.1；11. HTTP/2；12. HTTP/3 / QUIC；13. AI Streaming 为什么关心 HTTP Version；14. Keep-Alive 的意义；15. Failure Timeline；16. 🎯 面试怎么答；17. ⚠️ 易错点；18. 本章自测。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/03-backend-engineering/docs/02-TCPTLS%E4%B8%8EHTTPVersions.md)

## 03. HTTP / RPC / MQ 与 Streaming Reliability

**判定：需改进**。durable Turn≠SSE 已体现；Redis 故障与游标裁剪仍需重同步协议 F04。

**工程证据：** [A1](../代码证据索引.md#a1)。缺陷编号见总报告。

**手册知识点：** 1. 三种通信不是互相替代；2. 同步调用什么时候最自然；3. RPC / gRPC 为什么存在；4. 为什么需要 MQ；5. Streaming Transport：SSE vs WebSocket；SSE；WebSocket；6. Streaming Connection ≠ Durable Run；7. Heartbeat 解决什么；8. Reconnect 与 Resume 是两件事；9. Resume 的前提：事件必须有稳定身份；10. Ordering 问题；11. Duplicate Event；12. Error Contract；13. HTTP / RPC / MQ 如何一起用；14. 🎯 面试怎么答；15. ⚠️ 易错点；16. 本章自测。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/03-backend-engineering/docs/03-ServiceCommunication%E4%B8%8EStreamingReliability.md)

## 04. Concurrency Execution Model：Process / Thread / Coroutine / Thread Pool

**判定：不合格**。线程池、loop、异步池生命周期不统一 F02。

**工程证据：** [P3](../代码证据索引.md#p3)。缺陷编号见总报告。

**手册知识点：** 1. Concurrency 与 Parallelism；Concurrency；Parallelism；2. Process、Thread、Coroutine 放到 Service 里看；Process；Thread；Coroutine；3. 为什么“10000 个 Coroutine”仍可能拖死系统；4. Thread Pool 的核心模型；Queue 无限长有什么问题；5. Thread Pool Size 怎样思考；CPU-heavy；I/O-heavy；6. Reject Policy 为什么重要；7. Process Pool 的边界；8. Async + Sync SDK 怎样共存；9. Worker Process 与 Pool 的乘法效应；10. AI 场景：并发调用多个 Tool；11. Failure Timeline；12. 🎯 面试怎么答；13. ⚠️ 易错点；14. 本章自测。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/03-backend-engineering/docs/04-Concurrency%E4%B8%8EThreadPool.md)

## 05. Connection Pool 与 Resource Capacity

**判定：不合格**。只按 API worker 算连接未覆盖整个进程舰队与阻塞 SSE F09。

**工程证据：** [P3](../代码证据索引.md#p3)。缺陷编号见总报告。

**手册知识点：** 1. 为什么需要 Connection Pool；2. Pool 不只是“缓存连接”；3. 常见 Pool；4. Pool 的几个关键参数；Max Size；Acquire Timeout；Idle Timeout；Max Lifetime；5. Pool Size 不是越大越好；6. Little's Law 的直觉；7. Pool Exhaustion 的典型症状；8. Connection Leak；9. HTTP Connection Pool；10. HTTP Pool 还有一个特别风险；11. Pool Waiting vs Request Deadline；12. 多 Worker 的 Pool Multiplication；13. Pool 与 Semaphore 的区别；14. AI 场景：Provider Capacity；15. 🎯 面试怎么答；16. ⚠️ 易错点；17. 本章自测。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/03-backend-engineering/docs/05-ConnectionPool%E4%B8%8EResourceCapacity.md)

## 06. Backpressure、Concurrency Limit、Rate Limit 与 Load Shedding

**判定：需改进**。有限频无全局并发/队列入场预算；过载会变成 pending 失败 F03/F08。

**工程证据：** [S2](../代码证据索引.md#s2)。缺陷编号见总报告。

**手册知识点：** 1. Backpressure 是什么；2. 四种最常见的手段；Bound Queue；Concurrency Limit；Rate Limit；Load Shedding；3. Concurrency Limit vs Rate Limit；Concurrency Limit；Rate Limit；4. Fixed Window；5. Sliding Window；6. Token Bucket；7. Leaky Bucket；8. Multi-tenant Rate Limit；9. Queue 应该有多长；10. Load Shedding 为什么是保护机制；11. Degradation；12. Request Coalescing；13. Adaptive Concurrency；14. Retry 与 Backpressure 的冲突；15. AI 场景：Tool Fan-out；16. Metrics；17. 🎯 面试怎么答；18. ⚠️ 易错点；19. 本章自测。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/03-backend-engineering/docs/06-Backpressure%E4%B8%8ERateLimit.md)

## 07. Timeout、Deadline 与 Error Taxonomy

**判定：需改进**。有阶段 timeout；缺总 deadline 与真实可中止 worker F07/F08。

**工程证据：** [A3](../代码证据索引.md#a3)。缺陷编号见总报告。

**手册知识点：** 1. 为什么所有远程调用都需要 Timeout；2. Timeout 有很多层；Connect Timeout；Read Timeout；Pool Acquire Timeout；End-to-End Deadline；3. Timeout vs Deadline；4. Timeout Budget；5. Streaming 的 Timeout 更复杂；6. Error Taxonomy 为什么比 Exception 名字重要；Transient；Permanent；Permission / Auth；Business Rejection；Rate Limit / Overload；7. Unknown Outcome；8. Timeout 不等于 Cancellation；9. Timeout 过短也会制造事故；10. Timeout 过长的代价；11. Error Contract；12. AI 场景：RAG 请求预算；13. Metrics；14. 🎯 面试怎么答；15. ⚠️ 易错点；16. 本章自测。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/03-backend-engineering/docs/07-TimeoutDeadline%E4%B8%8EErrorTaxonomy.md)

## 08. Retry、Backoff、Circuit Breaker、Degradation 与 Failover

**判定：需改进**。SDK 重试关闭、调用层恢复较清楚；未见生产熔断/故障切换演练 F17。

**工程证据：** [A4](../代码证据索引.md#a4)。缺陷编号见总报告。

**手册知识点：** 1. 先问：这个错误值得 Retry 吗；可能适合 Retry；通常不应该 Retry；2. 为什么立即 Retry 很危险；3. Exponential Backoff；4. Jitter；5. Retry Budget；6. 只在一层 Retry；7. Retry 必须和 Idempotency 配合；8. Circuit Breaker；Closed；Open；Half-open；9. Circuit Breaker 不是万能；10. Degradation；11. Fallback；12. Failover；13. Hedged Request；14. AI Provider Failure Chain；15. Metrics；16. 🎯 面试怎么答；17. ⚠️ 易错点；18. 本章自测。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/03-backend-engineering/docs/08-RetryCircuitBreaker%E4%B8%8EFailover.md)

## 09. Production API、Idempotency 与 Side Effect Safety

**判定：不合格**。业务幂等已有；refresh check-then-set 不是原子消费 F05。

**工程证据：** [S1](../代码证据索引.md#s1)。缺陷编号见总报告。

**手册知识点：** 1. 先区分 Read 与 Side Effect；2. HTTP Method 的 Idempotent 语义；3. Idempotency 的核心定义；4. Idempotency Key；5. 为什么要校验 Request Fingerprint；6. Idempotency Record 的状态机；7. Idempotency 与并发重复请求；8. Exactly-once 为什么很难；9. Unknown Outcome 的处理；10. Idempotency Key 谁生成；Client-generated；Server-generated Operation ID；11. API Versioning；12. Error Contract 与 Idempotency；13. Agent Tool Side Effect；14. Idempotency 和 Distributed Lock 的区别；15. Result Retention；16. Metrics；17. 🎯 面试怎么答；18. ⚠️ 易错点；19. 本章自测。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/03-backend-engineering/docs/09-APIIdempotency%E4%B8%8ESideEffect.md)

## 10. 为什么需要 MQ：Delivery Semantics 与 Failure Model

**判定：需改进**。Celery late ack 是至少一次；Outbox lease 和外部 receipt 才决定幂等 F07。

**工程证据：** [D2](../代码证据索引.md#d2)。缺陷编号见总报告。

**手册知识点：** 1. 没有 MQ 会怎样；2. MQ 提供什么能力；3. Producer / Broker / Consumer 三段 Failure；Producer Failure；Broker Failure；Consumer Failure；4. At-most-once；5. At-least-once；6. Exactly-once 为什么要说边界；7. Ack 是什么意思；8. Dead Letter Queue；9. Ordering；10. Backlog；11. MQ vs Database Polling；12. MQ vs Redis Stream；13. AI 场景：Ingestion；14. AI 场景：Agent Tool Async Job；15. Retry 谁负责；16. 🎯 面试怎么答；17. ⚠️ 易错点；18. 本章自测。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/03-backend-engineering/docs/10-MQ%E4%B8%8EDeliverySemantics.md)

## 11. Kafka：Partition、Consumer Group、Ordering 与 Backlog

**判定：边界知识**。未使用 Kafka；解释 Celery Redis 的积压、可见性与投递语义即可。

**工程证据：** [D2](../代码证据索引.md#d2)。缺陷编号见总报告。

**手册知识点：** 1. Kafka 的核心抽象；2. 为什么需要 Partition；3. Key 决定局部顺序；4. Consumer Group；5. 不同 Consumer Group；6. Offset；先 Commit Offset，再处理；先处理，再 Commit Offset；7. Rebalance；8. Backlog / Consumer Lag；9. Backlog 排查；10. Hot Partition；11. Partition 数不是随便越多越好；12. Ordering 与 Retry；13. Replay；14. AI 场景：Embedding Pipeline；15. 当前 Kafka 机制不要写死成旧版本；16. Metrics；17. 🎯 面试怎么答；18. ⚠️ 易错点；19. 本章自测。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/03-backend-engineering/docs/11-KafkaPartition%E4%B8%8EBacklog.md)

## 12. Reliable Async Task：Outbox、Lease、Heartbeat、Worker Recovery 与 Long-running API

**判定：不合格**。queued/pending 与 running lease 混为同一 stale 条件 F03。

**工程证据：** [A1](../代码证据索引.md#a1)。缺陷编号见总报告。

**手册知识点：** 1. 为什么 Background Task 不够；2. Reliable Task Pattern；3. Task State Machine；4. Task Record 至少保存什么；5. 为什么 MQ 只传 task_id 很常见；6. Outbox Problem；7. Claim 与 Lease；8. Heartbeat；9. Reclaim 的重复执行问题；10. Fencing Token 的直觉；11. Long-running API；12. Cancellation；13. Retry Strategy；14. Progress；15. 大文件 Ingestion；16. Task Version / Processing Version；17. Metrics；18. 🎯 面试怎么答；19. ⚠️ 易错点；20. 本章自测。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/03-backend-engineering/docs/12-ReliableAsyncTask.md)

## 13. 最终一致性、DB + Cache、Outbox、Saga 与 Compensation

**判定：需改进**。Outbox 与规范事实发布方向正确；旧 worker 写回仍缺 owner CAS F07。

**工程证据：** [D2](../代码证据索引.md#d2)。缺陷编号见总报告。

**手册知识点：** 1. 为什么会有最终一致性；2. DB + Cache 的经典问题；3. 为什么“先删 Cache 再写 DB”也不完美；4. 常见策略：DB 先写，Cache 后删；5. 延迟双删为什么不是万能答案；6. Event-driven Invalidation；7. Versioned Cache；8. 最终一致性不是“迟早会一致”；9. Compensation；10. Saga 思想；11. Compensation 不是反向 SQL；12. Agent Tool 的部分成功；13. Reconciliation；14. Cache Consistency 的验证；15. Metrics；16. 🎯 面试怎么答；17. ⚠️ 易错点；18. 本章自测。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/03-backend-engineering/docs/13-Consistency%E4%B8%8ECompensation.md)

## 14. Data Layering 与 State Ownership：MySQL / Redis / Session / Runtime State

**判定：基础具备**。事实/派生索引/热事件/长期记忆已有边界；拒绝把 Redis 当唯一事实。

**工程证据：** [M1](../代码证据索引.md#m1)。缺陷编号见总报告。

**手册知识点：** 1. 不同存储不是“谁快用谁”；2. Source of Truth；3. MySQL 适合什么；4. Redis 适合什么；5. Session State；6. Sticky Session 的边界；7. Runtime State vs Business State；Business State；Runtime State；8. Cache State；9. Derived State；10. State Lifetime；11. Multi-tenant Key Design；12. Data Layering Example；13. Failure Recovery；14. 🎯 面试怎么答；15. ⚠️ 易错点；16. 本章自测。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/03-backend-engineering/docs/14-DataLayering%E4%B8%8EStateOwnership.md)

## 15. Authentication、Authorization、Session 与 Multi-tenant Boundary

**判定：不合格**。用户身份稳定主键正确；session 撤销与旋转可靠性不合格 F05/F06。

**工程证据：** [S1](../代码证据索引.md#s1)。缺陷编号见总报告。

**手册知识点：** 1. Authentication vs Authorization；Authentication；Authorization；2. Access Token 与 Refresh Token；3. JWT 不等于“Authentication System”；4. Stateless Token 的 Trade-off；5. Server-side Session；6. OAuth2 应该掌握到什么程度；7. API Key；8. RBAC；9. ABAC / Policy；10. Permission 必须在 Server 执行；11. Multi-tenant Context；12. Background Task 的身份问题；13. Token Refresh Race；14. Session Routing；15. AI 场景：RAG Permission；16. AI 场景：Agent Tool Approval；17. Metrics / Audit；18. 🎯 面试怎么答；19. ⚠️ 易错点；20. 本章自测。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/03-backend-engineering/docs/15-AuthSession%E4%B8%8ETenantBoundary.md)

## 16. Service Discovery、Load Balancing、Stateless Routing 与 Distributed ID

**判定：边界知识**。单机 Compose DNS 与 nginx 足够当前形态；未证明跨机自动发现/扩缩容。

**工程证据：** [D1](../代码证据索引.md#d1)。缺陷编号见总报告。

**手册知识点：** 1. 单实例时代没有“发现”问题；2. Service Discovery 的基本问题；3. DNS Discovery；4. Registry + Heartbeat；5. Load Balancing；6. Client-side vs Server-side LB；Server-side / Proxy；Client-side；7. Health 与 Routing；8. Stateless Service；9. Sticky Session；10. Consistent Hashing；11. Global Unique ID 为什么不总用自增；12. UUID；13. Snowflake 思想；14. ID 的真正需求；15. AI 场景：Run ID / Event ID / Task ID；16. Failure Timeline；17. 🎯 面试怎么答；18. ⚠️ 易错点；19. 本章自测。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/03-backend-engineering/docs/16-ServiceDiscovery%E4%B8%8ELoadBalancing.md)

## 17. Observability、SLO 与 Performance Diagnosis

**判定：需改进**。有请求和工具日志；缺队列等待/loop lag/池等待及分位数门禁 F17。

**工程证据：** [O1](../代码证据索引.md#o1)。缺陷编号见总报告。

**手册知识点：** 1. 三类核心 Signal；Metric；Log；Trace；2. Structured Logging；3. Request ID vs Trace ID；Request ID；Trace ID；4. Span；5. Metrics：平均值为什么不够；6. RED / USE 思想；7. AI-specific Metrics；8. SLI / SLO；SLI；SLO；9. Error Budget；10. Performance Diagnosis：从总延迟拆阶段；11. Pool / Queue / Downstream 联动；12. Distributed Trace 的 Context Propagation；13. Sampling；14. Log 中不能放什么；15. Performance Regression；16. AI Bad Case 与 Backend Trace；17. 🎯 面试怎么答；18. ⚠️ 易错点；19. 本章自测。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/03-backend-engineering/docs/17-Observability%E4%B8%8EPerformanceDiagnosis.md)

## 18. Linux Process / CPU / Memory / Disk / Port Troubleshooting

**判定：需改进**。有 smoke/drill/backup 脚本；缺与实际部署绑定的 OOM/FD/磁盘演练记录。

**工程证据：** [O2](../代码证据索引.md#o2)。缺陷编号见总报告。

**手册知识点：** 1. 先确认问题范围；2. 先看进程还活着吗；3. CPU 高怎么办；4. Load Average；5. Memory 高；6. OOM；7. Memory Leak vs High Working Set；Leak；High Working Set；8. Disk 问题；9. Deleted but Open File；10. Port / Connection；11. File Descriptor；12. Network 排查；13. Process / Thread 数异常；14. Container 里的“机器资源”；15. 最近变更优先；16. AI 场景：P99 突然升高；17. 常见命令不是知识点本身；18. 🎯 面试怎么答；19. ⚠️ 易错点；20. 本章自测。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/03-backend-engineering/docs/18-LinuxTroubleshooting.md)

## 19. Docker、Kubernetes、Health Check、Graceful Shutdown 与 Horizontal Scaling

**判定：需改进**。队列按负载隔离有价值；无资源限制、worker health 与强制终止证据 F07/F09。

**工程证据：** [D1](../代码证据索引.md#d1)。缺陷编号见总报告。

**手册知识点：** 1. Container 解决什么；2. Image 与 Container；3. 一个 Container 里到底跑几个进程；4. Kubernetes 解决什么；5. Pod / Deployment / Service；Pod；Deployment；Service；6. Startup / Liveness / Readiness；Startup；Liveness；Readiness；7. 为什么 Liveness 不能乱写；8. Readiness 不应该无脑依赖所有下游；9. Graceful Shutdown；10. Connection Draining；11. Horizontal Scaling；12. HPA 的直觉；13. Resource Request / Limit；14. Rolling Update；15. AI 场景：Model Client Warmup；16. AI 场景：Long-running Worker；17. Metrics；18. 🎯 面试怎么答；19. ⚠️ 易错点；20. 本章自测。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/03-backend-engineering/docs/19-ContainerK8s%E4%B8%8EDeployment.md)

## 20. Configuration、Feature Flag、Gray Release 与 Microservice Evolution

**判定：需改进**。generation fingerprint 很好；切换依赖维护窗口，需发布/回滚验收 F10/F12。

**工程证据：** [R3](../代码证据索引.md#r3)。缺陷编号见总报告。

**手册知识点：** 1. 为什么 Configuration 需要治理；2. Config Priority；3. Dynamic Config；4. Safe Config Update；5. Config Version；6. Feature Flag；7. Feature Flag 的 Debt；8. Gray / Canary Release；9. Rollback 不是永远简单；10. Monolith vs Microservice；11. 什么时候拆服务；12. DDD 的价值边界；13. Gateway；14. Microservice Communication；15. Distributed Transaction；16. AI Config 特别容易造成 Silent Regression；17. Kill Switch；18. 🎯 面试怎么答；19. ⚠️ 易错点；20. 本章自测。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/03-backend-engineering/docs/20-ConfigRelease%E4%B8%8EServiceEvolution.md)

## 21. Backend Security：SSRF / CSRF / SQLi / XSS / Secret / Trust Boundary

**判定：需改进**。SSRF/secret redaction/MCP 环境白名单已做；不等于操作系统沙箱 F18。

**工程证据：** [S3](../代码证据索引.md#s3)。缺陷编号见总报告。

**手册知识点：** 1. 先画 Trust Boundary；2. SQL Injection；3. XSS；4. CSRF；5. SSRF；6. SSRF 防护；7. Secret Management；8. Secret Lifecycle；9. Log Redaction；10. Reverse Shell / Command Injection；11. Container Escape 的直觉；12. Least Privilege；13. Input Boundary；14. Output Boundary；15. Multi-tenant Security；16. AI 场景：Prompt Injection 进入 Backend；17. Security Failure 要可观测；18. 🎯 面试怎么答；19. ⚠️ 易错点；20. 本章自测。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/03-backend-engineering/docs/21-BackendSecurity.md)

## 22. Spring / JVM / Java Concurrency / Go Runtime：跨语言 Backend Primitive 映射

**判定：边界知识**。Java AQS/JVM、Go GMP 不要求落地；以本项目进程/线程/loop 对照说明。

**工程证据：** [P3](../代码证据索引.md#p3)。缺陷编号见总报告。

**手册知识点：** 1. 为什么单独放一章，而不是散到主线里；2. Dependency Injection：FastAPI Depends vs Spring DI；3. Spring Bean Lifecycle 的面试层次；4. AOP / Proxy 映射到什么；5. Java `synchronized` / ReentrantLock / CAS；synchronized；ReentrantLock；CAS；6. AQS 的学习边界；7. Concurrent Collection；8. HashMap：为什么和 Python dict 不能完全类比；9. ThreadLocal；10. JVM Memory Area；11. GC；12. JVM OOM / Memory Leak 排查；13. Go Goroutine；14. GMP 的直觉；15. Channel；16. Go Mutex vs Channel；17. Cross-language Mapping Table；18. 为什么这组市场信号仍要保留；19. 🎯 面试怎么答；20. ⚠️ 易错点；21. 本章自测。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/03-backend-engineering/docs/22-CrossLanguageRuntimeMapping.md)
