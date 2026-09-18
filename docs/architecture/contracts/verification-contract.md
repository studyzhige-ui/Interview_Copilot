# Operation Verification Contract

> 状态：正式 Contract（Gate A 已批准）  
> 版本：`1.0.0`  
> 日期：2026-08-26  
> 上位规范：[`Career Agent OS Blueprint`](../career-agent-os-blueprint.md)  
> 首个使用者：[`VS-01 面试邀请接收、确认与准备交接生命周期`](../vertical-slices/vs-01-interview-invitation-intake-confirmation-handoff.md)

## 1. 目的

Verification 回答的不是“代码有没有返回 200”，而是“Operation 声称产生的结果是否真的成立”。本文定义统一结论、证据和恢复语义，并冻结 VS-01 内部 canonical write 的最小 read-back 契约。

本文不提前决定全产品是否使用独立 Verification 表、审计流或专用服务。VS-01 只要求 VerificationResult 可耐久引用、可重放核对，并与 Operation audit 和 Domain identity 关联。

## 2. VerificationResult

每个需要验证的 Operation 必须产生逻辑结果：

```text
verification_id
schema_version
operation_id
operation_name
conclusion
started_at
completed_at?
method
expected_postconditions[]
observed_evidence[]
object_references[]
provider_receipts[]?
attempt
next_reconciliation_at?
failure_or_unknown_reason?
```

`conclusion` 只能是：

- `pending`：尚未完成验证；
- `verified`：所有必需后置条件均被权威来源证明；
- `failed`：确定后置条件不成立或相互矛盾；
- `unknown`：当前证据无法判断是否成立；
- `reconciled`：先前 unknown 已得到最终结论，必须同时记录 final outcome。

## 3. 验证方法

| 方法 | 适用范围 | 真值来源 |
|---|---|---|
| `local_read_back` | 内部 canonical write | 提交后的权威存储、版本与 immutable event |
| `receipt` | 外部系统接受动作 | Provider 的稳定 receipt；仅证明 receipt 契约声明的内容 |
| `provider_read_back` | 外部状态可再次读取 | Provider 返回的当前对象状态 |
| `reconciliation` | timeout、late receipt、commit ambiguity | 同一 idempotency/resource identity 的后续核对 |
| `client_ack` | Client Action | 只证明客户端完成本地动作，不证明 Domain 或外部副作用 |

不得以日志文本、toast、模型回答、Tool 返回字符串或 HTTP 状态码单独证明业务完成。

## 4. 内部 Operation 验证规则

对于内部 canonical write：

1. 事务提交成功是验证前提，不是充分条件。
2. read-back 必须在用户 owner scope 下按稳定 identity 读取。
3. 每个创建/更新对象的 version、关键关系和 immutable event 必须与 Operation result 一致。
4. Evidence/source references 必须存在、属于同一用户且指向执行时要求的版本。
5. Domain Event/outbox identity 必须与事务结果一致；重复执行不得新增第二套事件。
6. 只有全部 required postconditions 为真，才能结论 `verified`。
7. 确定不成立时为 `failed`；无法判断提交是否发生时为 `unknown`，不得自动当作 failed 后盲目重试。

## 5. VS-01：`confirm_interview_invitation@1`

### 5.1 必需后置条件

Verification 必须核对：

1. **Opportunity**：属于当前用户；关联结果与 input 一致；新建时 company/job title 与已确认事实一致；没有预建未来阶段。
2. **Interview**：属于当前用户并关联正确 Opportunity；已确认的 start/end/timezone/original-time 与 invitation facts 一致；create/update identity 与 expected version 一致。
3. **ProcessEvent**：存在且 immutable；kind 为 `interview_scheduled`；关联同一 Opportunity；source kind/identity/version 与本次确认一致；相同 idempotency 不重复追加。
4. **Evidence**：用户陈述或候选确认、Source/Observation、字段修正及其版本可追溯；Agent 推测没有被标成用户事实。
5. **Candidate**：如果使用 candidate basis，则同一 candidate/version 已标记 confirmed 并引用本 Operation；如果使用 explicit user assertion，不得制造虚假的 candidate。
6. **Domain Events**：所需事件存在并引用相同 object versions。
7. **禁止副作用**：本 Operation 没有创建 NextAction、准备 Artifact、邮件、Calendar action、Profile change 或 PersistentTask。

### 5.2 Typed verification evidence

read-back 结果至少引用：

- Opportunity id/version；
- Interview id/version；
- ProcessEvent id/sequence/idempotency identity；
- candidate id/version（适用时）；
- Evidence/source ids/versions；
- Domain Event ids；
- Projection invalidation ids。

Verification 不复制完整对象作为新事实源；它保存断言、引用和观察结果。

### 5.3 失败处理

| 情况 | 结论 | 恢复 |
|---|---|---|
| 事务明确回滚 | `failed` | 修正输入或安全重试同一意图 |
| 事务提交但 read-back 与契约冲突 | `failed` | 阻止 success，告警并进入修复/补偿流程 |
| 提交响应丢失、无法判断是否落库 | `unknown` | 用 operation/idempotency identity reconciliation，禁止新 key 重试 |
| read-back 暂时不可用但提交身份存在 | `pending` 或 `unknown` | 有界重试后 reconciliation |
| 相同 key 已有 verified result | `verified` | 返回原结果，不重复写入 |

`failed` 不能抹去已经实际提交的事实。若事务已提交但某个派生投影失败，应验证 Canonical State，并将 Projection 修复作为独立恢复工作，而不是谎称整个领域事务未发生。

## 6. `reject_interview_invitation_candidate@1`

必须核对：候选为 rejected、resolution provenance 与用户决定一致、没有新建或更新 JobOpportunity/Interview/ProcessEvent/NextAction。相同拒绝重试返回原结果。

## 7. Observation 与 Candidate 验证

- Source snapshot hash/version 与输入一致；
- dedupe identity 稳定；
- Observation 和 Candidate 均保持低权威；
- Candidate 每个字段能回到 Source/Evidence；
- 未确认 Candidate 不出现在已确认的求职动态中；
- 第一版 Automation/fixture Observation 不自动写 canonical state。

## 8. Client Action 验证边界

`interview.preparation.open@1` 的 `client_ack` 只核对：指定客户端已打开与 Interview/Opportunity identity 对应的准备上下文。它不改变 `confirm_interview_invitation@1` 的 VerificationResult，也不证明面试准备完成。

Client Action 不可用时：

- 邀请确认 Operation 仍可 `verified`；
- Experience 显示“已确认，尚未打开准备界面”；
- 用户可以从 Interview Projection 再次发起 handoff；
- 不重复 Domain 写入。

## 9. 外部操作与 VS-01 边界

VS-01 核心不发送邮件、不写 Calendar，因此不使用 provider receipt/read-back 宣称外部完成。PDR-03 未决定前，fake Calendar 支线不进入核心 Definition of Done。

未来 External Action 必须单独定义：exact-call approval、provider identity、idempotency、receipt scope、read-back 能力、unknown outcome 与 reconciliation。不得把内部 Operation 的 `verified` 扩大解释为外部动作完成。

## 10. 事件与用户沟通

- `verification_status_changed` 必须携带 verification identity 和 typed conclusion；
- `operation_succeeded` 只能跟随 `verified`；
- `unknown` 必须使用诚实文案，例如“结果尚未确认，系统正在核对”，不能说“已完成”；
- `failed` 必须提供 stable recovery option；
- UI、Agent 最终回复、Activity Center 与日志都应引用同一 VerificationResult；
- 用户可见摘要不暴露敏感原始 Evidence，但必须允许用户进入来源视图。

## 11. 最小测试契约

VS-01 至少验证：

1. 正常 create/link 两条路径均得到 verified；
2. 同一 idempotency retry 不产生重复 Interview/ProcessEvent/Event；
3. key 相同但 fingerprint 不同被拒绝；
4. candidate 或 Opportunity stale version 不产生部分写入；
5. owner mismatch 不泄露对象存在性；
6. commit ambiguity 进入 unknown/reconciliation，不盲重试；
7. 禁止副作用断言成立；
8. Client Action failure 不改变 Domain verification；
9. verification 事件可在断线重连后恢复；
10. 任何未 verified 的结果都不会被 Copilot 宣称已完成。

## 12. 演进规则

当前物理存储方案是实施决定；一旦 VerificationResult 被跨进程恢复、Activity Center、审计或 reconciliation 共同消费，应通过专门决策确认是否提升为独立持久化 owner。无论物理位置如何，本文的 identity、conclusion 和 success gate 不能被省略。

实施状态见 [`Career Agent OS Implementation Ledger`](../../implementation/career-agent-os-ledger.md)。
