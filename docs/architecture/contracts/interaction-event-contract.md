# Interaction and Event Contract

> 状态：正式 Contract（Gate A 已批准）  
> 版本：`1.0.0`  
> 日期：2026-08-26  
> 上位规范：[`Career Agent OS Blueprint`](../career-agent-os-blueprint.md)  
> 首个使用者：[`VS-01 面试邀请接收、确认与准备交接生命周期`](../vertical-slices/vs-01-interview-invitation-intake-confirmation-handoff.md)

## 1. 目的与边界

本文定义 Career Agent OS 中 Domain、Harness 与 Experience 的统一事件外壳，以及 durable typed Interaction 和 Client Action 的最小协议。事件表达“已经发生什么”，Interaction 表达“活跃 Turn 正在等待用户提供什么”，Client Action 表达“Agent 请求具体客户端完成什么本地体验动作”。三者不能互相冒充。

本文不冻结 SSE/WebSocket、消息队列、数据库表或前端组件。传输和存储可以变化，但 identity、version、ordering、replay 和真实性语义不能变化。

## 2. Event Envelope

所有可持久化、可重放或跨边界传播的事件必须具有同一逻辑外壳：

```text
event_id
event_kind
event_category
schema_version
occurred_at
sequence_or_cursor
user_scope
conversation_id?
turn_id?
task_id?
operation_id?
tool_call_id?
interaction_id?
object_references[]
replayable
payload
```

约束：

1. `event_id` 稳定且全局唯一；重投递不产生新语义事件。
2. `event_category` 只能是 `domain`、`harness` 或 `experience`。
3. `event_kind` 与 `schema_version` 共同决定 payload schema；客户端不得靠字段存在与否猜版本。
4. `sequence_or_cursor` 在声明的 stream scope 内单调，用于重连与去重，不等同于全局时间顺序。
5. `object_references` 使用 typed kind/id/version，不复制完整对象作为第二事实源。
6. `occurred_at` 使用 UTC；来源中的原始时间和时区属于 Evidence。
7. 未知 additive 字段可忽略；未知事件版本必须安全降级，不得错误执行副作用。
8. 事件是结果记录，不是执行命令；消费重放不得再次调用 Operation。

## 3. 事件类别

### 3.1 Domain Event

表示 Career Domain 中已提交的正式事实变化。只有 Domain Kernel 或其事务 outbox 可以产生。VS-01 至少需要：

- `interview_invitation_candidate_registered@1`；
- `interview_invitation_candidate_rejected@1`；
- `interview_invitation_confirmed@1`；
- `job_opportunity_created@1`（条件性）；
- `interview_created@1` 或 `interview_schedule_updated@1`；
- `process_event_appended@1`；
- `evidence_bound@1`。

`interview_invitation_confirmed` 只能在 `confirm_interview_invitation@1` 的 Domain 事务提交后存在，不得在 Agent 推断或用户点击确认按钮但写入失败时提前发送。

### 3.2 Harness Event

表示 Turn、Task、Tool、Operation、Interaction、Verification 与恢复的执行状态。VS-01 至少需要：

- `turn_status_changed@1`；
- `operation_status_changed@1`；
- `interaction_requested@1`；
- `interaction_resolution_recorded@1`；
- `verification_status_changed@1`；
- `tool_call_status_changed@1`（Agent 入口适用）。

Harness Event 不修改 Career Domain，不得用 `turn_completed` 推断邀请已经确认。

### 3.3 Experience Event

表示用户体验应刷新、展示或执行的动作。VS-01 至少需要：

- `assistant_message_finalized@1`；
- `projection_invalidated@1`；
- `client_action_requested@1`；
- `client_action_result_recorded@1`。

Experience Event 是投影驱动信号，不拥有 Canonical State。

## 4. Operation 状态事件

`operation_status_changed@1` 的状态只能按契约合法迁移：

```text
proposed
waiting_approval
started
progress
verifying
succeeded
failed
cancelled
unknown
reconciled
```

- `succeeded` 必须引用 `VerificationResult`，且 conclusion 为 `verified`。
- `unknown` 表示结果真实性未确定，不得向用户宣称完成，也不得触发冲突写入。
- `reconciled` 必须说明最终结论以及与原 Operation identity 的关系。
- progress 可以丢弃或合并；terminal event 与最终结构化结果必须持久化。

## 5. Interaction Contract

### 5.1 定义

Interaction 是一个 active Turn 等待的 durable、typed 用户输入请求。它拥有独立 identity、version 和生命周期；不是聊天文本中的建议，也不是 Today 卡片本身。

第一版通用种类：

- `clarification`；
- `connection`；
- `approval`；
- `fact_confirmation`；
- `profile_update_confirmation`；
- `client_readiness`。

只有 `approval`、`fact_confirmation` 和 `profile_update_confirmation` 可以投影到 Today 的“待我确认”。同一 Turn 同时最多有一个前台阻塞 Interaction。

### 5.2 Interaction record

每个 Interaction 至少包含：

| 字段 | 约束 |
|---|---|
| identity/version | CAS 解决与重试依据 |
| owning turn | resolution 后恢复同一 Turn |
| kind/schema version | 决定 request/resolution schema |
| request payload | 用户作决定所需的结构化信息 |
| allowed resolutions | 显式列举，不接受任意字符串 |
| object/source/evidence refs | 可审计依据 |
| status | `pending`、`resolution_recorded`、`rejected`、`cancelled`、`expired` |
| expiry | 仅在业务真的具有期限时使用 |
| resolution provenance | user、client、timestamp、correlation identity |

Interaction 解决请求必须携带 `expected_version`。旧版本、重复但内容不同的 resolution 必须返回 conflict；完全相同的重试返回原结果。

### 5.3 `fact_confirmation@1`

VS-01 的 fact-confirmation request payload 至少包含：

```text
candidate_reference
expected_candidate_version
invitation_facts
field_provenance[]
missing_or_uncertain_fields[]
conflicts[]
source_and_evidence_references[]
opportunity_match_options[]
allowed_decisions
```

允许的决定：

- `confirm`；
- `correct_and_confirm`，必须携带 typed corrections 与 Opportunity resolution；
- `reject`。

禁止：

- 把 Agent 推荐当成用户确认；
- 隐藏来源或关键不确定性；
- 以“批准所有未来类似事实”替代本次事实确认；
- 在 Interaction 产生时直接写 JobOpportunity 或 Interview。

### 5.4 Resolution 与 Turn 恢复

1. 接收 resolution 时，以 Interaction expected version 做 CAS，记录真实用户决定，并原子地把 owning Turn 从 waiting 恢复为可调度状态。
2. 普通聊天输入、页面刷新或 SSE 重连不能隐式解决 Interaction。
3. 恢复后的同一 Turn 使用 decision identity 作为 Evidence，调用 `confirm_interview_invitation@1` 或 `reject_interview_invitation_candidate@1`。
4. 用户决定一旦被耐久记录，即使后续 Operation 失败也仍是真实历史；Interaction 不回滚成未决定。
5. 候选的 confirmed/rejected 业务状态只由对应 Operation 成功写入。Operation 失败时，Turn 显示 typed retry/recovery，不能把决定伪装成业务完成。
6. 重试必须沿用同一 Operation idempotency identity，避免重复创建 Opportunity、Interview 或 ProcessEvent。

这一分离使“用户已经做出决定”与“系统已经成功执行决定”保持真实。

## 6. Today “待我确认” Projection

Today 通过 Query/Projection 聚合 pending Interaction，不维护复制状态：

- 卡片 identity 必须是 Interaction identity；
- 确认操作必须提交 Interaction resolution，而不是前端本地删除；
- resolution 后先显示真实 waiting/running/verifying 状态，只有收到 terminal result 才完成；
- 多客户端同时操作依靠 version conflict 收敛；
- 空状态不得展示 seed、演示公司或虚构计数；
- clarification 和 client readiness 不混入“待我确认”。

## 7. Client Action Contract

### 7.1 定义

Client Action 是 Agent/Harness 请求某个客户端完成的 typed 本地体验动作。它不修改 Career Domain，且客户端 ack 不等于 Operation verification。

### 7.2 `interview.preparation.open@1`

VS-01 handoff 使用：

```text
action_id
action_kind = interview.preparation.open
schema_version = 1
initiating_client_id?
interview_id
opportunity_id
expected_object_versions
preferred_surface?
created_at
expires_at?
```

允许结果：

- `acknowledged`：客户端已打开正确对象上下文；
- `refused`：用户或客户端拒绝；
- `unsupported`：该客户端不支持；
- `failed`：打开失败，附 stable reason；
- `expired`。

约束：

1. Action 必须先持久化后投递，支持重连和多客户端接管。
2. 相同 action identity 重投递不得打开多个业务流程或产生 Domain 写入。
3. 客户端通过 object id/version 读取 handoff Projection，不依赖 prompt 文本解析。
4. `acknowledged` 只证明界面已打开，不证明准备已完成、邮件已发送或日历已创建。
5. 没有可用客户端时，Turn 可以完成业务确认并把 handoff 保留为待打开状态；不得回滚 Domain 事务。

## 8. Streaming 与恢复

- 断开连接不等于取消 Turn、Operation 或 Interaction；
- 客户端通过 snapshot + cursor 恢复，不能重放副作用；
- Tool call 以 call identity 配对 start/result，不依赖相邻顺序；
- 文本 delta 可以不耐久，最终文本和结构化 block 必须耐久；
- Turn cancellation 不能删除已经提交的 Domain 事实；
- pending Interaction、terminal Operation result 与 Client Action result 必须跨进程恢复；
- 旧客户端遇到未知 typed event 时安全忽略并重新读取 Projection。

## 9. VS-01 事件顺序不变量

1. candidate registered Domain Event 必须早于 fact-confirmation Interaction request。
2. Interaction resolution recorded 必须早于恢复后的 confirm/reject Operation started。
3. Domain Events 只有在事务提交后可见。
4. Verification verified 必须早于 Operation succeeded。
5. Projection invalidation 必须引用已提交的新 object version。
6. `interview.preparation.open` 只能在确认 Operation verified 后请求。
7. Client Action result 不得改变 Operation terminal state。
8. 相同 idempotency retry 不得产生第二组 Domain Events。

## 10. 演进规则

- Event、Interaction 与 Client Action 分别版本化；
- pending durable records 必须保存创建时 schema version；
- 改变 allowed resolution、事实权威、成功语义或副作用时提升 major schema version；
- 前后端类型应从正式 schema 生成，手工镜像只能作为过渡且必须有一致性测试；
- 当前代码差距与迁移状态只登记在 [`Implementation Ledger`](../../implementation/career-agent-os-ledger.md)。
