# Interview Copilot Career Agent OS 初始实施评估

> 状态：非规范性实施评估
> 对应蓝图：[`career-agent-os-blueprint.md`](../architecture/career-agent-os-blueprint.md)
> 初始评估日期：2026-08-25

## 0. 文档用途

本文档保存 Career Agent OS 主蓝图初稿形成时的代码取证、Implementation Gap、旧文档待查点和当前实现冲突。它用于说明“当前实现是什么”和“当前实现与目标架构相差什么”，不定义产品使命、目标语义或架构权威顺序。

当本文档与已批准的 Blueprint、正式 Contract 或已登记架构决策冲突时，以规范文档为准。实现进度应进入 Implementation Ledger，不应通过修改主蓝图表达。

## 1. 初稿检查的当前工程事实

本次没有预先通读旧架构文档或报告。检查范围限于任务允许的代码、迁移、测试、evaluation 和 README。

### 1.1 核心领域模型

检查了：

- `backend/app/models/career_profile.py`
- `backend/app/models/job_opportunity.py`
- `backend/app/models/ability_signal.py`
- `backend/app/models/artifact.py`
- `backend/app/models/interview_record.py`
- `backend/app/models/offer.py`
- `backend/app/models/gmail_observation.py`
- `backend/app/models/long_term_memory.py`
- `backend/app/models/chat.py`
- `backend/app/models/conversation_turn.py`
- `backend/app/models/pending_submission.py`
- `backend/app/models/agent_task.py`
- `backend/app/models/agent_execution.py`
- `backend/app/models/model_dispatch.py`
- `backend/app/models/agent_interaction.py`
- `backend/app/models/persistent_task.py`

已确认的可保护工程资产包括：

- 单用户 CareerProfile owner 与可逐项确认草稿；
- JobOpportunity 当前投影与 append-only ProcessEvent；
- time/provenance 受约束的 NextAction；
- 来源绑定、可 dispute/invalidate/supersede 的 AbilitySignal；
- append-only ArtifactVersion 与精确提交快照；
- Offer 当前条款投影与来源差异确认；
- Gmail Observation 去重、不可变快照与 review card；
- user-level LongTermAgentMemory 与来源边；
- durable Turn、PendingSubmission、AgentTask、ModelDispatch、ToolCall、Interaction 和 PersistentTask/Trigger。

### 1.2 数据库迁移

通过 `python -m alembic heads` 确认当前唯一迁移头为 `0042`。重点检查了：

- `0014_unify_stage0_runtime.py`
- `0015_add_career_domain.py`
- `0016_add_artifacts_and_offers.py`
- `0017_add_persistent_tasks_and_gmail.py`
- `0019_add_agent_tasks.py`
- `0029_unify_resume_artifact_and_ability_projection.py`
- `0030_add_gmail_observations_and_event_cards.py`
- `0031_add_actions_reminders_and_funnel_context.py`
- `0033_add_canonical_agent_memory.py`
- `0037_add_tool_call_audit_ordering.py`
- `0040_add_tool_resource_identities.py`
- `0042_add_interview_transcript_evidence.py`

### 1.3 Agent Runtime 与关键服务

检查了：

- `backend/app/conversation/engine.py`
- `backend/app/conversation/agent_strategy.py`
- `backend/app/services/chat/turn_executor.py`
- `backend/app/services/chat/context_assembly_pipeline.py`
- `backend/app/services/chat/model_dispatch_service.py`
- `backend/app/services/chat/client_action_service.py`
- `backend/app/agent_runtime/tool_policy.py`
- `backend/app/agent_runtime/tool_registry.py`
- `backend/app/agent_runtime/turn_tool_catalog.py`
- `backend/app/agent_runtime/tool_call_executor.py`
- `backend/app/agent_runtime/context_compactor.py`
- `backend/app/agent_runtime/harness_events.py`
- `backend/app/core/model_provider_adapter.py`
- `backend/app/core/llm_tracing.py`
- `backend/app/services/agent_memory_service.py`
- `backend/app/services/persistent_task_service.py`
- `backend/app/services/gmail_observation_service.py`
- `backend/app/services/analytics/telemetry_service.py`

### 1.4 测试与 evaluation

检查了以下测试中的测试名、保护语义和必要断言：

- Turn admission、FIFO、interrupt、waiting、memory scheduling；
- Tool Policy、Tool Call audit、resource fence、late receipt；
- Agent Strategy、completion gate、并行和上下文压力；
- Context slot、current input anchor、compaction 与 grounding；
- CareerProfile、Career Process、NextAction、Artifact、Offer、AbilitySignal；
- PersistentTask、Gmail Observation 与 Long-term Memory；
- 架构 import graph 与 storage contracts；
- `evaluation/career_scenarios.json` 中 18 个跨阶段场景。

基础设施事实来自 `README.md`：FastAPI/React、PostgreSQL、Redis/Celery、Milvus、S3-compatible object storage，以及 Cloud/Community 两种 Edition 共享产品核心。

## 2. Implementation Gap

以下是初稿编制时发现的目标差距，不表示迁移优先级或完成进度。

| ID | Implementation Gap | 当前证据 |
|---|---|---|
| IG-01 | Agent Loop、Turn Kernel 与 Tool Runtime 的物理所有权分散，目标 Harness 边界尚未形成。 | Loop 在 `conversation/agent_strategy.py`，Turn admission/runtime 在 `services/chat/turn_executor.py`，Tool primitives 在 `agent_runtime/`。 |
| IG-02 | 缺少显式 Shared Atomic Application Operation Catalog。 | API 和 Agent Tool 分别直接 import 多个 `app.services` 模块。 |
| IG-03 | Tool Adapter 中仍含有大块领域编排，未保持薄适配器。 | `agent_runtime/tools/career_domains.py`、`career.py` 均超过千行并直接依赖具体 services。 |
| IG-04 | 当前 NextAction 仍允许 `suggested` 和 `agent_suggestion`，与“建议不是 Next Action”冻结原则冲突。 | `models/job_opportunity.py` 与迁移 `0031`；服务测试只阻止建议直接成为 planned，仍保留 suggested 记录。 |
| IG-05 | 当前 Artifact 支持将普通消息显式 promotion/save 为 Artifact，与“只有明确要求文件格式才创建 Artifact”冻结原则冲突。 | `models/artifact.py` 的 `message_promotion` 及 `test_artifact_service.py`。 |
| IG-06 | 当前 Harness Event 只覆盖 status/source/tool/text/interaction/budget/error/done，不能完整表达冻结 Agent 循环和 Operation verification。 | `agent_runtime/harness_events.py`。 |
| IG-07 | Client Action Protocol 当前主要绑定 Mock Interview，尚不是通用 typed product client action。 | `services/chat/client_action_service.py`。 |
| IG-08 | Observation 当前有成熟 Gmail 特化实现，但缺少目标中的 Calendar 与 provider-neutral observation/application 边界。 | `models/gmail_observation.py`、`gmail_observation_service.py`；核心模型中无 Calendar owner。 |
| IG-09 | Canonical Long-term Memory 已存在且 producer 默认关闭，但旧 MemoryDocument/MemoryAbilityState/MemoryAuditEntry 仍保留在运行模型注册和迁移测试中。 | `models/long_term_memory.py`、三类 legacy model、`legacy_memory_migration.py`。 |
| IG-10 | Context 已有 slot、稳定/动态分区、usage 与 cache 支持，但尚未形成覆盖冻结六类资产和权威标记的正式 Context Package Contract。 | `context_assembly_pipeline.py`、`model_provider_adapter.py`。 |
| IG-11 | 当前 Policy 是成熟的参数级 effect policy，但仍以 Tool execution 为中心，尚未与统一 Operation Contract 和 Verification Contract 绑定。 | `agent_runtime/tool_policy.py`、`tool_call_executor.py`。 |
| IG-12 | 当前有 JSONL interaction metrics、cache/token telemetry 和可选 LangSmith tracing，但缺少 provider-neutral 的端到端 Operation/Verification/blocked-on-user trace。 | `services/analytics/telemetry_service.py`、`core/llm_tracing.py`。 |
| IG-13 | 架构测试保证无环，但没有为 `app.agent_runtime` 和 `app.conversation` 定义目标向内依赖规则。 | `tests/test_architecture/test_import_boundaries.py`。 |
| IG-14 | 多个核心模块过大且混合职责，增加迁移和验证风险。 | Career process、Agent strategy、Turn executor、PersistentTask、Tool executor、Career tools 等超过千行。 |
| IG-15 | 当前 evaluation manifest 仍把旧蓝图和旧 Stage Spec 作为 architecture source，并冻结了当前工作区/页面投影。 | `evaluation/career_scenarios.json`。 |
| IG-16 | 当前 Conversation 暴露 `chat`/`agent` 双 strategy 模式；目标统一自然语言 Copilot 下的内部 strategy routing 尚未定义。 | `models/chat.py`、`conversation/engine.py`。 |
| IG-17 | 生产 Resume owner 已向 Artifact 收敛，但 legacy Resume 模型和读取路径仍存在。 | `models/resume.py`、`artifact_resume_states` 与相关 services。 |
| IG-18 | 当前架构没有完整的 Domain/Harness/Experience 三类事件与 schema version 体系。 | 现有 Harness SSE 事件和 Domain 模型事件各自存在，但无统一协议契约。 |
| IG-19 | 当前没有由 Memory Runtime 长期聚合同一能力多个 AbilitySignal 的专门 Learned Memory `AbilityUnderstanding`。 | 当前模型只有 `AbilitySignal` 与通用 `LongTermAgentMemory`，没有 AbilityUnderstanding owner 或聚合契约。 |
| IG-20 | 当前 AbilitySignal 持久化数值 `score`，尚未符合“分数、雷达图和趋势值仅为可重算 View Projection”的冻结决定。 | `backend/app/models/ability_signal.py` 及相关迁移和测试。 |
| IG-21 | 当前前端尚未形成由 AbilityUnderstanding、AbilitySignal、Evidence 和趋势共同组成的 AbilityProfile 投影。 | 现有能力展示与当前 API/schema 尚未定义该投影契约。 |

## 3. 需要按需查阅旧文档的位置

本次没有读取旧架构文档正文。后续编写正式契约时，以下位置可能需要按规则查阅相关片段，以避免丢失当前复杂不变量的设计理由：

1. Turn terminalization、selected interrupt、admission hold 和 Conversation deletion 的完整竞态理由；
2. Attachment draft/claim/revoke/permanent deletion 与 Source coverage 的边界；
3. Interview audio word evidence、结构投影和 QA provenance 的完整算法约束；
4. Provider-native Prompt Cache 物理分区的安全理由；
5. Gmail OAuth broker、credential ownership 和 live connector release 条件；
6. History Search 与 canonical Interaction Record 的精确边界；
7. Cloud/Community Edition 的已冻结部署权限矩阵。

只有与当前已批准 Blueprint、已登记架构决策和正式 Contract 一致，且仍有代码、测试或明确产品决定支持的内容，才能进入后续规范文档。

## 4. 与冻结决定的真实冲突

初稿编制发现三项当前实现与冻结决定存在直接语义冲突：

1. **NextAction 冲突**：当前模型允许 Agent suggestion 成为 `suggested` NextAction；冻结决定要求建议不是 Next Action，只有用户创建、外部明确要求或用户接受建议后才形成 Next Action。
2. **Artifact 冲突**：当前实现允许普通消息通过显式保存/promotion 成为 Artifact；冻结决定要求只有用户明确要求生成文件格式时才创建 Artifact。
3. **Ability 投影冲突**：当前实现将数值 `score` 持久化在 AbilitySignal 上；冻结决定要求 AbilitySignal 只表达局部、带 Evidence 的能力观察，长期理解由 Memory Runtime 聚合为 AbilityUnderstanding，分数、雷达图和趋势值只作为可重新计算的 View Projection。

此外存在一项规范引用冲突：当前 evaluation manifest 仍引用旧蓝图作为 architecture source。它不改变目标产品语义，但后续必须在独立 evaluation contract 中重新绑定。

除上述项目外，本次检查到的 Durable Turn、Policy、append-only history、Observation、Memory 低权威、Evidence 与用户确认等核心工程不变量，与冻结决定没有发现真实冲突。
