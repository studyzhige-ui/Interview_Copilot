# 02-fastapi：逐章审查

全部 16 章均有映射。判定针对本项目当前实现；“基础具备”不等于生产验收通过，“边界知识”不要求增加相应技术栈。知识点提纲来自该章二级及三级标题，保留原手册链接供逐点追问；本表的工程判断聚焦章节在项目中的实际落点。

[总报告](../README.md) · [代码证据索引](../代码证据索引.md)

## 01｜FastAPI 的职责：从 HTTP 请求到 ASGI Application

**判定：基础具备**。ASGI→middleware→身份依赖→router 可追踪；热路径阻塞见 F01。

**工程证据：** [P4](../代码证据索引.md#p4)。缺陷编号见总报告。

**手册知识点：** 1. FastAPI 在 AI Application 中负责什么；2. HTTP Request / Response 先建立最小直觉；3. ASGI 是什么；4. Uvicorn、Starlette、FastAPI、Pydantic 怎么分层；5. 一个请求的完整链路；6. Middleware / Dependency / Handler 不是一回事；7. FastAPI 为什么特别适合 AI Service；8. Failure：请求链路会坏在哪里；9. 🎯 面试怎么回答 FASTAPI-001；10. 易错点；11. 本章自测。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/02-fastapi/docs/01-FastAPI%E8%81%8C%E8%B4%A3%E4%B8%8EASGI%E8%AF%B7%E6%B1%82%E9%93%BE%E8%B7%AF.md)

## 02｜Routing、Request / Response 与 OpenAPI Contract

**判定：需改进**。202 admission、409 CAS、SSE 分离合理；路由仍承担事务/调度 F16。

**工程证据：** [A1](../代码证据索引.md#a1)。缺陷编号见总报告。

**手册知识点：** 1. Route 是 API Contract 的入口；2. Path / Query / Header / Cookie / Body 怎么区分；3. HTTP Method 不只是“语法不同”；4. APIRouter 为什么重要；5. Router 不应该承担业务核心；6. OpenAPI 从哪里来；7. Status Code 是 API Contract 的一部分；8. Error Contract 要稳定；9. API Versioning 什么时候需要；10. 🎯 面试怎么答“FastAPI 路由到底做了什么”；11. 易错点；12. 本章自测。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/02-fastapi/docs/02-Routing%E4%B8%8EAPIContract.md)

## 03｜Pydantic、Validation、Serialization 与 Error Contract

**判定：基础具备**。请求/响应/ORM 分离；业务不变量仍须数据库约束兜底。

**工程证据：** [A3](../代码证据索引.md#a3)。缺陷编号见总报告。

**手册知识点：** 1. 为什么 API 层必须做 Runtime Validation；2. Request Model 不等于数据库 Model；3. FastAPI 怎样识别 Request Body；4. `Annotated` 为什么越来越常见；5. Pydantic v2 的常用心智模型；6. Schema Validation ≠ Business Validation；7. Response Model 为什么是安全边界；8. Return Type 和 `response_model`；9. Validation Error、Business Error、Server Error 要分层；10. `HTTPException` 应放在哪里；11. 自定义 Exception Handler；12. AI 场景：Structured Output 到 API Response；13. 🎯 面试怎么回答；14. 易错点；15. 本章自测。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/02-fastapi/docs/03-Pydantic%E4%B8%8E%E6%95%B0%E6%8D%AE%E5%A5%91%E7%BA%A6.md)

## 04｜Dependency Injection 与 Middleware：职责、顺序与横切逻辑

**判定：基础具备**。JWT dependency、代理头顺序与 CORS 明确；身份查询仍同步 F01。

**工程证据：** [P4](../代码证据索引.md#p4)。缺陷编号见总报告。

**手册知识点：** 1. 先看两个抽象解决什么问题；2. Middleware 的位置；3. Dependency 的位置；4. Dependency Graph 可以嵌套；5. Middleware 的执行顺序；6. Middleware vs Dependency 对比；7. Authentication 放哪？；8. Logging 放哪？；Access Log / Request Timing；业务事件日志；9. Tenant Context 放哪？；10. Dependency Caching 的直觉；11. Dependency 不等于 Service Locator；12. Failure：Middleware 和 Dependency 放错位置会怎样；把 DB Session 放 Middleware；把 Request ID 放每个 Dependency；把 Authorization 只放 Middleware；13. 🎯 面试怎么回答 FASTAPI-002；14. 本章自测。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/02-fastapi/docs/04-Dependency%E4%B8%8EMiddleware.md)

## 05｜Resource Lifecycle：yield Dependency、scope 与 Application Lifespan

**判定：不合格**。流订阅依赖持有同步 Session；应完成鉴权后释放连接 F01/F09。

**工程证据：** [A1](../代码证据索引.md#a1)。缺陷编号见总报告。

**手册知识点：** 1. 两种生命周期必须分清；Application-scoped；Request-scoped；2. `yield` Dependency 是什么；3. 为什么 `finally` 很重要；4. 当前 FastAPI 的 `Depends(scope=...)`；5. Streaming 场景为什么要特别小心；6. BackgroundTasks 不应该复用已结束 Request 的资源；7. Application Lifespan 解决什么；8. 为什么不能每个 Request 创建 HTTP Client；9. DB Session 为什么通常是 Request-scoped；10. Lifespan ≠ 全局可变状态随便放；11. Graceful Shutdown 和 Lifespan 的关系；12. Failure Timeline：资源生命周期错了会怎样；Case A：每个请求建连接池；Case B：Request DB Session 被长 Stream 持有；Case C：后台任务复用 Request Resource；13. 🎯 面试怎么回答；14. 本章自测。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/02-fastapi/docs/05-ResourceLifecycle.md)

## 06｜Async Execution：`def` / `async def`、Blocking Boundary 与并发保护

**判定：不合格**。async handler 直接调用同步 ORM；utility 不会自动线程卸载 F01。

**工程证据：** [P3](../代码证据索引.md#p3)。缺陷编号见总报告。

**手册知识点：** 1. 先复习 Python 前置；2. `async def` Path Operation；3. 普通 `def` Path Operation；4. 但“普通 Utility Function”不会被 FastAPI 自动 offload；5. Blocking I/O 为什么危险；6. CPU-bound 更危险；7. Thread Pool 也不是无限资源；8. 并发 ≠ 无限并发；9. Connection Pool 和 Concurrency 必须一起看；10. `asyncio.gather` 在 API 中怎么用；11. `def` vs `async def` 的决策框架；12. FASTAPI-003 为什么被迁回 Python；13. 🎯 面试怎么回答；14. 易错点；15. 本章自测。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/02-fastapi/docs/06-AsyncExecution%E4%B8%8EBlockingBoundary.md)

## 07｜Streaming Fundamentals 与 Server-Sent Events（SSE）

**判定：不合格**。Stream ID/keepalive/代理配置已有；Redis 故障恢复分支不可达 F04。

**工程证据：** [A1](../代码证据索引.md#a1)。缺陷编号见总报告。

**手册知识点：** 1. 为什么 AI API 经常需要 Streaming；非 Streaming；Streaming；2. `StreamingResponse` 的核心模型；3. Raw Streaming 和 SSE 有什么区别；4. 现代 FastAPI 的原生 SSE 支持；5. AI Chat 的 SSE Event 不应该只有 token；6. Event Schema 要稳定；7. SSE 的 keep-alive 和 Proxy 问题；8. FASTAPI-004：Agent 中间事件如何推前端；9. Stream 中途出错怎么办；10. Client Disconnect；11. SSE vs WebSocket 先记一个边界；12. 🎯 面试怎么回答 FASTAPI-004；13. 易错点；14. 本章自测。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/02-fastapi/docs/07-Streaming%E4%B8%8ESSE.md)

## 08｜WebSocket 与 AI Event Protocol

**判定：边界知识**。文本单向 SSE 选型合理；未做双向实时语音 WS 不算缺陷。

**工程证据：** [A1](../代码证据索引.md#a1)。缺陷编号见总报告。

**手册知识点：** 1. WebSocket 的核心模型；2. 最小 WebSocket Endpoint；3. SSE vs WebSocket 怎么选；4. WebSocket Connection State 是什么；5. Connection Manager 的边界；6. AI Event Protocol 应该与 Transport 解耦；7. Message Envelope 至少考虑什么；8. Heartbeat 为什么需要；9. Backpressure 在 WebSocket 更明显；10. Auth 怎样做；11. Disconnect 时发生什么；12. SSE / WebSocket 与 FASTAPI-005 的关系；13. 🎯 面试怎么回答；14. 本章自测。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/02-fastapi/docs/08-WebSocket%E4%B8%8EEventProtocol.md)

## 09｜Authentication、Authorization、CORS 与 Tenant Context

**判定：不合格**。租户和 JWT 基础健全，refresh 双花及撤销丢失是实际缺口 F05/F06。

**工程证据：** [S1](../代码证据索引.md#s1)。缺陷编号见总报告。

**手册知识点：** 1. Authentication 和 Authorization 先分清；2. FastAPI 为什么很适合把身份做成 Dependency；3. Tenant Context 是 AI SaaS 的关键前置；4. Authorization 应靠数据和策略，不靠 Prompt；5. Route-level Policy；6. Middleware 在安全中的角色；7. CORS 到底解决什么；8. `allow_origins=["*"]` 为什么不能无脑用；9. Secret Boundary；10. Upload / Prompt / Tool Input 都是不可信输入；11. 错误响应不要泄露内部信息；12. Multi-tenant Cache Key；13. 🎯 面试怎么回答；14. 易错点；15. 本章自测。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/02-fastapi/docs/09-Security%E4%B8%8ETenantContext.md)

## 10｜DB、Redis、Vector DB 与 LLM Client 集成：资源边界与 Service Layer

**判定：不合格**。HTTP/Redis 客户端复用没有绑定 loop owner F02；需连接预算 F09。

**工程证据：** [P3](../代码证据索引.md#p3)。缺陷编号见总报告。

**手册知识点：** 1. Route 不应该直接承担所有集成逻辑；2. Application-scoped Client vs Request-scoped Session；3. HTTP / LLM Client 为什么要复用；4. DB Session 的常见 Dependency；5. FastAPI 不决定你用 sync 还是 async Driver；6. Redis Client 生命周期；7. Vector DB / RAG Client；8. LLM Provider Adapter；9. Timeout / Retry 不要散落每个 Route；10. Data Mapping Boundary；11. Pool Exhaustion 怎么定位；12. Transaction 和 Streaming 不要随便绑在一起；13. 🎯 面试怎么回答；14. 本章自测。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/02-fastapi/docs/10-ExternalResourceIntegration.md)

## 11｜BackgroundTasks、文件上传与 Long-running Task Boundary

**判定：需改进**。上传事实与异步解析已分离；队列派发与故障恢复尚不一致 F03。

**工程证据：** [R2](../代码证据索引.md#r2)。缺陷编号见总报告。

**手册知识点：** 1. `BackgroundTasks` 解决什么；2. 它不等于 Durable Task Queue；3. RAG Ingestion 是典型 Long-running Task；4. `bytes` vs `UploadFile`；5. 大文件上传的真实风险；6. 不要一次 `await file.read()` 读爆内存；7. Upload API 和 Processing API 解耦；8. `BackgroundTasks` 和 Request Resource；9. 为什么任务需要 `task_id`；10. Progress 怎么返回；11. Cancel 怎么设计；12. 🎯 面试怎么回答；13. 易错点；14. 本章自测。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/02-fastapi/docs/11-BackgroundTask%E4%B8%8EUpload.md)

## 12｜Timeout、Cancellation、Client Disconnect 与 Cleanup

**判定：需改进**。tool 超时/取消已有 fence；线程中外部副作用不等于被取消 F07/F08。

**工程证据：** [A3](../代码证据索引.md#a3)。缺陷编号见总报告。

**手册知识点：** 1. Timeout 是“等待边界”，不是“世界停止”；2. Client Disconnect 是 Transport 事件；短 LLM 生成；Durable Agent Run；3. Streaming Generator 的取消；4. 不要把 CancelledError 当普通业务异常吞掉；5. `request.is_disconnected()` 的用途；6. Timeout 应该分层；7. Downstream Cancellation 不一定存在；8. 副作用 Tool 最危险；9. Cleanup 要考虑哪些资源；10. Shield 要谨慎；11. Graceful Shutdown 也是 Cancellation 问题；12. Failure Timeline；Case：用户关闭 Agent Chat 页面；13. 🎯 面试怎么回答；14. 易错点；15. 本章自测。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/02-fastapi/docs/12-TimeoutCancellation%E4%B8%8EDisconnect.md)

## 13｜Testing：Dependency Override、Streaming、WebSocket 与错误路径

**判定：不合格**。测试数量充足但全套收集失败、场景清单漂移 F11。

**工程证据：** [Q1](../代码证据索引.md#q1)。缺陷编号见总报告。

**手册知识点：** 1. 最小 API Test；2. 测试 Input Validation；3. `app.dependency_overrides`；4. 为什么 Dependency Override 很重要；5. Service Layer 更容易测试；6. Lifespan 测试；7. Streaming Test 测什么；8. SSE Protocol Test；9. WebSocket Test；10. Error Mapping Test；11. Provider Failure Test；12. Tenant Isolation Test；13. 测试不要过度 Mock；14. 🎯 面试怎么回答；15. 本章自测。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/02-fastapi/docs/13-Testing.md)

## 14｜Logging、Trace、Metrics 与 FastAPI 性能诊断

**判定：需改进**。request ID、日志、LLM tracing 有基础；缺部署 SLO 与资源饱和证据 F17。

**工程证据：** [O1](../代码证据索引.md#o1)。缺陷编号见总报告。

**手册知识点：** 1. Access Log 和 Application Log 不一样；2. Request ID 为什么重要；3. Trace 要分 Span；4. AI-specific Span；5. P50 / P95 / P99；6. Event Loop Block 怎么看；7. Thread Pool Saturation；8. Connection Pool Exhaustion；9. Streaming 指标不只 total latency；10. Middleware Timing 能做什么；11. Error Metrics 要分类；12. Cardinality 风险；13. 性能诊断顺序；14. 🎯 面试怎么回答；15. 本章自测。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/02-fastapi/docs/14-Observability%E4%B8%8EPerformance.md)

## 15｜Deployment：Worker、Health Check 与 Graceful Shutdown

**判定：需改进**。多 API worker/队列隔离已做；资源总量、shutdown 与线程 hard-limit 假设需修正 F07/F09/F14。

**工程证据：** [D1](../代码证据索引.md#d1)。缺陷编号见总报告。

**手册知识点：** 1. Development Server 和 Production Runtime 不一样；2. 一个 Worker 是什么；3. 多 Worker 为什么能利用多核；4. Worker 数和连接池要联动；5. Process-local State 为什么危险；6. Liveness 和 Readiness 不一样；Liveness；Readiness；7. Health Check 不要做得太重；8. Graceful Shutdown 的完整顺序；9. Streaming 对 Shutdown 的影响；10. Lifespan Cleanup 在 Shutdown 中扮演什么角色；11. Container 场景的进程模型；12. 模型/Tokenizer 的 Memory Duplication；13. Horizontal Scaling 的前提；14. 🎯 面试怎么回答；15. 易错点；16. 本章自测。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/02-fastapi/docs/15-Deployment%E4%B8%8EGracefulShutdown.md)

## 16｜AI Service Patterns：Chat、RAG、Ingestion 与 Agent Run API

**判定：基础具备**。Run 与订阅分离且可恢复 waiting；不能把终止 orphan 宣称任意断点恢复 F03。

**工程证据：** [A1](../代码证据索引.md#a1)。缺陷编号见总报告。

**手册知识点：** 1. 一个成熟 AI Service 至少有四类 API；2. 普通 `/chat`；3. Streaming `/chat/stream`；4. RAG Query 的 API Boundary；5. RAG Response 要不要返回 Evidence；6. Ingestion 为什么要 Long-running；7. Ingestion 的幂等入口；8. Agent Run 为什么不是普通 Chat；9. Run API 应该显式化 Run State；10. Session 和 Run 不要混为一谈；11. FastAPI 负责 Transport，Agent Harness 负责 Runtime；12. FASTAPI-005 的真正含义；13. 一个 Production Agent API 的事件模型；14. Multi-tenant Agent Service；15. Failure Timeline：Agent Tool 超时；16. 🎯 面试怎么回答 FASTAPI-005；17. 本章自测。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/02-fastapi/docs/16-AIServicePatterns.md)
