# 05-redis：逐章审查

全部 24 章均有映射。判定针对本项目当前实现；“基础具备”不等于生产验收通过，“边界知识”不要求增加相应技术栈。知识点提纲来自该章二级及三级标题，保留原手册链接供逐点追问；本表的工程判断聚焦章节在项目中的实际落点。

[总报告](../README.md) · [代码证据索引](../代码证据索引.md)

## 01｜Redis 在 AI Application 中负责什么

**判定：需改进**。Redis 同时承载 broker/结果/缓存/撤销/SSE；故障域需分层 F09。

**工程证据：** [S2](../代码证据索引.md#s2)。缺陷编号见总报告。

**手册知识点：** 1. 先从一个真实 AI Application 看起；4.1 Cache；4.2 Session；4.3 Counter / Rate Limit；4.4 Temporary Runtime State；4.5 Lock / Coordination Helper；5.1 长期唯一业务真相；5.2 大量冷数据；5.3 复杂关系查询；5.4 语义近邻搜索；Q：为什么 Agent 项目里同时有 MySQL 和 Redis？；Q：为什么不能全部放 Redis？。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/05-redis/docs/01-Redis%E5%9C%A8AI%E5%BA%94%E7%94%A8%E4%B8%AD%E7%9A%84%E8%81%8C%E8%B4%A3.md)

## 02｜Keyspace、Command 与 Redis 基本执行模型

**判定：基础具备**。key 有业务前缀；需补 tenant、generation、TTL、最大字节与owner清单。

**工程证据：** [S2](../代码证据索引.md#s2)。缺陷编号见总报告。

**手册知识点：** 1. Redis 的最小模型；Q：Redis 单个命令为什么通常具有原子性？；Q：为什么不要在生产上随便 KEYS *？。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/05-redis/docs/02-Keyspace%E4%B8%8ECommand%E6%A8%A1%E5%9E%8B.md)

## 03｜String / Hash / List / Set / ZSet

**判定：基础具备**。String 缓存/黑名单、Stream 事件、List 取消分别有用途。

**工程证据：** [A1](../代码证据索引.md#a1)。缺陷编号见总报告。

**手册知识点：** 1. 总体对比；2.1 Counter；2.2 条件写；2.3 适合 Cache；3.1 Hash vs JSON String；4.1 List 的优势；4.2 List 不是通用 MQ；6.1 为什么 ZSet 很重要；Session；Conversation 最近消息；Tenant 可用 Tool 集合；Rate Limit 滑动窗口；Model Usage Counter；Q：Redis 五种常见数据结构分别适合什么？；Q：Hash 一定比 JSON String 好吗？。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/05-redis/docs/03-%E6%A0%B8%E5%BF%83%E6%95%B0%E6%8D%AE%E7%BB%93%E6%9E%84.md)

## 04｜Bitmap / Bitfield / HyperLogLog / Geo / Stream

**判定：边界知识**。没有 Bitmap/HLL 不构成缺陷；按实际去重/统计需求选择。

**工程证据：** [S2](../代码证据索引.md#s2)。缺陷编号见总报告。

**手册知识点：** 1. Bitmap：用 Bit 表示大量布尔状态；HyperLogLog；Bitmap；Stream；Q：Redis 除了五种常见数据结构还有什么？。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/05-redis/docs/04-%E6%89%A9%E5%B1%95%E6%95%B0%E6%8D%AE%E7%BB%93%E6%9E%84.md)

## 05｜底层编码与内存效率

**判定：需改进**。Stream maxlen 只限制条数，不限制大工具结果字节 F09。

**工程证据：** [A1](../代码证据索引.md#a1)。缺陷编号见总报告。

**手册知识点：** 1. 逻辑类型 ≠ 唯一底层结构；7.1 一个 String 非常大；7.2 一个集合元素很多；Q：ZSet 底层是不是跳表？；Q：为什么 Redis 一个很小的业务对象也会有额外内存开销？。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/05-redis/docs/05-%E5%BA%95%E5%B1%82%E7%BC%96%E7%A0%81%E4%B8%8E%E5%86%85%E5%AD%98%E6%A8%A1%E5%9E%8B.md)

## 06｜Redis Runtime 与性能模型：为什么快、Event Loop 与阻塞边界

**判定：不合格**。阻塞 XREAD/BLPOP 消耗连接；异步客户端跨 loop 是关键风险 F02/F09。

**工程证据：** [P3](../代码证据索引.md#p3)。缺陷编号见总报告。

**手册知识点：** 1. 先讲人话：Redis 快，不代表每条命令都快；2. Redis 快的几个主要原因；2.1 Memory-first；2.2 Server-side Data Structures；2.3 主执行路径简单；3. “Redis 单线程”到底是什么意思；4. 为什么大量连接不需要“一连接一线程”；5. I/O Multiplexing 解决的到底是什么；6. Event Loop 怎么理解；7. select / poll / epoll 学到什么深度；8. Reactor 与 Redis 的关系；9. 为什么慢命令会破坏低延迟；10. 现代 Redis 的 I/O Threads 怎么理解；11. RTT 为什么会成为瓶颈；12. AI Application 中为什么要懂这个 Runtime；Session / Conversation；Streaming；Big Tool Result / Large State；13. 常见错误；错误 1：Redis 快是因为单线程；错误 2：单线程就不能处理很多连接；错误 3：I/O Multiplexing 会让慢命令并行执行；错误 4：有 I/O Thread 以后 Redis 就变成普通多线程数据库；14. 面试怎么答；Q：Redis 为什么快？；Q：I/O Multiplexing 为什么适合 Redis？；Q：Redis 是单线程吗？；15. 章节自测。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/05-redis/docs/06-RedisRuntime%E4%B8%8E%E6%80%A7%E8%83%BD%E6%A8%A1%E5%9E%8B.md)

## 07｜TTL 与过期删除

**判定：需改进**。xadd+expire、lpush+expire 非原子；崩溃窗口可留下无 TTL key。

**工程证据：** [A1](../代码证据索引.md#a1)。缺陷编号见总报告。

**手册知识点：** 1. TTL 是什么；Fixed；Sliding；Conversation Hot State；Agent Run Lease；Semantic Cache；Q：Redis 过期删除怎么实现？；Q：为什么 Cache TTL 要加随机值？。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/05-redis/docs/07-TTL%E4%B8%8E%E8%BF%87%E6%9C%9F%E5%88%A0%E9%99%A4.md)

## 08｜maxmemory、Eviction 与内存压力

**判定：需改进**。Compose AOF 已启用，但未定义 maxmemory/关键状态淘汰策略 F09。

**工程证据：** [D1](../代码证据索引.md#d1)。缺陷编号见总报告。

**手册知识点：** 1. 为什么需要 maxmemory；3.1 淘汰所有 Key；3.2 只在带 TTL 的 Key 中淘汰；LRU；LFU；纯 Cache；Redis 同时存 Cache + 关键非缓存状态；Q：Redis 内存淘汰策略有哪些？怎么选？；Q：LRU 和 LFU 有什么差别？。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/05-redis/docs/08-Eviction%E4%B8%8E%E5%86%85%E5%AD%98%E7%AE%A1%E7%90%86.md)

## 09｜Cache 设计与故障模式：Key、TTL、Cache Aside、穿透、击穿与雪崩

**判定：需改进**。cache-aside 有降级，无 singleflight/抖动；限于当前轻量缓存才合理。

**工程证据：** [S2](../代码证据索引.md#s2)。缺陷编号见总报告。

**手册知识点：** 1. 为什么需要 Cache；2. 先区分 Source of Truth 和 Cache；3. Cache Aside 是最常见心智模型；Read Path；Write Path；4. Key Design 是 Cache Design 的一部分；5. TTL 不是“随便设 30 分钟”；高频、重建昂贵的数据；强时效数据；低频数据；6. Cache Penetration：查询的东西根本不存在；常见治理；7. Cache Breakdown / Stampede：一个热点 Key 突然失效；治理思路；8. Cache Avalanche：大量缓存同时失效或缓存层整体不可用；8.1 大量 Key 同时过期；8.2 Redis 整体故障；9. 三种故障怎么快速区分；10. Cache Warmup 与 Rebuild；11. Multi-tenant Cache 的额外风险；12. 缓存什么，不缓存什么；13. AI Application 场景；Model Configuration；User / Tenant Configuration；RAG Result Cache；Tool Result Cache；14. 常见错误；错误 1：Cache Hit Rate 越高越好；错误 2：所有 Key 都设同一个 TTL；错误 3：缓存穿透只靠 Bloom Filter；错误 4：缓存击穿就加分布式锁；错误 5：Redis 挂了就直接回源数据库；15. 面试怎么答；Q：缓存穿透、击穿、雪崩有什么区别？；Q：TTL 怎么设计？；Q：Redis 故障后为什么不能无脑回源数据库？；16. 章节自测。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/05-redis/docs/09-Cache%E8%AE%BE%E8%AE%A1%E4%B8%8E%E7%BC%93%E5%AD%98%E6%95%85%E9%9A%9C.md)

## 10｜BigKey 与 HotKey

**判定：需改进**。工具大事件可能形成大 Stream；需每租户字节限制及热点观测 F09。

**工程证据：** [A1](../代码证据索引.md#a1)。缺陷编号见总报告。

**手册知识点：** 1. 什么叫 BigKey；2.1 大响应；2.2 高复杂度命令；2.3 删除成本；2.4 Replication / Migration；4.1 大 Hash 按桶拆；4.2 大时间序列按时间分桶；4.3 大 List / ZSet 按业务维度拆；8.1 Local Cache；8.2 Replica Read；8.3 Key Sharding；8.4 Request Coalescing；Conversation 全塞一个 List；Global Model Config；Agent Tool Schema；Q：BigKey 和 HotKey 有什么区别？；Q：为什么 Cluster 不能自动解决 HotKey？。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/05-redis/docs/10-BigKey%E4%B8%8EHotKey.md)

## 11｜RDB 与 AOF

**判定：基础具备**。AOF 不能代替任务事实、撤销持久性或备份；需恢复实测 F06/F19。

**工程证据：** [D1](../代码证据索引.md#d1)。缺陷编号见总报告。

**手册知识点：** 1. RDB：某一时刻的数据快照；纯 Tool Result Cache；Session / 临时状态；Agent Runtime State；Q：RDB 和 AOF 有什么区别？；Q：有 Replica 后还需要 Persistence 吗？。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/05-redis/docs/11-RDB%E4%B8%8EAOF.md)

## 12｜Replication：Primary / Replica

**判定：边界知识**。单实例无复制不是自动不合格；Cloud 要定义故障窗口与一致性。

**工程证据：** [D1](../代码证据索引.md#d1)。缺陷编号见总报告。

**手册知识点：** 1. 最基本拓扑；Q：Redis 主从复制是强一致吗？；Q：Replica 能不能做读扩展？。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/05-redis/docs/12-Replication.md)

## 13｜Sentinel 与自动 Failover

**判定：边界知识**。未部署 Sentinel；达到可用性要求再引入并测 failover。

**工程证据：** [D1](../代码证据索引.md#d1)。缺陷编号见总报告。

**手册知识点：** 1. Sentinel 做什么；Cache；Session；Rate Limit；Agent Lease；Q：Sentinel 解决什么问题？；Q：Sentinel 和 Cluster 怎么选？。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/05-redis/docs/13-Sentinel.md)

## 14｜Redis Cluster、Hash Slot 与 Reshard

**判定：边界知识**。当前单实例 key 无同槽保证；迁 Cluster 前 Lua/多 key 必须审计。

**工程证据：** [S2](../代码证据索引.md#s2)。缺陷编号见总报告。

**手册知识点：** 1. Redis Cluster 不使用“Key 直接 hash 到节点”；Q：Redis Cluster 为什么是 16384 个 Slot？；Q：为什么 Lua 多 Key 要同 Slot？。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/05-redis/docs/14-Cluster%E4%B8%8EHashSlot.md)

## 15｜Transaction：MULTI / EXEC / WATCH

**判定：不合格**。refresh 的 GET→SET 非原子；用原子消费或事务 CAS F05。

**工程证据：** [S1](../代码证据索引.md#s1)。缺陷编号见总报告。

**手册知识点：** 1. MULTI / EXEC 的基本语义；Session 滑动续期；Agent Task Claim；Q：Redis Transaction 能 Rollback 吗？；Q：WATCH 是悲观锁吗？。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/05-redis/docs/15-Transaction%E4%B8%8EWATCH.md)

## 16｜Pipeline：降低 RTT，不等于 Transaction

**判定：需改进**。Stream 写+TTL 可用事务/pipeline；pipeline 本身不保证业务原子性。

**工程证据：** [A1](../代码证据索引.md#a1)。缺陷编号见总报告。

**手册知识点：** 1. 没有 Pipeline 时；批量写 Session 元数据；批量读取 Tool Cache；RAG Ingestion Metadata；Q：Redis Pipeline 和 Transaction 有什么区别？；Q：Pipeline 越大越好吗？。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/05-redis/docs/16-Pipeline.md)

## 17｜Lua / Redis Functions 与服务器端原子逻辑

**判定：基础具备**。验证码场景可借服务端原子操作；refresh 尚未统一 F05。

**工程证据：** [S2](../代码证据索引.md#s2)。缺陷编号见总报告。

**手册知识点：** 1. 为什么服务器端脚本有价值；WATCH + MULTI / EXEC；Lua / Function；Rate Limit；Lock Release；Quota；Q：Redis Lua 为什么常用于分布式锁释放？；Q：Lua 和 WATCH 有什么区别？。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/05-redis/docs/17-Lua%E4%B8%8EFunctions.md)

## 18｜Redis 分布式锁：从 Acquire 到 Lease、Renewal、Failover 与 Fencing

**判定：不合格**。关键 ownership 走 SQL 合理；现有 lease 时间假设和旧 owner 写回仍不稳 F07。

**工程证据：** [D2](../代码证据索引.md#d2)。缺陷编号见总报告。

**手册知识点：** 1. 为什么单机 Lock 不够；2. 最小 Redis Lock；为什么不能 `SETNX` 后再 `EXPIRE`；3. TTL 不是装饰，而是 Lease；4. 为什么 Value 必须是唯一 Owner Token；5. 为什么不能 GET 后再 DEL；6. 加锁失败怎么办；Fail Fast；Retry with Backoff；7. 最经典的 Lease Expiry Race；8. Renewal / WatchDog 解决什么；续租也必须校验 Owner；9. Fencing Token 为什么比“我还持锁”更强；关键前提；10. Primary Failover 会怎样影响锁；11. Redlock 应该怎么理解；12. Lock 和 Idempotency 不是一回事；Lock；Idempotency；13. 什么场景不该默认用 Redis Lock；能不能用数据库唯一约束？；能不能用 Conditional Update？；能不能设计成 Idempotent？；能不能串行化到单消费者？；14. AI Application 场景；防止重复 Agent Run；Knowledge Base Rebuild；Scheduled Job；15. 一条完整 Failure Timeline；16. 常见错误；错误 1：有 TTL 就不会死锁，所以锁是正确的；错误 2：唯一 Token 解决所有问题；错误 3：WatchDog 等于绝对安全；错误 4：加了分布式锁就不需要幂等；错误 5：所有跨实例并发都必须用 Redis Lock；17. 面试怎么答；Q：Redis 分布式锁怎么实现？；Q：TTL 到期但业务没执行完怎么办？；Q：为什么锁和幂等要同时考虑？；18. 章节自测。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/05-redis/docs/18-%E5%88%86%E5%B8%83%E5%BC%8F%E9%94%81%E4%B8%8E%E6%AD%A3%E7%A1%AE%E6%80%A7.md)

## 19｜Pub/Sub、Streams 与消息边界

**判定：需改进**。Streams 有重连 ID；缺失区间/故障重同步不是简单重读能解决 F04。

**工程证据：** [A1](../代码证据索引.md#a1)。缺陷编号见总报告。

**手册知识点：** 1. Pub/Sub：在线广播；Q：Redis Pub/Sub 和 Stream 有什么区别？。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/05-redis/docs/19-PubSub%E4%B8%8EStreams.md)

## 20｜Multi-level Cache 与 Semantic / Result Cache

**判定：边界知识**。不要求语义缓存；模型答案缓存必须包含权限/版本，先保证正确性。

**工程证据：** [S2](../代码证据索引.md#s2)。缺陷编号见总报告。

**手册知识点：** 1. 为什么需要 Local Cache + Redis；Q：Local Cache + Redis 怎么保证一致？；Q：Semantic Cache 和普通 Redis Cache 有什么区别？。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/05-redis/docs/20-%E5%A4%9A%E7%BA%A7%E7%BC%93%E5%AD%98%E4%B8%8E%E8%AF%AD%E4%B9%89%E7%BC%93%E5%AD%98.md)

## 21｜Session、Conversation 与 Agent State Store 边界

**判定：不合格**。持久化 Turn 边界正确；认证撤销未持久化且失败仍返回成功 F06。

**工程证据：** [S1](../代码证据索引.md#s1)。缺陷编号见总报告。

**手册知识点：** 1. Session：共享登录状态；Runtime State；Memory；Session；Conversation Hot State；Agent Runtime State；Q：为什么 Redis 常用于 Session？；Q：Redis 里的 Agent State 和 Agent Memory 是一回事吗？。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/05-redis/docs/21-Session%E4%B8%8EAgentState.md)

## 22｜Redis 实现 Rate Limit

**判定：需改进**。按用户限频、Redis 故障本地降级已做；无法替代并发/成本准入 F08/F09。

**工程证据：** [S2](../代码证据索引.md#s2)。缺陷编号见总报告。

**手册知识点：** 1. Fixed Window Counter；Fail-open；Fail-closed；Q：Redis 如何实现 Sliding Window Rate Limit？；Q：Redis 做限流挂了怎么办？。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/05-redis/docs/22-Redis%E9%99%90%E6%B5%81.md)

## 23｜Security、Latency 与 Production Troubleshooting

**判定：需改进**。本地端口绑定正确；生产 ACL/TLS/故障诊断和池饱和仍需验证。

**工程证据：** [D1](../代码证据索引.md#d1)。缺陷编号见总报告。

**手册知识点：** 1. Redis 安全的第一原则；Cache；Session；Rate Limit；Agent State；Semantic Cache；Q：Redis 突然变慢怎么排查？；Q：Redis 安全怎么做？。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/05-redis/docs/23-Security%E4%B8%8ETroubleshooting.md)

## 24｜Redis in AI System Design

**判定：需改进**。事实/缓存/协调应分别容灾；当前共用单实例不能宣称无损恢复。

**工程证据：** [M1](../代码证据索引.md#m1)。缺陷编号见总报告。

**手册知识点：** 1. 一张总图；MySQL；Redis；Durable History；Redis Hot State；Durable；Redis；L1 可绕过；L2 可降级；L3 关键协调状态；Q：为什么 Agent 项目里既有 Redis、MySQL、Vector DB？；Q：Agent State 为什么不能全部只放 Redis？。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/05-redis/docs/24-Redis%E5%9C%A8AI%E7%B3%BB%E7%BB%9F%E8%AE%BE%E8%AE%A1%E4%B8%AD%E7%9A%84%E4%BD%8D%E7%BD%AE.md)
