# VS-01 — Interview Invitation Intake, Confirmation, and Preparation Handoff Lifecycle

# 面试邀请接收、确认与准备交接生命周期

> 状态：Vertical Slice Spec（Gate A 已批准，实施中）  
> 版本：`1.0.0`  
> 日期：2026-08-26  
> 上位规范：[`Career Agent OS Blueprint`](../career-agent-os-blueprint.md)  
> 已批准决定：PDR-01、PDR-02（2026-08-26）  
> 实施状态源：[`Career Agent OS Implementation Ledger`](../../implementation/career-agent-os-ledger.md)

## 0. 文档契约

### 0.1 目的

本文冻结 Career Agent OS 的第一条完整可运行主干：从三个入口中的任意一个接收到面试邀请信息，到邀请事实被用户明确建立，系统创建或关联正确的 JobOpportunity、建立 Interview、追加真实流程事件，更新产品投影，并把用户安全交接到该 Interview 的准备上下文。

该切片的价值不只是“增加面试邀请功能”，而是首次贯通：

```text
Perceive
→ Contextualize
→ Understand
→ Decide / Confirm
→ Act through Shared Operation
→ Verify
→ Communicate
→ Experience Handoff
```

### 0.2 规范关系

本文服从已批准 Blueprint 与正式 Contracts。它可以收窄 VS-01 的实施范围，但不能改变产品宪法、事实权威、Atomic Operations、三种入口平权、Trust 或 Career Data Assets 的长期语义。

本文不冻结物理路由、组件、数据库表名、Python 包、队列或视觉稿。Implementation Ledger 记录当前资产、迁移、删除条件和状态；这些内容不得回流为产品规范。

### 0.3 当前批准状态

- **PDR-01 已批准**：VS-01 正式名称与范围冻结；第一版使用 UI、自然语言和 fixture/manual Observation，不依赖真实 Gmail/Calendar。
- **PDR-02 已批准**：`confirm_interview_invitation` 的事务边界冻结；不包含 NextAction、准备计划、邮件或 Calendar action。
- **PDR-03 未决定**：Calendar Event、Interview Schedule 与 fixed-time NextAction 长期所有权，以及 fake Calendar 可选支线。它不阻塞核心 VS-01，故本规格不纳入该支线。

## 1. 用户价值与成功定义

### 1.1 用户问题

候选人收到面试邀请时，信息可能来自手动输入、对 Copilot 的自然语言说明或外部来源观察。现有工具常把“检测到一封邮件”“用户点了确认”“页面显示了一条记录”和“系统已经可靠建立面试安排”混为一谈，容易产生重复岗位、错误时间、虚构阶段或无法追溯的状态。

### 1.2 用户结果

完成后，用户能够确定：

- 系统记录的是自己确认过或自己明确陈述的邀请事实；
- 邀请属于正确的求职机会；
- 面试安排、来源和流程变化可以核对；
- Today、求职、面试和 Copilot 指向同一对象；
- 点击后进入正确的面试准备上下文；
- Agent 没有暗中发送邮件、写 Calendar、创建建议性待办或虚构未来流程。

### 1.3 业务完成条件

核心 VS-01 只有在以下条件全部成立时完成：

1. 邀请事实由用户明确陈述，或由用户对候选事实 confirm/correct-confirm；
2. JobOpportunity 已被正确创建或关联；
3. Interview 已创建或更新并承载已确认安排；
4. `interview_scheduled` ProcessEvent 已按来源和幂等规则追加；
5. Evidence、用户决定与对象版本可追溯；
6. `confirm_interview_invitation@1` 已通过 Verification；
7. Today/求职/面试/活动中心/Copilot 的相关 Projection 可从同一事实重建；
8. 用户可以通过 Client Action 或普通 UI 打开正确的准备上下文。

## 2. 范围

### 2.1 包含

- 直接 UI 手动录入已安排的面试邀请；
- 用户在 Copilot 中明确陈述已安排邀请；
- fixture/manual Connector Observation 的接收、不可变 snapshot 和去重；
- 邀请事实候选、字段级 Evidence、歧义与冲突；
- durable `fact_confirmation` Interaction；
- confirm、correct-confirm 和 reject；
- Opportunity 明确关联或受控创建；
- Interview 创建/更新与 schedule 事实；
- ProcessEvent、Domain Events、Operation Events 与 Projection invalidation；
- Turn waiting/resume、断线重连、CAS、幂等与 Verification；
- Today、求职、面试、活动中心和 Copilot 的最小投影；
- `interview.preparation.open@1` Client Action handoff；
- UI、Agent、Automation 三种入口调用同一 Operation 语义；
- 一组确定性测试与新蓝图场景门禁设计。

### 2.2 第一版 Invitation 形状

happy path 只覆盖已经有具体开始时间的邀请。最小必需事实：

- company name；
- job title；
- timezone-aware scheduled start；
- original time text 与 source timezone；
- source/evidence identity。

可选：round/stage label、scheduled end、location、meeting URL、contact identity。

要求用户选择时间槽、未给时间、岗位匹配存在实质歧义或来源冲突无法解决时，系统保持 `needs_clarification`，不写 Canonical State。后续 Slice 可以扩展邀请协商，但不得通过降低事实门槛来假装完成。

### 2.3 明确非目标

- 真实 Gmail、Calendar 或 Outlook provider 接入；
- 发送确认邮件、回复招聘方或写 Calendar；
- 完整面试准备内容生成；
- 生成 Artifact；
- 自动创建 NextAction；
- 模拟面试、实际面试执行、录音、转录和复盘；
- AbilitySignal、AbilityUnderstanding 或 AbilityProfile 更新；
- Profile change、长期 Memory producer 或 PersistentTask；
- 多 Agent、Hooks 或全 Harness 重写；
- 一次性改造所有旧页面和 Tool；
- 把 fixture Observation 描述成真实 Provider 成功。

## 3. 共享对象与所有权

### 3.1 Source Snapshot

不可变保存入口来源和版本。它证明“来源中出现了什么”，不证明该内容已经成为用户事实。

### 3.2 Invitation Observation

表示系统观察到可能的面试邀请，保持低权威、可去重、可撤回。第一版 Automation 入口只能到达 Observation/Candidate/Interaction，不能 auto-apply Canonical State。

### 3.3 Invitation Candidate

表示对 Source 或用户消息的 typed 提取，包含字段值、provenance、confidence、缺失、冲突、提取器版本和 lifecycle。它不是 JobOpportunity、Interview 或 ProcessEvent。

### 3.4 JobOpportunity

用户级多个求职流程中的权威机会 owner。VS-01 只创建或关联当前邀请所属 Opportunity，不虚构未来阶段。

### 3.5 Interview

已确认面试安排和后续面试生命周期的权威业务对象。第一版要求它能表达已确认 schedule 与 Opportunity 关系；物理模型由实施阶段确定。

### 3.6 ProcessEvent

Opportunity 的 append-only 流程事实。VS-01 追加 `interview_scheduled`，保存 source provenance、sequence 与 idempotency。修正通过领域允许的修正/supersession 语义完成，不原地改写历史。

### 3.7 Interaction

active Turn 正在等待的 durable typed 用户决定。Today 只投影它，不拥有它。

### 3.8 NextAction

不属于本事务。如果邀请同时意味着用户真实需要做某项行动，必须由另一项明确 Operation 创建；如果只是 Agent 推荐，则只有用户接受 Recommendation 后才能创建。

## 4. Shared Operations

VS-01 使用 [`Shared Application Operation Contract`](../contracts/application-operation-contract.md) 中：

- `intake_interview_invitation_observation@1`；
- `register_interview_invitation_candidate@1`；
- `confirm_interview_invitation@1`；
- `reject_interview_invitation_candidate@1`；
- `get_interview_invitation_candidate@1`；
- `get_interview_invitation_handoff@1`。

高层 Skill 可以称为“记录并开始准备这场面试”，但必须编排这些原子 Operation，不能拥有一个绕过确认、事务和 Verification 的宏 Tool。

## 5. 三种入口

### 5.1 入口 A：直接 UI

```text
用户打开面试邀请录入界面
→ 填写/修正结构化事实
→ 明确选择已有 Opportunity 或创建新 Opportunity
→ 提交明确用户意图
→ UI Adapter 调用 confirm_interview_invitation@1
→ Verify
→ 刷新投影
→ 打开准备上下文
```

用户亲自提交完整表单属于 `explicit_user_assertion`，不应再弹出重复的 fact confirmation。表单必须展示时间及时区、Opportunity resolution 和将产生的正式变化。

### 5.2 入口 B：自然语言 Copilot

用户明确、完整地陈述邀请且 Opportunity 唯一时：

```text
Current user input
→ typed extraction with user-assertion provenance
→ 必要澄清（如有）
→ confirm_interview_invitation@1
→ Verify
→ 诚实沟通并 handoff
```

如果存在实质推测、来源转述或 Opportunity 歧义：

```text
register candidate
→ fact_confirmation Interaction
→ 用户 confirm / correct / reject
→ 同一 Turn resume
→ confirm/reject Operation
```

Agent 不能因为自然语言“看起来像确认”而跳过必需事实，也不能把自己的岗位匹配建议伪装成用户选择。

### 5.3 入口 C：主动 Career Loop（fixture/manual Observation）

```text
fixture/manual source arrives
→ intake observation + immutable snapshot + dedupe
→ candidate extraction outside Operation
→ register candidate
→ create fact_confirmation Interaction
→ Today 待我确认
→ 用户决定
→ same Turn resume
→ shared confirm/reject Operation
```

第一版不 auto-apply，即使 confidence 很高。该限制保证首个切片先验证事实确认与恢复主干；未来若允许某类 observation 自动推进，必须单独通过 Policy、Evaluation 和产品决定。

## 6. 核心流程

### 6.1 Candidate confirmation happy path

1. Ingress 持久化 Source Snapshot 与 Observation，并返回稳定 dedupe identity。
2. 规则/模型在 Operation 外提取 typed candidate；每个字段绑定 Evidence。
3. `register_interview_invitation_candidate@1` 登记 candidate。
4. Harness 编译 candidate、来源、Opportunity options 和权限，创建 `fact_confirmation@1`。
5. Turn 进入 waiting；Interaction 投影到 Today“待我确认”和 Copilot。
6. 用户 confirm 或 correct-and-confirm，提交 expected Interaction/candidate version。
7. Interaction resolution 与 Turn resume 被耐久记录。
8. 同一 Turn 调用 `confirm_interview_invitation@1`。
9. Operation 在一个 Domain 事务内 create/link Opportunity、create/update Interview、append ProcessEvent、bind Evidence、emit Domain Events。
10. Verification read-back 通过后，Operation 进入 succeeded。
11. Projection invalidation 触发 Today、求职、面试和活动中心重读。
12. Copilot 用 verified result 沟通，并请求 `interview.preparation.open@1`。
13. 客户端 ack 表示已经打开准备上下文；不表示准备完成。

### 6.2 Direct assertion happy path

与 6.1 相同的 Domain Operation 与 Verification，但没有 Observation/Candidate/Interaction。Evidence 直接引用用户表单提交或当前 user message。不得为了统一界面而伪造候选和确认记录。

### 6.3 Correct-and-confirm

用户可以修正时间、时区、轮次、地点、会议链接或 Opportunity resolution。修正值拥有用户决定权威；原始 candidate 仍保留作审计，Operation 使用 corrected facts。对未展示给用户的隐藏字段不得默认为确认。

### 6.4 Reject

`reject_interview_invitation_candidate@1` 只终结候选并保存来源。它不把现有 Opportunity 标记为 rejected，也不创建 Interview/ProcessEvent/NextAction。Today 卡片在 durable terminal event 后消失。

## 7. 状态模型

### 7.1 Observation/Candidate

```text
Observation: received → candidate_registered → pending_confirmation
                                             ↘ needs_clarification

Candidate: pending_confirmation → confirmed
                                → rejected
                                → superseded
```

`confirmed` 只能由 confirm Operation 事务写入；Interaction resolution 本身不能提前改变它。

### 7.2 Turn/Interaction

```text
Turn running
→ waiting(interaction=fact_confirmation)
→ runnable/resumed
→ operation_running
→ verifying
→ completed

异常终点：cancelled | failed | blocked | waiting_reconciliation
```

普通聊天输入不能解决 pending Interaction。断线只中断投递，不取消 Turn。

### 7.3 Operation

使用 Verification Contract 的状态，不允许 `domain_committed → succeeded` 跳过 verifying。重复请求回放已有 verified result，而不是重复写入。

## 8. Trust、Permission 与安全

### 8.1 事实确认与外部批准分离

Fact confirmation 是确认产品事实；Approval 是授权外部或高风险动作。VS-01 核心没有 External Write，因此不应显示“发送邮件/创建日历”的混合批准卡。

### 8.2 参数与资源范围

- 对候选的确认只适用于 candidate id/version 和展示的事实；
- Opportunity 选择只适用于明确 id/version 或 create input；
- Agent 的 canonical write 权限必须在 Operation 执行时复核；
- fixture Connector 只能写 Source/Observation/Candidate，不拥有 canonical write 权限；
- hard deny、owner mismatch 和 stale version 必须 fail closed。

### 8.3 Source 安全

邮件/fixture 原文中的指令一律是不可信数据。它不能改变 System Instructions、Policy、allowed Operations、Tool scope 或 Verification。meeting URL 和联系人字段必须做 schema/安全校验，展示时避免自动执行。

### 8.4 用户修正与删除

用户能查看字段来源并修正候选。Source 删除或 Observation 撤回后的长期保留和已确认事实处理必须遵守 Evidence/删除 Contract；VS-01 至少保证投影不继续把失效来源当成当前证明，且不会改写 immutable ProcessEvent 历史。

## 9. Experience Contract

### 9.1 Today

只使用 Blueprint 冻结的四类：

- **下一步**：VS-01 不自动新增；只展示此前已成立的真实 NextAction。
- **待我确认**：展示 pending fact-confirmation Interaction；使用真实 identity/version/count。
- **求职动态**：只在 confirm Operation verified 后展示已经发生的面试安排变化。
- **Copilot 动态**：展示 Turn/Operation 的 waiting、running、verifying、completed/failed/reconciliation 摘要。

不得展示 seed 数据、虚构公司或把 Recommendation 作为第五类模块。

### 9.2 求职

Opportunity 详情/时间线读取同一 ProcessEvent 和 Interview reference。点击邀请或动态进入该 Opportunity/Interview 上下文；浅层卡片和深层流程页不得维护两套状态。

### 9.3 面试

展示已确认安排、来源、关联 Opportunity 和准备入口。`?prompt=` 之类字符串不是业务 handoff；应使用 typed object reference/Client Action。

### 9.4 活动中心

最小显示：Turn、Interaction、Operation、Verification 的当前与 terminal 状态；可通过 identity 进入来源或对象。它不是另一套任务 owner。

### 9.5 Copilot

Copilot 横跨产品而非一级导航页面。它理解当前 surface/object scope，显示待确认事实、执行状态和 verified result；最终回复必须区分：

- “我发现了一条可能的邀请，等待你确认”；
- “你已经确认，系统正在写入/核对”；
- “邀请已确认并建立面试安排”；
- “结果尚未确认，系统正在核对”；
- “没有完成，原因与恢复方式如下”。

### 9.6 Client Action handoff

Operation verified 后请求 `interview.preparation.open@1`。没有客户端、用户拒绝或客户端失败不会回滚已确认事实；用户可从 Interview 页面重试打开。

## 10. Context Package

使用 [`Context Package Contract`](../contracts/context-package-contract.md)。关键不变量：

- 用户明确陈述与 Agent inference 不混淆；
- pending Interaction、candidate/source/version、active Operation 与 Verification 不被压缩丢失；
- 只读取 disambiguation 所需 Opportunity；
- System Prompt 不永久包含用户数据；
- 执行前重新读取版本和 Policy；
- 最终沟通只根据 typed verified result。

## 11. 失败与恢复

| 场景 | 系统行为 |
|---|---|
| Observation 重复 | 返回原 identity，不创建第二候选或 Interaction |
| 同名公司/岗位多匹配 | `needs_clarification`，不静默关联 |
| 缺少具体时间 | clarification；不写 Canonical State |
| Interaction stale | conflict，重读当前卡片；不执行 Operation |
| Candidate stale/superseded | 阻止确认，展示变化 |
| Opportunity stale | Operation conflict；用户/Agent 重读并重新决定 |
| Turn worker 被杀 | durable heartbeat/dispatch generation 恢复同一 Turn |
| SSE 断线 | snapshot + cursor 重连；不取消、不重放副作用 |
| Operation 事务回滚 | no partial state；typed retry/fix |
| commit outcome 不明确 | unknown + reconciliation；禁止新 key 重试 |
| Verification 失败 | 不发 succeeded；进入修复/告警 |
| Client Action 失败 | Domain 保持 verified；保留手动打开入口 |
| 用户取消 Turn | 未提交写入取消；已提交事实不回滚 |
| 用户 reject candidate | 无 canonical side effect |

## 12. 事件最小集合

### 12.1 Domain

- candidate registered/rejected；
- invitation confirmed；
- Opportunity created（条件性）；
- Interview created/schedule updated；
- ProcessEvent appended；
- Evidence bound。

### 12.2 Harness

- Turn status；
- Interaction requested/resolution recorded；
- Operation status；
- Verification status；
- Tool call status（Agent 路径）。

### 12.3 Experience

- assistant final message；
- projection invalidated；
- client action requested/result。

全部使用 [`Interaction and Event Contract`](../contracts/interaction-event-contract.md) 的 envelope、identity、version 和 ordering。

## 13. 验收场景

下列场景是新蓝图 evaluation manifest 的 VS-01 条目设计；本阶段不修改现有 evaluation 文件。

| ID | 场景 | 必需断言 |
|---|---|---|
| VS01-S01 | UI 明确录入 + create Opportunity | 无重复确认；同一 Operation；verified；无 NextAction/外部动作 |
| VS01-S02 | Copilot 明确陈述 + link existing | 用户陈述 provenance；正确关联；同一 verified 结果 |
| VS01-S03 | Fixture Observation | 只到 candidate + pending fact confirmation；未确认前无 canonical write |
| VS01-S04 | Correct-and-confirm | 原候选保留；修正值作为用户决定；一次原子事务 |
| VS01-S05 | Reject | 候选 terminal；JobOpportunity/Interview/ProcessEvent/NextAction 零变化 |
| VS01-S06 | 幂等重试 | 一个 Opportunity/Interview/ProcessEvent/event set；回放原结果 |
| VS01-S07 | Interaction/candidate/opportunity version conflict | typed conflict；无部分写入 |
| VS01-S08 | 跨用户对象引用 | fail closed，不泄露对象细节 |
| VS01-S09 | waiting 和 verifying 期间断线/worker kill | 同一 Turn 恢复；不丢决定；不重复副作用 |
| VS01-S10 | Client Action ack/fail | 只影响 handoff 状态，不改变 Domain verification |
| VS01-S11 | Source prompt injection | 不扩大权限、不调用额外 Tool、不改变 System Instructions |
| VS01-S12 | Recommendation/NextAction 边界 | confirm Operation 不创建 NextAction；建议不能进入 Today 下一步 |
| VS01-S13 | 不虚构未来阶段 | 只建立本次 confirmed interview 和流程事件 |
| VS01-S14 | commit ambiguity | unknown + reconciliation；不宣称完成、不盲重试 |
| VS01-S15 | Today 真实性 | 无 seed/fallback；四类投影边界正确；卡片 CAS |

## 14. 测试与质量门禁

每个实现批次必须同时具有：

1. Operation schema/contract tests；
2. Domain transaction、append-only、CAS、idempotency 和 owner isolation tests；
3. Observation/Candidate provenance 与 rejection tests；
4. Interaction waiting/resume/reconnect tests；
5. Policy execution-time tests；
6. Verification success/failure/unknown/reconciliation tests；
7. Event schema、ordering、replay 和 projection invalidation tests；
8. UI adapter parity、Today truthfulness 和 Client Action tests；
9. 三入口端到端 deterministic scenarios；
10. Agent quality tests：正确 Operation、无宏副作用、最终沟通真实性。

发布门禁必须基于新蓝图场景；旧 evaluation 可以作为实现回归保护，但不能单独证明本切片符合新产品语义。

## 15. 实施策略

### 15.1 原则

采用新边界 + 完整垂直切片 + 逐所有权迁移。不得先创建整个目标目录空壳，也不得在旧页面上继续增加第四套邀请逻辑。

### 15.2 建议批次

1. **Schema 与 owner seam**：冻结可生成 schema、候选 owner、Interview schedule owner 与 Operation execution record。
2. **Domain path**：实现共享 Operations、事务、Events、Verification 与 migration。
3. **Harness path**：fact confirmation、same-Turn resume、Context Package、typed events。
4. **Experience path**：Today、求职、面试、活动中心、Copilot 与 Client Action。
5. **Automation fixture path**：Observation ingress、dedupe、candidate、pending confirmation。
6. **Evaluation and cutover**：三入口场景、回归、旧入口封闭与删除。

每一批都必须可运行、可测试、可回滚；具体 owner、当前资产和退出条件见 Implementation Ledger。

### 15.3 Strangler 与回滚

- 新 Operation 成为唯一写入 owner 前，旧路径只能通过 Adapter 汇入或保持只读；
- 不允许新旧路径同时独立写同一邀请语义；
- 读 Projection 可以在迁移期双读比较，但只允许一个 canonical write owner；
- feature gate 只能切入口，不能改变事实语义；
- rollback 优先回到旧只读体验或关闭新入口，不回滚已经验证的 Domain 事实；
- 删除旧路径前必须有使用扫描、contract/e2e gate 和数据一致性证明。

## 16. Gate A Implementation Gaps（基线）

本节冻结 Gate A 批准时用于启动实施的语义差距，不作为实时进度。当前代码路径、完成度和剩余发布阻塞只登记在 Implementation Ledger：

1. 现有 Observation 可以在特定条件 auto-apply；VS-01 fixture 路径必须先事实确认。
2. 现有 interview-scheduled Observation 主要追加流程事件，没有统一创建/更新 Interview。
3. 当前 Interaction kinds 未完整表达 `fact_confirmation`。
4. 当前 Client Action 协议偏向模拟面试，缺少通用准备 handoff。
5. 当前事件流不足以统一表示 Domain/Harness/Experience 与 Verification。
6. 当前 Today“待我确认”使用本地 seed，未绑定 durable Interaction。
7. 当前求职与面试存在重复/浅层路径，typed object handoff 未贯通。
8. 当前 Verification 主要散落在服务返回、receipt 或测试中，缺少统一可引用结论。
9. 当前 Context 管理具备耐久与压缩资产，但尚未形成本文的 typed authority/source package。
10. 当前新蓝图 evaluation manifest 尚未建立。

这些差距是实施任务，不改变已批准产品边界。

## 17. Definition of Done

VS-01 只有在以下全部成立时可以标记完成：

1. 本 Spec 和四份最小 Contracts 已批准并有 versioned schema；
2. 三种入口在第一版范围内汇入同一 Operation 语义；
3. confirm/correct-confirm/reject/clarify 均符合事实权威；
4. PDR-02 事务与禁止副作用被自动化断言；
5. waiting/resume/reconnect/interrupt/worker recovery 不丢决定或重复写入；
6. Operation success 受 Verification gate 约束，unknown 能 reconciliation；
7. Today 不再使用邀请 seed/fallback，四类投影边界正确；
8. 求职与面试能打开同一 confirmed Interview；
9. Client Action 只完成 preparation handoff；
10. Activity Center 显示真实执行状态；
11. VS01-S01 至 VS01-S15 全部通过；
12. 当前受保护回归测试保持通过；
13. 旧邀请写路径已汇入、隔离或删除，没有双 owner；
14. 文档、Contract、Ledger 与实现状态一致；
15. 没有把真实 Gmail/Calendar、完整准备、NextAction 或 Ability 能力误报为本切片完成。

## 18. 仍然开放但不阻塞核心 VS-01

1. PDR-03：Calendar Event、Interview Schedule 与 fixed-time NextAction 的长期所有权；
2. Interview schedule 的最终物理存储形态，只要保持本文 owner 与事务语义；
3. Copilot 常驻、抽屉或对象工作区的具体呈现；
4. VerificationResult 的全产品独立持久化 owner；VS-01 可先使用可耐久引用的 operation audit 形态；
5. 第一版之后是否允许经过评测的特定 Observation 自动确认。

这些问题不得被实现者自行扩展为核心 VS-01 的新范围。
