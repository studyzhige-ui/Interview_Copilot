# Shared Application Operation Contract

> 状态：正式 Contract（Gate A 已批准）  
> 版本：`1.0.0`  
> 日期：2026-08-26  
> 上位规范：[`Career Agent OS Blueprint`](../career-agent-os-blueprint.md)  
> 首个使用者：[`VS-01 面试邀请接收、确认与准备交接生命周期`](../vertical-slices/vs-01-interview-invitation-intake-confirmation-handoff.md)

## 1. 契约目的

本文定义 UI、Agent 与 Automation 共享的 Atomic Application Operation 边界，并冻结 VS-01 所需的最小 Operation Catalog。它约束业务语义、授权、幂等、证据、事务、结果与验证，不冻结 HTTP 路由、Python 类名、数据库表、队列或前端组件。

本文不得被解释为允许 Agent 直接写表、任意更新字段，或用一个高层宏 Tool 隐藏多个业务意图。高层目标由 Skill、Plan 或 Task Template 编排；实际改变必须通过本文定义的业务原子完成。

## 2. 通用 Operation Envelope

每次 Operation 调用必须具有以下逻辑字段；物理传输可由正式 schema 生成：

| 字段 | 约束 |
|---|---|
| `operation_name` | 稳定业务名称，不使用页面或按钮名称 |
| `schema_version` | 输入与结果契约版本 |
| `operation_id` | 一次逻辑执行的全局身份 |
| `idempotency_key` | 同一业务意图重试时保持稳定 |
| `request_fingerprint` | 对影响语义的输入做规范化指纹 |
| `actor` | `user`、`agent_on_behalf`、`automation` 或受信任的 `system_connector` |
| `user_scope` | 被操作数据的用户/租户所有权范围 |
| `causation` | 可选的 conversation、turn、task、tool call、interaction、observation 身份 |
| `expected_versions` | 所有需要 CAS 的对象版本 |
| `input` | 对应 Operation 的 typed payload |
| `policy_context` | 调用时权限、授权与连接上下文，不替代执行时复核 |
| `requested_at` | UTC 时间；业务原始时间与时区另存 |

同一 `idempotency_key` 与同一 fingerprint 必须返回同一逻辑结果；相同 key 但 fingerprint 不同必须返回稳定的 `idempotency_conflict`，不得覆盖或执行第二个意图。

## 3. 执行生命周期

```text
accepted
→ policy_checked
→ started
→ domain_committed
→ verifying
→ succeeded

或

accepted → rejected / failed / cancelled

或在提交结果无法确定时

domain_commit_ambiguous → unknown → reconciled
```

约束：

1. Policy 必须在执行边界按实际参数、资源与版本重新检查；计划阶段的判断不能替代执行时判断。
2. Canonical 写入必须在 Domain 事务中完成，不允许 Adapter 分步拼接同一业务原子的写入。
3. `operation_succeeded` 只能在 Verification Contract 满足后形成。
4. 内部提交结果不确定时必须先以 `unknown` 封闭后续冲突写入，再通过幂等身份核对；不得盲目重放。
5. Projection 刷新、通知和 Client Action 可以由成功后的事件触发，但不得改变原事务已经冻结的业务边界。

## 4. Actor 与三种入口

| 入口 | Adapter 责任 | 不得承担的责任 |
|---|---|---|
| UI | 将用户表单和当前对象引用转换为 typed input；保留显式用户陈述的来源 | 复制领域规则、直接写表、伪造 Agent 推理 |
| Agent | 注入 Turn、Tool Call、Evidence、Policy 与用户授权身份；把 typed result 返回 Harness | 自行决定隐藏副作用、把推测升级为事实 |
| Automation | 注入 trigger、task、read/action scope 与预授权；调用相同 Operation | 使用预授权范围外的资源，或绕过需要当前用户确认的事实 |

三个 Adapter 可以具有不同体验，但对同一 Operation 必须获得相同的前置条件、领域效果、幂等结果和错误代码。

## 5. Evidence 与事实权威

Operation 输入必须区分：

- 用户明确陈述；
- 用户对候选事实的确认或修正；
- Connector Observation；
- Agent/模型提取或推测；
- Canonical State 的现有版本。

模型提取不能伪装成用户陈述。Observation 与候选事实只有在对应 Operation 完成后才能影响 Canonical State。Operation 必须保存足够的 source/evidence identity 与版本，使用户能够查看、修正、失效或删除来源，并使下游投影可以重建。

## 6. Typed Result 与失败

成功结果至少包含：

- `operation_id` 与最终状态；
- 创建、更新或读取的 object references；
- 新 object versions；
- Domain Event references；
- Evidence references；
- Verification reference 与结论；
- 需要失效的 Projection identities。

稳定失败至少区分：

| 类别 | 示例 |
|---|---|
| `validation_error` | 输入形状或第一版必需事实不完整 |
| `ownership_denied` | 对象不属于当前用户 |
| `policy_denied` | 当前 actor/effect/resource 未获授权 |
| `stale_version` | 候选、Opportunity、Interview 或 Interaction 版本冲突 |
| `idempotency_conflict` | 同一 key 对应不同请求指纹 |
| `ambiguous_match` | 无法确定要关联的 Opportunity |
| `state_conflict` | 当前领域状态不允许该意图 |
| `source_unavailable` | 必需来源已失效或不可读取 |
| `transient_failure` | 可安全重试且尚未提交 |
| `unknown_outcome` | 提交结果不能判定，必须 reconciliation |
| `verification_failed` | 已有结果与契约后置条件不一致 |

用户可见文案可以本地化；程序不得匹配文案判断恢复方式。

## 7. VS-01 Operation Catalog

### 7.1 `intake_interview_invitation_observation@1`

**意图**：把手动/fixture Connector 提供的邀请来源保存为不可变 Source Snapshot 与低权威 Observation，并执行所有权、格式和去重检查。

**Effect**：source write；不得写 Canonical Career State。

**输入**至少包含：provider/source identity、source version、observed_at、raw source reference，以及在 Connector 边界产生的结构化候选内容。第一版不接真实 Gmail 或 Calendar。

**幂等**：同一用户、provider、source identity 与 source version 只产生一个逻辑 Observation；内容改变必须形成新 snapshot/version，不得改写旧证据。

**结果**：Observation reference、Snapshot reference、dedupe outcome。

**失败**：ownership、invalid source、duplicate-with-conflict、source unavailable。

### 7.2 `register_interview_invitation_candidate@1`

**意图**：把规则或模型在 Operation 外完成的提取结果登记为可审阅的邀请候选。

**Effect**：candidate write；不得写 JobOpportunity、Interview、ProcessEvent 或 NextAction。

**输入**至少包含：Observation/用户消息来源、逐字段 provenance、逐字段 confidence、缺失与冲突、候选版本和提取器版本。

**结果**：candidate identity/version、状态 `pending_confirmation` 或 `needs_clarification`、Evidence references。

**约束**：Operation 不调用开放式模型；提取结果必须作为 typed input 进入。候选不能被 Today 或 Agent 表述为已经确认发生的求职动态。

### 7.3 `confirm_interview_invitation@1`

**已批准边界（PDR-02）**：一个原子业务意图内同时完成邀请事实确认、JobOpportunity 创建或关联、Interview 创建或更新、`interview_scheduled` ProcessEvent、Evidence 绑定和 Domain Events。它不创建 NextAction、准备计划、邮件、Calendar action、Profile change 或长期自动化。

#### 7.3.1 Confirmation basis

输入必须使用下列互斥形式之一：

```text
explicit_user_assertion
  user assertion source
  structured invitation facts

candidate_confirmation
  candidate_id
  expected_candidate_version
  decision identity
  optional user corrections
```

- 直接 UI 表单和用户在 Copilot 中明确、完整的陈述属于 `explicit_user_assertion`，无需制造重复确认。
- Connector Observation、Agent 推测或有实质歧义的提取必须使用 `candidate_confirmation`，并引用已经解决的 fact-confirmation Interaction。
- “用户说了”与“Agent 从来源推断”必须在 Evidence 中可区分。

#### 7.3.2 第一版 Invitation Facts

VS-01 happy path 只接受已经具有具体安排的邀请：

| 必需 | 可选 |
|---|---|
| company name | round/stage label |
| job title | scheduled end |
| timezone-aware scheduled start | location |
| original time text 与 source timezone | meeting URL |
| source/evidence identity | contact identity |

要求用户选择多个时间槽、尚无具体时间或无法确定岗位的邀请进入 `needs_clarification`，不写 Canonical State。这只是 VS-01 的范围边界，不定义未来产品的全部邀请语义。

#### 7.3.3 Opportunity resolution

输入必须显式选择：

```text
link_existing(opportunity_id, expected_version)
或
create_new(company, job_title, optional direction/source facts)
```

Agent 可以建议匹配，但不能在存在实质歧义时静默选择。创建新 Opportunity 不得预先虚构后续面试阶段、Offer 或 NextAction。

#### 7.3.4 原子事务

Domain 事务按以下逻辑完成：

1. 校验 actor、owner、confirmation basis、source/candidate/version 与第一版必需事实；
2. 获取幂等身份和相关资源的并发保护；
3. 关联或创建 JobOpportunity；
4. 创建或更新承载已确认安排的 Interview；
5. 追加 `interview_scheduled` ProcessEvent；
6. 绑定 Evidence，并在适用时把 candidate 标记为 confirmed；
7. 写入对应 Domain Events 与 Projection invalidation outbox；
8. 提交事务；
9. 按 Verification Contract 做本地 read-back；通过后才产生 `operation_succeeded`。

候选确认状态不得先于该事务成功。物理表结构、Interview 安排字段的最终 owner 和迁移方式由实施规格决定，但不得拆散上述业务事务。

#### 7.3.5 结果

结果至少引用：Opportunity、Interview、ProcessEvent、Evidence、Domain Events、新版本、Verification 与需要失效的 Today/求职/面试 Projection。

#### 7.3.6 权限

该 Operation 是 `internal/canonical write`。直接用户调用可使用当前明确意图；Agent 和 Automation 必须具备该用户范围内的写权限。对候选事实的用户确认不是 External Action approval，且不得被宽泛预授权替代。

### 7.4 `reject_interview_invitation_candidate@1`

**意图**：记录用户对邀请候选的拒绝，使其不再等待确认。

**事务**：以 expected version 将候选标记为 rejected，保存 resolution provenance，并发出候选拒绝事件。

**禁止效果**：不得创建或更新 JobOpportunity、Interview、ProcessEvent、NextAction 或 Profile。

拒绝的是候选事实，不等于自动把已存在的真实 Opportunity 标记 rejected。

### 7.5 `get_interview_invitation_candidate@1`

按用户范围读取候选、字段来源、冲突、版本与允许决定。它是 Query，无隐藏写入。

### 7.6 `get_interview_invitation_handoff@1`

读取已确认 Invitation 的 handoff view：Opportunity、Interview、安排、来源、准备入口可用性与最近 Operation verification。它是可重建 Projection，不拥有第二份状态。

## 8. 明确不属于 Operation 的内容

- LLM 对邮件或自然语言的开放式提取；
- Agent 的高层规划与 Recommendation；
- UI 页面跳转和动画；
- SSE/WebSocket 传输；
- 通知文案；
- 生成面试准备内容；
- Calendar 或邮件外部写入；
- Recommendation 被接受后创建 NextAction 的另一项 Operation。

这些能力可以消费 Operation，但不能改变其事务边界。

## 9. 版本与演进

1. additive optional 字段可以在 `@1` 中演进；
2. 改变事实权威、事务范围、幂等身份或成功定义必须提升 Operation version；
3. durable pending Interaction 必须保留创建时的版本；
4. Adapter 必须由同一 schema 生成或通过契约测试证明一致；
5. 删除旧入口前，Implementation Ledger 必须证明 UI、Agent、Automation 已全部汇入共享 Operation。

## 10. 当前实施差距引用

现有代码资产、差距、迁移与删除条件不在本文维护。统一见：

- [`VS-01 Implementation Ledger`](../../implementation/career-agent-os-ledger.md)
- [`Career Agent OS Initial Assessment`](../../implementation/career-agent-os-initial-assessment.md)
