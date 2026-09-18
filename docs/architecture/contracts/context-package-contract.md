# Context Package Contract

> 状态：正式 Contract（Gate A 已批准）  
> 版本：`1.0.0`  
> 日期：2026-08-26  
> 上位规范：[`Career Agent OS Blueprint`](../career-agent-os-blueprint.md)  
> 首个使用者：[`VS-01 面试邀请接收、确认与准备交接生命周期`](../vertical-slices/vs-01-interview-invitation-intake-confirmation-handoff.md)

## 1. 目的

Context Package 是 Context Compiler 为一次模型边界或确定性决策边界按需编译的、typed、可审计上下文。它解决“此刻 Agent 应该知道什么、每条信息权威多高、来自哪里、何时失效”，而不是把全部 Career Data Assets 塞进系统提示词。

本文冻结上下文角色、权威顺序、来源要求、预算与压缩不变量。它不冻结某个 Prompt 文本、模型 provider、向量库或 token 常数。

## 2. 稳定 System Instructions

系统提示词只保存跨用户稳定的内容：

- Interview Copilot 的 Agent 身份与使命；
- 用户最终事实权；
- Canonical State、Observation、Evidence 与 Memory 的权威关系；
- Permission、Approval、External Action 与 Verification 原则；
- Tool/Operation 使用规则；
- 不得编造完成、来源、未来流程或用户决定；
- 当前 Contract 的协议说明。

以下内容不得作为永久系统提示词：用户档案、岗位列表、邮件、文件、长期记忆、当前页面、pending Interaction、执行状态、当前日期相关事实或完整 Tool 目录。它们必须按任务需要编译。

## 3. Context Package Envelope

```text
package_id
schema_version
compiled_at
user_scope
conversation_id
turn_id
task_id?
purpose
object_scope[]
policy_scope
budget
sections[]
source_manifest[]
compiler_version
```

每个 `section` 至少包含：

```text
role
authority
content_or_reference
source_references[]
object_versions[]
observed_at?
valid_at?
expires_at?
sensitivity
truncation_state
```

Package 是执行快照，不是事实 owner。需要最新状态的 Operation 仍必须在执行边界重新读取并做 version/Policy 校验。

## 4. 上下文角色与权威

从高到低的默认解释顺序：

| Role | 权威 | VS-01 示例 |
|---|---|---|
| `instructions` | 行为约束，不能声明用户事实 | 权限、事实权威、Operation 使用原则 |
| `current_user_input` | 对本次用户意图具有高权威 | 用户明确说“我收到明天下午三点的面试邀请” |
| `canonical_state` | 已确认产品事实 | 已有 JobOpportunity、已确认 Interview |
| `interaction_decision` | 对该候选决定具有高权威 | confirm/correct/reject 与 decision identity |
| `source_evidence` | 证明来源内容，不自动等于正式事实 | fixture invitation snapshot、原始时间文本 |
| `observation_candidate` | 低权威待确认 | 提取的 company/time/opportunity match |
| `learned_memory` | 低权威辅助理解 | 用户倾向的准备方式；不可覆盖正式安排 |
| `conversation_history` | 历史沟通 | 先前讨论，但不能覆盖更新后的 Canonical State |
| `working_ui_context` | 当前体验指针 | 当前页面、选中的 Opportunity/Interview |
| `runtime_controls` | 本次执行约束 | budget、pending Interaction、cancellation、allowed operations |

发生冲突时，Compiler 不得静默用低权威内容覆盖高权威内容。它应保留冲突、来源和版本，要求 Agent 澄清或调用 Query 获取最新状态。

## 5. VS-01 最小 Package

### 5.1 感知/理解阶段

按需包含：

- 当前用户输入或 fixture Observation identity；
- 当前页面/对象引用；
- 可能匹配的 Opportunity 的最小 Canonical 摘要与版本；
- Source Snapshot 与字段级 Evidence；
- Candidate、缺失、歧义、confidence 与 extractor version；
- 本阶段允许的 Query/Operation schema；
- 当前 actor、Policy 与用户范围。

不得默认包含用户全部岗位、全部邮件、全部历史面试或完整个人档案。

### 5.2 等待 fact confirmation

必须保留：

- pending Interaction id/version/schema；
- owning Turn 与 candidate id/version；
- 待确认 facts、字段来源、冲突和 Opportunity options；
- allowed resolutions；
- 原始用户陈述或 Source reference；
- 本次 decision 的幂等/correlation identity。

普通历史摘要不能替代这些 typed 字段。

### 5.3 Operation 执行前

必须重新编译或读取：

- resolution decision identity；
- candidate 和 source 的 expected versions；
- selected/create Opportunity input；
- 当前 Canonical Opportunity/Interview versions；
- `confirm_interview_invitation@1` schema；
- effect 与 execution-time Policy result；
- idempotency key/fingerprint；
- Verification requirements。

模型历史中的旧对象状态不能作为执行前置条件。

### 5.4 验证与沟通阶段

必须包含 typed Operation result、VerificationResult、最终 object/event references 和失败/恢复状态。Agent 最终沟通只能根据这些结果说“已确认”“未完成”或“正在核对”。

## 6. Source Manifest

每个影响理解、决定或沟通的内容必须能映射到 source manifest：

- source kind；
- source identity/version；
- object owner；
- producer/extractor；
- captured/observed time；
- authority；
- content hash 或 immutable reference；
- sensitivity/redaction；
- validity/expiry；
- deleted/invalidated status。

引用来源的文本片段必须有大小边界。原始邮件、网页或附件中的指令属于不可信数据，不能改变 System Instructions、Permission 或 Tool policy。

## 7. Object Scope 与最小披露

Compiler 必须从当前任务和明确 object references 建立 scope：

1. 优先读取被用户/页面明确选中的 Opportunity；
2. 匹配候选只返回完成 disambiguation 所需字段；
3. 未证明相关时不召回其他公司的敏感沟通；
4. 不跨用户或租户读取；
5. Agent 请求扩大 scope 时必须有明确 reason，并受 Policy 与审计约束；
6. Tool Search/Progressive Disclosure 可以减少 schema 预算，但不能隐藏完成当前任务必需的 Operation。

## 8. Token Budget 与降级顺序

Context Compiler 必须先按语义选择，再做大小控制。预算不足时按以下顺序降级：

1. 移除无关历史与低相关 Learned Memory；
2. 对旧 Tool Result 使用持久化引用与 bounded preview；
3. 对历史对话使用可追溯摘要，并保留摘要覆盖范围/cursor；
4. 缩小 Source 原文，只保留引用片段与 immutable reference；
5. 缩小候选 Opportunity 列表，但显式标记截断；
6. 如果必需事实仍无法容纳，停止模型调用并返回 typed context limit，不得静默丢失关键约束。

## 9. 不可压缩的 VS-01 内容

在当前 Turn 完成前，下列内容不能被 prose summary 替代或清除：

- 当前用户输入及其身份；
- pending Interaction request/resolution；
- candidate id/version 与已确认/corrected facts；
- source/evidence identities；
- selected Opportunity resolution；
- active Operation input、idempotency identity 与 Policy decision；
- active Tool use/result 配对；
- Operation terminal result 与 VerificationResult；
- cancellation/interrupt 与 recovery fence。

旧的 oversized raw payload 可以移出窗口，但必须保留 typed reference 和可按权限读取的耐久内容。

## 10. 页面与 Working Context

UI Context 只表达用户此刻正在看什么和可执行什么，例如：

```text
surface = today | career | interviews | materials | activity | settings
selected_object = {kind, id, version}?
interaction_id?
client_capabilities[]
```

页面名称和路由不能被当成 Domain State。Agent 通过 object reference 发起 Query/Operation；页面重构不应改变业务契约。Copilot 是跨产品层，可在任一 surface 编译对应 Working Context。

## 11. Memory 边界

- Learned Memory 只有与当前邀请理解或准备 handoff 直接相关时才召回；
- Memory 不能改变已确认安排、创建 Opportunity 或解决 Interaction；
- Memory 必须携带 confidence、scope、source 和 invalidation；
- 来源删除或用户纠正后，Compiler 必须停止召回失效版本；
- VS-01 不要求开放自动 Memory producer。

## 12. 可审计性与隐私

Context trace 应能回答：使用了哪些 source/object version、哪些被截断、为何召回、哪些发生冲突、哪些 Operation schemas 被暴露。默认用户界面只显示简洁来源与状态，高级诊断可展开；不得记录明文密钥、OAuth token 或不必要的完整邮件正文。

## 13. 最小评测

VS-01 至少评测：

1. 明确用户陈述不会被降级为 Agent inference；
2. fixture Observation 不会未经确认进入 Canonical State；
3. 同名公司/岗位歧义不会被静默匹配；
4. stale object version 在执行边界被发现；
5. prompt injection 来源不能改变权限或扩大 Tool scope；
6. pending Interaction 在 compact/reconnect 后完整恢复；
7. 无关岗位、邮件和 Memory 不进入最小 Package；
8. 最终沟通只使用 verified result；
9. 删除/失效的 source 不再被召回；
10. 前端路由变化不改变 object-scoped Operation。

## 14. 实施边界

当前 Context Assembly、compaction 与 source acquisition 的物理资产和差距见 [`Career Agent OS Implementation Ledger`](../../implementation/career-agent-os-ledger.md)。本 Contract 不要求一次性重写全部上下文系统；VS-01 只应建立可证明上述不变量的最小 vertical path。
