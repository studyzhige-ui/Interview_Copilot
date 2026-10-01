# 09-agent：逐章审查

全部 24 章均有映射。判定针对本项目当前实现；“基础具备”不等于生产验收通过，“边界知识”不要求增加相应技术栈。知识点提纲来自该章二级及三级标题，保留原手册链接供逐点追问；本表的工程判断聚焦章节在项目中的实际落点。

[总报告](../README.md) · [代码证据索引](../代码证据索引.md)

## 01. Agent 系统的全貌：模型之外，谁把任务做完

**判定：基础具备**。ConversationEngine 管 Turn，strategy 管推理，tool executor 管调用；成熟性取决于闭环。

**工程证据：** [A2](../代码证据索引.md#a2)。缺陷编号见总报告。

**手册知识点：** 1. 先讲人话：Model 很聪明，但它不会替你经营一次“执行”；2. 一个实用定义；先有任务，再决定需要多少执行设施；3. 为什么“Model + API”还不够；3.1 下一步由谁驱动？；3.2 Context 越来越长怎么办？；3.3 Tool 有副作用怎么办？；3.4 中途崩了怎么办？；3.5 Agent 说“完成了”，真的完成了吗？；4. 八组执行责任：检查清单，不是八个必部署服务；5. 一个最小 Runtime 长什么样；6. Model 和 Harness 到底各负责什么；7. 一个 AI 应用场景：企业知识库 Agent；8. Harness、Backend、Framework 不要混在一起；Harness vs 普通 Backend；Harness vs Agent Framework；9. 产品实现与官方资料对照（按需展开）；9.1 Claude Code：QueryEngine 明确拥有 Conversation Runtime；9.2 Claude Code：Tool 不是普通函数；9.3 Codex：Context / Session / Tool / Sandbox 都是独立 Runtime 对象；10. HUMAN-A 信号；HUMAN-A；Claude Code 源码；OpenAI Codex 源码；外部权威资料；11. 面试怎么答；Q：什么是 Agent？为什么不等于“LLM 加几个工具”？；Q：Harness 和 Runtime 究竟有没有区别？；Q：设计一个 Agent 系统，最先决定什么？；Q：模型说完成，为什么不能直接标记业务成功？；继续展开时的回答结构；Level 1｜30 秒；Level 2｜2–3 分钟；Level 3｜继续深挖；12. 高频易错点；13. 本章自测。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/09-agent/docs/01-AgentSystemAndResponsibilities.md)

## 02. Workflow、Agent 与自主权：执行角色的边界

**判定：基础具备**。chat/agent 策略与领域操作可区分；不要把任意流程都 Agent 化。

**工程证据：** [A2](../代码证据索引.md#a2)。缺陷编号见总报告。

**手册知识点：** 1. 先讲人话：Agent 化的本质是什么；2. 为什么“更 Agent”不等于“更高级”；3. 什么任务更值得 Agent 化；4. Production 往往是 Hybrid；5. 为什么 Model + API 还不够；6. Harness / Runtime 到底是什么；7. Harness、Runtime、Orchestrator、Workflow Engine 怎么区分；8. 三个经常混淆的边界；Prompt Engineering；Context Engineering；Harness Engineering；9. Agent 化之后立刻新增哪些工程问题；10. 产品实现与官方资料对照（按需展开）；11. HUMAN-A 信号；12. 面试怎么答；Q：Workflow与Agent的本质区别是什么？；Q：Runtime 与编排器是同一个东西吗？；Q：什么时候不该用 Agent？；Q：上下文工程和 Harness 工程各解决什么？；继续展开时的回答结构；🔍 继续追问与下一步；13. 高频易错点；14. 本章自测。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/09-agent/docs/02-WorkflowAutonomyAndRuntimeBoundary.md)

## 03. Agent Loop：Session、Run、Turn、Step 与执行事件

**判定：需改进**。Turn/step/call/execution generation 有身份；原生 client loop owner 缺位 F02。

**工程证据：** [A2](../代码证据索引.md#a2)。缺陷编号见总报告。

**手册知识点：** 1. 先讲人话：Agent 的核心不是“会调用 Tool”，而是会循环推进任务；2. 一个最小可运行的 Agent Loop；3. 为什么要分 Run / Turn / Step；对照产品语义，不强制一一对应；4. 为什么这个分层对 Failure 很重要；5. Runtime 不是只有 Message，还需要 Event；6. Event 为什么最好是结构化的；7. Correlation ID 为什么关键；8. State Machine：Loop 不只是 while True；9. Runtime State 应该有什么；10. 新用户指令怎样进入正在运行的 Agent；11. Loop 什么时候继续，什么时候停止；12. 产品实现与官方资料对照（按需展开）；13. HUMAN-A 信号；14. 面试怎么答；Q：怎样解释一个完整Agent Loop？；Q：怎样描述一个最小 Agent Loop？；Q：Session、Run、Turn、Step 怎么区分？；Q：Agent 运行中用户追加消息，能直接修改当前模型输入吗？；Q：Message 和 Event 的区别为什么重要？；🔍 继续追问与下一步；15. 高频易错点；16. 本章自测。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/09-agent/docs/03-AgentLoopAndExecutionScopes.md)

## 04. Tool Contract：工具说明、参数与语义校验

**判定：基础具备**。schema→参数→policy→ledger→handler→redaction→result 完整。

**工程证据：** [A3](../代码证据索引.md#a3)。缺陷编号见总报告。

**手册知识点：** 1. 先讲人话：为什么 Tool 不能只写成一个 Python 函数；2. Tool Contract 的最小结构；3. Schema 解决两个完全不同的问题；Model-facing Schema；Runtime Validation；4. 结构校验 vs 语义校验；5. Tool Description 也是协议的一部分；6. Structured Result 也应该有 Contract；7. Tool Arguments 出错时怎么处理；8. Repair 不能无限循环；9. Side-effect Metadata 为什么应该靠 Runtime 保存；10. 版本升级怎么办；11. 产品实现与官方资料对照（按需展开）；12. HUMAN-A 信号；13. 面试怎么答；Q：怎样设计生产工具契约？；Q：为什么 Tool 不是普通 Python 函数？；Q：结构校验、语义校验、权限校验有什么区别？；Q：工具的可并发、只读、权限信息会全部进入上下文吗？；Q：模型参数出错后怎么处理？；🔍 继续追问与下一步；14. 高频易错点；15. 本章自测。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/09-agent/docs/04-ToolContractAndValidation.md)

## 05. Tool Registry：工具注册、模型可见说明与按需发现

**判定：基础具备**。TurnToolCatalog/registry/动态 MCP 发现已有；需目录版本和规模指标。

**工程证据：** [A5](../代码证据索引.md#a5)。缺陷编号见总报告。

**手册知识点：** 1. Registry 解决什么；2. Registry 与 Model-visible Tool Set 必须分开；3. Router 做什么；4. 为什么需要 Namespace；5. Tool Exposure 不应该只有“注册 / 未注册”；6. Progressive Discovery 的核心；7. Tool Discovery 可以怎么做；Rule / Intent Filter；Embedding / Semantic Search；LLM Router；Hybrid；8. Discovery 的 Evaluation；9. Tool Unavailable 怎么办；10. Registry 更新与版本问题；11. 产品实现与官方资料对照（按需展开）；Codex 固定源码：注册表与 model_visible_specs 的真实连接；Claude Code 用户快照：getTools → toolToAPISchema → tool result；12. HUMAN-A 信号；13. 面试怎么答；Q：注册、发现和调用怎样配合？；Q：工具怎样注册并最终调用？；Q：加载工具时，是否会把所有注册信息都加入上下文？；Q：为什么工具多时要分目录、候选和调用三个阶段？；Q：两个外部Server都提供search，怎样处理？；Q：Codex 与 Claude Code 中，哪里能看到这种分离？；14. 高频易错点；15. 本章自测。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/09-agent/docs/05-ToolRegistrationAndDiscovery.md)

## 06. Tool Execution：结果回填、错误分类与有限恢复

**判定：需改进**。typed error、超时和账本已有；未知外部效果不能简单重试 F07/F18。

**工程证据：** [A3](../代码证据索引.md#a3)。缺陷编号见总报告。

**手册知识点：** 1. 一次完整 Tool Execution；2. Executor 为什么不应该直接暴露原始函数；3. Tool Result 不是一段字符串；4. 为什么日志、模型输出、Host Metadata 应分层；5. Failure Classification；6. Repair、Retry、Fallback、Fail 不是一回事；Repair；Retry；Fallback；Fail；7. Retry Eligibility 必须先判断幂等与副作用；8. Timeout 也不是一种简单失败；9. 错误反馈给模型应该“可行动”；10. Result Validation；11. Pre / Post Tool Hook 为什么很有用；12. 产品实现与官方资料对照（按需展开）；13. HUMAN-A 信号；14. 面试怎么答；Q：一次工具调用怎样从请求走到可用结果？；Q：工具出错后，所有错误都交给模型吗？；Q：哪些错误可以自动重试？；Q：工具HTTP成功但没有生成目标文件怎么办？；Q：怎样设计工具结果的多种表示？；🔍 继续追问与下一步；15. 高频易错点；16. 本章自测。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/09-agent/docs/06-ToolExecutionAndFailure.md)

## 07. Tool Control：副作用、并发、取消与进度

**判定：基础具备**。read 并行、mutating/unknown 独占、资源交集屏障；取消后外部结果需验证。

**工程证据：** [A2](../代码证据索引.md#a2)。缺陷编号见总报告。

**手册知识点：** 1. 为什么 Tool 不能默认并发；2. Tool Side Effect 分类；Pure / Read-only；Local Mutable；External Reversible；External Irreversible / High Risk；3. Concurrency Safety 应是 Tool Contract 的一部分；4. Resource Key 比“Tool Name”更准确；5. 用户取消为什么必须传播；6. Cancellation 是协议，不是一个布尔值；7. Parent / Child Cancellation；8. Progress 为什么是 Runtime Primitive；9. Streaming Result 与 Final Result 要分开；10. Side Effect + Cancellation 的危险窗口；11. 产品实现与官方资料对照（按需展开）；12. HUMAN-A 信号；13. 面试怎么答；Q：怎样设计工具并发、取消与进度？；Q：用户取消为什么必须传播？；Q：哪些工具可以并发？；Q：用户取消后工具又返回成功怎么办？；Q：运行中用户改了约束，怎么生效？；14. 高频易错点；15. 本章自测。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/09-agent/docs/07-ToolConcurrencyAndCancellation.md)

## 08. Planning / ReAct：计划、目标、停止与预算

**判定：需改进**。plan/progress/局部无进展检测已有；无部署资源预算兜底 F08。

**工程证据：** [A6](../代码证据索引.md#a6)。缺陷编号见总报告。

**手册知识点：** 1. 先讲人话：Planning 不是“先写一份超长计划”；2. ReAct 解决什么问题；3. Plan-Execute-Replan 什么时候更合适；4. Goal Control：Agent 怎么知道自己还在做原任务；5. Stop Condition 不是只有 `max_steps`；5.1 成功停止；5.2 无法继续；5.3 强制停止；6. Budget 应该是多维的；7. Dead Loop / Oscillation 怎么检测；8. Dynamic Instruction / Steering 怎么进入当前 Run；9. Planning Failure Timeline；10. Framework 不应该决定你的 Planning 模型；11. HUMAN-A 信号；12. 面试怎么答；Q：Agent 怎样避免无限循环？；Q：ReAct 和 Plan-Execute-Replan 怎么选？；Q：计划更新会不会破坏Prompt Cache？；Q：怎样检测Agent死循环？；Q：计划说done了，为什么不能直接结束？；13. 高频易错点；14. 本章自测。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/09-agent/docs/08-PlanningGoalAndControl.md)

## 09. Context Assembly：上下文编排、缓存与结果外部化

**判定：基础具备**。上下文/工具大结果/历史分工清楚；缓存收益待实测。

**工程证据：** [C1](../代码证据索引.md#c1)。缺陷编号见总报告。

**手册知识点：** 1. Context、Memory、State、History 先分清；2. 一次 Agent Context 可能来自哪些 Source；3. Context Assembly 应该是“Compiler”，不是字符串拼接；4. 编排顺序、追加历史与计划更新怎样配合；5. Token Budget 要分区，而不是统一“还剩多少”；6. Large Tool Result 为什么不能直接塞回 Context；7. Offloading 和 Truncation 有什么区别；8. Prompt / Context Cache 应该缓存什么；9. Context Pollution / Stale Context；10. Context Dedup 为什么重要；11. Context Assembly Failure Timeline；12. 产品实现与官方资料对照（按需展开）；固定源码路径：初始上下文、消息追加、工具说明、计划更新与压缩后重建；用户提供的固定源码路径：query.ts → utils/api.ts → 模型适配；13. HUMAN-A 信号；14. 面试怎么答；Q：Agent Context 应该怎么组装？；Q：Tool Result 太大怎么办？；Q：Agent上下文怎样编排？；Q：新的计划和修订计划放在哪里？；Q：为什么一直追加也不意味着永远命中Prompt Cache？；Q：工具结果很大时怎么处理？；Q：Codex和Claude的编排顺序是一套吗？；15. 高频易错点；16. 本章自测。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/09-agent/docs/09-ContextAssemblyAndCache.md)

## 10. Context Compaction：压缩、替代历史与继续执行

**判定：需改进**。checkpoint CAS、through_seq 和替代上下文具备；真实多次压缩约束保真未证明 F12。

**工程证据：** [C1](../代码证据索引.md#c1)。缺陷编号见总报告。

**手册知识点：** 1. Compaction 为什么存在；2. Compaction 与普通 Summary 的区别；3. Compaction 什么时候触发；3.1 Token Threshold；3.2 Phase Boundary；3.3 Tool Result Pressure；4. 哪些信息必须保留；5. 哪些内容适合压缩或外部化；6. Replacement History 为什么重要；7. Compaction Correctness 怎样验证；7.1 Structural Invariant；7.2 Semantic Invariant；7.3 Continuation Test；7.4 Regression Eval；8. Compaction 失败怎么办；9. Stale Context 是另一类问题；10. Summary Error 会产生“压缩后的错误记忆”；11. Compaction 和 Memory 的边界；12. 产品实现与官方资料对照（按需展开）；固定源码：触发判定 → 摘要请求 → 替代历史 → 后续调用；用户固定快照：消息预算与多种压缩机制如何协作；13. HUMAN-A 信号；14. 面试怎么答；Q：Agent Context 快满了怎么办？；Q：怎样验证 Compaction 没丢信息？；Q：Compaction完整流程是什么？；Q：Codex压缩提示是什么，输出是否JSON？；Q：Claude Code有几层压缩，何时触发？；Q：System Prompt是否会被压缩掉？；Q：怎么防止摘要丢掉关键约束？；15. 高频易错点；16. 本章自测。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/09-agent/docs/10-CompactionAndContinuation.md)

## 11. Memory：提取、召回、更新、纠错与遗忘

**判定：基础具备**。两阶段提取合并、来源/lease/retention/更正已有；真实记忆质量仍需回归。

**工程证据：** [M1](../代码证据索引.md#m1)。缺陷编号见总报告。

**手册知识点：** 1. 先把 Context / Memory / State / History 分开；2. Memory 为什么不能“什么都存”；3. Memory 可以怎样分层；3.1 Working Memory；3.2 Episodic Memory；3.3 Semantic Memory；3.4 Procedural Memory；4. 什么时候应该写 Memory；5. Extraction：从对话变成 Memory Record；6. Retrieval-on-demand 为什么比“全量注入”更重要；7. Memory Consolidation 是什么；8. Memory Correctness：错误事实比“没有记住”更危险；9. Memory Conflict 怎么处理；10. Memory Staleness / Expiration；11. Privacy / Tenant Boundary；12. Memory Failure Timeline；13. 产品实现与官方资料对照（按需展开）；Claude Code：文件型auto memory与CLAUDE.md有何不同；Codex：固定memories模块的两阶段离线提炼；14. HUMAN-A 信号；15. 面试怎么答；Q：Agent Memory 怎么设计？；Q：Memory 错了怎么办？；Q：什么时候提取，什么时候变长期记忆？；Q：记忆冲突或错误怎么办？；Q：怎么评估记忆不是在污染上下文？；16. 高频易错点；17. 本章自测。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/09-agent/docs/11-MemoryLifecycle.md)

## 12. State / Persistence：程序怎样记住当前工作

**判定：基础具备**。History/Turn/Interaction/ToolCall 持久化，热事件不当唯一事实。

**工程证据：** [A1](../代码证据索引.md#a1)。缺陷编号见总报告。

**手册知识点：** 1. Session 是什么；2. Run / Turn / Step 再复习；3. State 应该保存什么；3.1 Identity State；3.2 Control State；3.3 Environment State Reference；3.4 Safety State；3.5 Progress State；4. History 应该是事件流，而不是“一个超长字符串”；5. Snapshot 与 Event Log 怎么配合；6. Persistence 不等于把 Context 存下来；7. Session Store 选什么；8. Tenant Isolation 为什么必须进入 State Schema；9. Session Hijack / Cross-tenant Pollution；10. Concurrency：同一个 Session 同时来两个请求怎么办；11. State Version 为什么重要；12. Cold Resume 与 Warm Resume；Warm Resume；Cold Resume；13. Session Retention / Deletion；14. HUMAN-A 信号；15. 面试怎么答；Q：Agent Session / State 怎么设计？；Q：Agent State究竟是什么？；Q：State和Persistence有什么区别？；Q：为什么不把Trace作为恢复数据库？；Q：每个东西都必须记录版本吗？；16. 高频易错点；17. 本章自测。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/09-agent/docs/12-StateHistoryAndPersistence.md)

## 13. Checkpoint / Resume：检查点、恢复、分叉与重放

**判定：需改进**。waiting resume 与 fence 实现较强；running 崩溃路径是失败终结，并非通用恢复 F03。

**工程证据：** [A3](../代码证据索引.md#a3)。缺陷编号见总报告。

**手册知识点：** 1. Checkpoint 不是“把聊天记录存一下”；2. Checkpoint 应该发生在哪里；3. Long-running Task 的状态机；4. Resume 的第一步不是“继续调用模型”；5. 最危险的问题：Tool 成功，但 Checkpoint 失败；补偿不是把世界退回过去；6. Idempotency 是第一道防线；7. Side-effect Ledger；8. Compensation 什么时候需要；9. Pause / Resume 与 HITL；10. Cancellation 与 Resume 的关系；11. Resume 和 Fork 不一样；Resume；Fork；12. Replay 是什么；12.1 State Replay；12.2 Execution Replay；13. Worker Lease 与 Ownership；14. Checkpoint Schema 一个示例；15. HUMAN-A 信号；16. 面试怎么答；Q：Agent Checkpoint 应该保存什么？；Q：Tool 成功但服务崩了，怎么避免重试两次？；Q：Checkpoint的作用是什么，两点之间崩溃怎么办？；Q：为什么工具成功后立刻存检查点仍可能重复？；Q：Resume和Compaction、Replay有什么区别？；Q：Fork需要复制什么？；Q：框架有Checkpointer是否就不需要幂等？；17. 高频易错点；18. 本章自测。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/09-agent/docs/13-CheckpointResumeAndRecovery.md)

## 14. Permission / Approval / Sandbox：政策、批准与隔离

**判定：需改进**。policy 与参数绑定批准较强；stdio 环境裁剪不是 OS sandbox F18。

**工程证据：** [S3](../代码证据索引.md#s3)。缺陷编号见总报告。

**手册知识点：** 1. 三层边界；Policy；Approval / HITL；Sandbox；2. 为什么“全部弹确认框”不是好安全设计；3. Risk Classification 可以看什么；4. Permission Context 应该结构化；5. Approval 为什么必须和 RunState 结合；6. Approval Record 应保存什么；7. Sandbox 解决的是另一层问题；8. Filesystem Sandbox；9. Network Sandbox；10. Sandbox 不是“绝对安全”；11. Permission 与 Prompt Injection 的关系；12. Permission Failure Timeline；13. HUMAN-A 信号；14. 面试怎么答；Q：Permission、Approval、Sandbox 有什么区别？；Q：审批为什么要持久化？；Q：参数校验、权限、批准和沙箱为什么都要有？；Q：Sandbox和Docker是什么关系？；Q：HITL为什么不是一个确认弹窗？；Q：如何减少审批次数而不降低安全性？；15. 高频易错点；16. 本章自测。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/09-agent/docs/14-PermissionApprovalAndSandbox.md)

## 15. Guardrails：提示注入、秘密保护与风险控制

**判定：需改进**。低信任输入、出网校验与脱敏有基础；缺完整 prompt injection/记忆投毒评测 F18。

**工程证据：** [S3](../代码证据索引.md#s3)。缺陷编号见总报告。

**手册知识点：** 1. Threat Model：先问“攻击者想让 Agent 做什么”；2. Instruction 与 Data 必须在 Runtime 概念上分层；3. Guardrail 应该分生命周期，而不是一个总开关；3.1 Ingress Guardrail；3.2 Context Guardrail；3.3 Tool Guardrail；3.4 Output / Egress Guardrail；4. Prompt Injection 为什么不能靠“检测一句恶意文本”解决；5. Secret 不应该直接进入模型 Context；6. Tool Capability 要最小化；7. Containment：重点不是“永不犯错”；8. Untrusted Tool Result 也可能继续攻击下一轮；9. RAG / MCP 的 Injection Surface；10. Memory Poisoning；11. Output Leakage；12. Security Incident Timeline；13. 产品实现与官方资料对照（按需展开）；14. HUMAN-A 信号；15. 面试怎么答；Q：Agent 如何防 Prompt Injection？；Q：为什么Output Guardrail不能替代工具授权？；Q：如何区分模型被诱导与系统已被攻破？；Q：为什么Trace也要最小化？；16. 高频易错点；17. 本章自测。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/09-agent/docs/15-InjectionAndContainment.md)

## 16. MCP：从 Host / Client / Server 到完整协议往返

**判定：基础具备**。host/client/server、stdio/HTTP、schema 校验与会话管理有实现；不等于外部可信。

**工程证据：** [A5](../代码证据索引.md#a5)。缺陷编号见总报告。

**手册知识点：** 1. MCP先给清楚定义；2. Host、Client、Server究竟是谁；3. Tools、Resources、Prompts各提供什么；4. 一次完整工具调用：发现不是执行；5. 不要混写2025与2026生命周期；6. 传输是什么，安全又是什么；需要更多输入、出错和目录过期时怎么办；7. 从协议回到执行系统；8. HUMAN-A 信号；9. 面试怎么答；Q：MCP是什么，解决什么？；Q：Host、Client、Server怎么区分？；Q：模型调用MCP工具的完整链路是什么？；Q：MCP原理为什么不能只背initialize？；Q：MCP工具太多时怎么办？；10. 高频易错点；11. 本章自测。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/09-agent/docs/16-MCPArchitectureAndLifecycle.md)

## 17. Skills / Hooks / Plugins：能力扩展与生命周期

**判定：基础具备**。skill/catalog 与 tool 分离；没有任意 hook 平台不算缺陷，需生命周期效果验收。

**工程证据：** [A5](../代码证据索引.md#a5)。缺陷编号见总报告。

**手册知识点：** 1. 先给稳定边界；Tool；MCP；Skill；Hook；2. 为什么 Tool 太多会出问题；3. Capability Catalog；4. Skill 与 Tool 的区别；5. Skill Progressive Disclosure；6. Hook 是什么；7. Codex Hooks 的实现证据；8. Extension Failure 怎么处理；9. Capability Versioning；10. Security Boundary；11. 产品实现与官方资料对照（按需展开）；12. HUMAN-A 信号；13. 面试怎么答；Q：Tool、MCP、Skill、Hook 有什么区别？；Q：Tool 太多怎么处理？；Q：MCP是什么，解决什么？；Q：Host、Client、Server怎么区分？；Q：模型调用MCP工具的完整链路是什么？；Q：MCP原理为什么不能只背initialize？；Q：MCP工具太多时怎么办？；14. 高频易错点；15. 本章自测。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/09-agent/docs/17-SkillsHooksAndExtensions.md)

## 18. Routing：意图、模型适配与供应商容错

**判定：需改进**。provider 适配和错误分类已有；故障切换/价格与质量路由缺实测 F17。

**工程证据：** [A4](../代码证据索引.md#a4)。缺陷编号见总报告。

**手册知识点：** 1. Routing 至少有三层；Intent Routing；Capability Routing；Model / Provider Routing；2. Intent Recognition 可以有多种实现；Rule；Small Classifier；LLM Router；Agent 自主 Tool Selection；3. Router 也需要 Evaluation；4. Model Routing 的目标是什么；5. Provider Adapter 为什么是 Runtime 能力；6. Provider Adapter 应统一什么，不统一什么；7. Claude Code 的实现信号；8. Runtime Resilience 先做 Error Classification；9. Retry Eligibility 为什么比 Retry Count 更重要；10. Model Failover 会不会改变结果语义；11. Circuit Breaker 在 Agent Runtime 中怎么用；12. Fallback 不应该静默；13. Routing Failure Timeline；14. HUMAN-A 信号；15. 面试怎么答；Q：Agent Router 怎么设计？；Q：Provider 失败怎么 Fallback？；Q：Agent路由至少分哪几类？；Q：如何评估Router？；Q：为什么Adapter不应抹平全部供应商差异？；16. 高频易错点；17. 本章自测。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/09-agent/docs/18-RoutingAndProviderResilience.md)

## 19. Multi-Agent / A2A：内部协作与跨系统任务

**判定：边界知识**。当前核心为单 Agent 工具运行时；多 Agent/A2A 非必要，不可虚报支持。

**工程证据：** [A2](../代码证据索引.md#a2)。缺陷编号见总报告。

**手册知识点：** 1. 什么时候真的值得 Multi-Agent；2. Subagent as Tool；3. Handoff 模式；4. Manager / Worker 模式；5. Task Ownership 必须显式；6. Context Isolation 为什么很重要；7. Claude Code `Task.ts` 提供的实现信号；8. Workspace Concurrency 是 Coding Agent 的高风险点；9. 共享 Workspace 的几种策略；9.1 单 Writer；9.2 Isolated Branch / Worktree；9.3 Fine-grained Ownership；9.4 Optimistic Merge；10. Shared State 也会 Race；11. Multi-Agent Failure；12. Budget Explosion；13. Recursive Delegation / Deadlock；14. A2A 解决什么；一次完整跨系统委派；15. A2A 和内部 Subagent 有什么区别；16. Result Aggregation 不是“把所有答案拼起来”；17. HUMAN-A 信号；18. 面试怎么答；Q：什么时候用 Multi-Agent？；Q：MCP 和 A2A 区别？；Q：多Agent什么时候值得？；Q：Handoff与Agent-as-Tool有什么区别？；Q：A2A原理与完整生命周期是什么？；Q：两个Agent同时改文件怎么办？；19. 高频易错点；20. 本章自测。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/09-agent/docs/19-MultiAgentAndA2A.md)

## 20. Trace / Replay：记录必要证据，定位具体问题

**判定：需改进**。tool call audit 与事件可定位；完整重放和代价/资源时序证据不足 F17。

**工程证据：** [O1](../代码证据索引.md#o1)。缺陷编号见总报告。

**手册知识点：** 1. Log、Metric、Trace 各解决什么；Log；Metric；Trace；2. Trace Identity；3. 一个 Agent Span 可按诊断需要记录什么；Model Span；Tool Span；Context Span；State Span；4. OpenAI Agents SDK Tracing 给出的证据；5. 为什么要记录“模型看到什么”；6. Trace 与 Privacy 冲突；7. Replay 有三种不同含义；8. Trace 如何定位“Agent 卡住”；9. Token / Cost 异常怎么定位；10. Context Management 自己也需要 Observability；11. Agent Trace Schema 示例；12. Observability 不应该和 Evaluation 混为一谈；13. 产品实现与官方资料对照（按需展开）；14. HUMAN-A 信号；15. 面试怎么答；Q：Agent Trace 应该记录什么？；Q：Trace、History、Checkpoint如何区分？；Q：Agent卡住怎样排查？；Q：为什么每个事件不需要自己的版本？；Q：保存原始请求能否保证重现？；16. 高频易错点；17. 本章自测。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/09-agent/docs/20-TraceReplayAndDiagnosis.md)

## 21. Agent Evaluation、Benchmark 与 Data Flywheel

**判定：不合格**。场景门禁失效；缺当前端到端真实任务 outcome benchmark F11/F12。

**工程证据：** [Q2](../代码证据索引.md#q2)。缺陷编号见总报告。

**手册知识点：** 1. 先分清 Agent Harness 和 Eval Harness；用一次考试理解两个Harness；2. 最终结果比“模型说完成了”更重要；3. 四个评测视角：结果、过程、组件、资源与安全；3.1 Final Outcome；3.2 Process / Runtime；3.3 Component；3.4 Resource / Safety；用同一份报告对照；4. Eval Dataset 从哪里来；5. Dataset 要分层采样；6. Ground Truth 不一定是一个字符串；7. LLM Judge 什么时候适合；8. Process Metric 为什么也重要；9. Tool / Routing Eval；10. Agent Eval 与 Trace 的关系；11. Regression 为什么必须自动化；12. SWE-bench 为什么是重要参考；13. Benchmark Contamination / Overfitting；14. Data Flywheel；15. Online Validation；16. Evaluation Failure Timeline；17. HUMAN-A 信号；18. 面试怎么答；Q：Agent 应该怎么评估？；Q：Data Flywheel 怎么做？；Q：Agent评测和普通文本生成评测有何不同？；Q：如何根据评测改善Agent？；Q：LLM Judge可以做唯一评分器吗？；Q：Benchmark高分能证明生产可用吗？；19. 高频易错点；20. 本章自测。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/09-agent/docs/21-EvaluationBenchmarkAndImprovement.md)

## 22. Coding Agent：Repo Understanding → Patch → Test → Verify

**判定：需改进**。仓库有大量测试与 CI；全套不绿意味着 AI 编码交付链未闭合 F11。

**工程证据：** [Q1](../代码证据索引.md#q1)。缺陷编号见总报告。

**手册知识点：** 1. Coding Agent 最大的问题不是生成，而是理解和验证；2. Repository Understanding 不等于 Vector RAG；ripgrep / Text Search；Filesystem Navigation；AST / LSP；Vector / Semantic Search；Dependency Graph；3. Repo Understanding 的搜索漏斗；4. Patch 应尽量小；5. Workspace State 必须可控；6. Patch Application 要有前置版本；7. Test 是 Outcome Verification，不是装饰；8. Test Failure 怎么处理；9. Diff Review 是另一道防线；10. Acceptance Criteria 必须独立于 Agent 自评；11. Verification Pyramid；12. Command Execution 的风险；13. AI-assisted Development 中人的责任；14. Rollback / Delivery；15. Claude Code / Codex 为什么是重要实现参考；16. Coding Agent Failure Timeline；17. HUMAN-A 信号；18. 面试怎么答；Q：AI Coding 怎么保证质量？；Q：Coding Agent怎样证明Patch可交付？；Q：为什么仓库理解不等于Vector RAG？；Q：测试全绿为什么还可能错？；Q：多Agent改同一仓库怎样控制？；19. 高频易错点；20. 本章自测。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/09-agent/docs/22-CodingAgentDelivery.md)

## 23. Production Agent：从单进程到可运营执行系统

**判定：不合格**。进程/池/准入/任务超时假设存在结构缺口 F02/F03/F07/F08/F09。

**工程证据：** [D1](../代码证据索引.md#d1)。缺陷编号见总报告。

**手册知识点：** 1. 先看一个单机 Demo；2. 一个通用 Production Agent Runtime；3. Brain / Hands / Durable Session 分离；4. API / Streaming Gateway；5. Harness Worker 应尽量可替换；6. Scheduler / Queue 为什么重要；7. Execution Sandbox Pool；8. Tool Gateway；9. Model Provider Gateway；10. Durable Event / State Store；11. 多租户隔离；12. Long-running Agent 如何跨 Worker；13. Streaming 和 Durable State 不要混；14. Deployment / Scaling 的核心指标；15. Cost Governance；16. Failure Domain；17. 一个 Production Failure Timeline；18. Observability / Eval Plane；19. Brain / Hands 分离不是唯一正确架构；20. HUMAN-A 信号；21. 面试怎么答；Q：Production Agent Backend 怎么设计？；Q：生产Agent Backend怎么设计？；Q：为什么断开SSE不一定取消任务？；Q：为什么增加Worker可能更慢？；Q：怎样跨Worker恢复而不重复副作用？；22. 高频易错点；23. 本章自测。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/09-agent/docs/23-ProductionRuntime.md)

## 24. Framework Mapping：按核心语义比较框架与自研

**判定：基础具备**。自研带来业务语义控制；应以故障矩阵/维护成本比较框架，不重写为换框架。

**工程证据：** [A2](../代码证据索引.md#a2)。缺陷编号见总报告。

**手册知识点：** 1. 先写自己的 Requirement Matrix；2. Framework 提供的价值通常是什么；3. OpenAI Agents SDK 怎样映射；4. LangGraph 适合解决什么类型问题；5. LangChain 适合什么；6. 什么时候自研 Runtime；7. Build-vs-Buy Matrix；8. Framework Selection 的错误方法；8.1 只看 Star；8.2 只看 Demo；8.3 只看 Feature Checklist；9. Framework Evaluation 应该用真实 Workload；10. Escape Hatch 很重要；11. Framework Upgrade 风险；12. 自研最小 Runtime 到底需要什么；13. Framework 不会替你解决业务正确性；14. Framework Migration；15. 产品实现与官方资料对照（按需展开）；16. HUMAN-A 信号；17. 面试怎么答；Q：怎样完整说明框架选型的理由？；Q：LangChain / LangGraph / 自研怎么选？；Q：Agents SDK、LangGraph、LangChain与自研怎么选？；Q：Session、Checkpointer和Store是一回事吗？；Q：LangGraph interrupt恢复为什么还要考虑副作用？；Q：怎样避免未来被框架绑定？；18. 高频易错点；19. 本章自测。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/09-agent/docs/24-FrameworkSelection.md)
