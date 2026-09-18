# Interview Copilot Career Agent OS Capability Coverage Map

> 状态：非规范性产品覆盖与实施规划草案  
> 对应蓝图：[`career-agent-os-blueprint.md`](../architecture/career-agent-os-blueprint.md)  
> 当前实现评估：[`career-agent-os-initial-assessment.md`](career-agent-os-initial-assessment.md)  
> 编制日期：2026-08-26

## 0. 文档契约

本文档回答四个问题：

1. 为实现已批准的 Career Agent OS 蓝图，完整产品能力范围是什么；
2. 哪些能力必须共享，不能分别为 UI、Agent 和 Automation 建三套实现；
3. 当前工程资产能够复用到哪里，目标能力仍缺什么；
4. 应按什么垂直切片顺序重建，才能持续交付完整业务闭环。

本文档不是 Product Blueprint、Operation Contract、Vertical Slice Spec 或 Implementation Ledger。它不冻结接口、表结构、路由、组件或排期，也不把“当前已存在”解释为“符合目标架构”。产品语义以已批准蓝图为准；尚未由蓝图裁定的问题统一标记为 **Product Decision Required**。

本阶段仅检查当前代码、测试和 evaluation 以确认实现事实，没有修改业务代码、数据库、迁移、测试或 evaluation。

---

## 1. 覆盖方法

### 1.1 当前实现证据分类

本地图使用以下证据分类，描述当前资产与目标能力的关系，而不是汇报实施进度：

| 分类 | 含义 |
|---|---|
| `Reusable` | 已有实现包含可保留的正确领域不变量或运行时能力，但仍需通过正式 Operation/Contract 接入目标架构。 |
| `Partial` | 已覆盖部分状态、入口或流程，尚未形成目标闭环。 |
| `Conflicting` | 已有能力与已批准蓝图存在真实语义冲突，不能原样保留。 |
| `Experience Mock` | 只有界面、演示数据或本地交互，没有权威后端状态与执行链。 |
| `Missing` | 当前没有可证明的目标 owner、契约或端到端能力。 |

一项能力可以同时拥有多种分类，例如后端领域模型 `Reusable`，而当前前端仍是 `Experience Mock`。

### 1.2 垂直切片定义

本路线中的 Vertical Slice 必须：

- 从一个真实用户目标开始，以用户可验证的业务结果结束；
- 同时贯穿 Adaptive Experience、Agent Harness、Shared Application Operations 与 Career Domain Kernel；
- 覆盖 UI 直接操作与自然语言 Agent；涉及主动运行时再覆盖 Automation；
- 明确事实来源、确认、幂等、失败、恢复、验证和审计；
- 用场景评测证明业务闭环，而不是只证明接口存在；
- 在切片结束时删除或封闭被替代的重复路径，避免新旧双轨无限共存。

不把“先重写整个 Harness”“先整理全部目录”或“先完成所有页面”作为独立垂直切片。共享基础能力在首个需要它的业务切片中建立，后续切片复用并加固。

### 1.3 验收门禁代码

| Gate | 验收主题 | 最低要求 |
|---|---|---|
| `G-DOMAIN` | 领域真实性 | owner、状态机、Evidence、修正和投影满足蓝图不变量。 |
| `G-OPS` | 操作一致性 | UI、Agent、Automation 通过同一 Atomic Operation 语义执行；幂等、版本和 typed failure 可验证。 |
| `G-HARNESS` | 执行可靠性 | Turn、Tool/Operation Call、waiting、interrupt、retry、resume 和 terminal state 可恢复。 |
| `G-TRUST` | 权限与外部真实性 | 参数级 Policy、Approval、receipt/read-back、unknown 与 reconciliation 正确。 |
| `G-EXPERIENCE` | 用户体验闭环 | 直接 UI 可完成；Copilot 携带 typed context；状态、确认、证据和失败可见。 |
| `G-EVIDENCE` | 来源与学习 | Source/Evidence 可追溯，Memory/Ability 不覆盖 Canonical State，删除传播正确。 |
| `G-OBSERVE` | 可观察性与评测 | Trace 可按 Turn/Task/Operation 关联，端到端场景和确定性不变量进入 release gate。 |
| `G-EXIT` | 旧路径退出 | 新读写路径、回填、回归和场景门禁完成后，旧 owner、重复 UI/API/Tool 和兼容写入被删除或隔离。 |

---

## 2. 全产品覆盖总览

完整产品不是四个页面与一个聊天入口的集合，而是以下连续能力链：

```text
职业身份与方向
→ 机会发现与跟踪
→ 多流程事实与真实行动
→ 面试邀请、准备、训练与复盘
→ 材料生成与精确提交
→ Offer 与决策
→ 沟通、观察与主动推进
→ 能力理解和长期求职记忆
→ 下一轮更高质量行动
```

`今天`、`求职`、`面试`、`资料`、`活动中心`和`设置`是这套能力的产品投影；Copilot 是贯穿所有投影的自然语言交互与执行层。它们不拥有第二套业务状态。

---

## 3. Shared Foundation Coverage

这些基础能力不是先行建设的独立平台项目，而是每个垂直切片必须共同使用的“产品脊柱”。

| ID | Shared Foundation | 目标职责 | 当前可复用资产 | 主要差距 | 首次建立 / 加固切片 | 验收门禁 | 退出条件 |
|---|---|---|---|---|---|---|---|
| SF-01 | Identity、Ownership 与 Edition | 统一 user/tenant owner、连接身份、actor 和 Edition 能力边界。 | Auth、`User`、owner-scoped models、`core/edition.py`、安全与 edition 测试。 | Operation actor/owner 仍未形成统一契约；Cloud/Community 数据治理默认值未冻结。 | VS-01 建立；所有切片加固 | G-DOMAIN, G-OPS | 所有正式 Operation 都执行 owner/actor 检查，旧的隐式 user 传递被消除。 |
| SF-02 | Atomic Operation Registry | 为 UI、Agent、Automation 提供唯一业务执行边界、schema、effect、幂等与 verification metadata。 | 多个成熟 domain services；API 与 Tool 已覆盖大量命令。 | 缺少正式 Operation Catalog；API/Tool 直接编排 services；Tool Adapter 过重（IG-02、IG-03）。 | VS-01 | G-OPS, G-EXIT | 目标能力全部由 Operation Registry 暴露，重复业务规则和宏 Tool 被删除。 |
| SF-03 | Canonical State、Domain Event 与 Evidence | 维护唯一事实 owner、append/retract/supersede、source/version 和可重建投影。 | CareerProfile、JobOpportunity、ProcessEvent、Interview、Artifact、Offer、AbilitySignal 等模型及密集测试。 | 缺少统一 Domain/Harness/Experience event envelope 与 schema version（IG-18）；部分 owner 仍双轨。 | VS-01、VS-02 | G-DOMAIN, G-EVIDENCE | 每个写 Operation 发出 typed Domain Event；旧直接写和重复 owner 退出。 |
| SF-04 | Source Asset、File 与 Retrieval | 接收文件/网页/邮件/音频，保存真实 source/version，按 scope 检索并传播删除。 | FileAsset、attachment ingress/source、knowledge/RAG、JD snapshot、transcript evidence。 | Source concern 分散；legacy attachment 路径仍在；Artifact promotion 语义冲突（IG-05）。 | VS-01 建最小 source；VS-07 完整化 | G-EVIDENCE, G-EXIT | Source 与 Artifact 完全分离；旧附件/Resume 读写迁移完成。 |
| SF-05 | Durable Turn Kernel | 统一 PendingSubmission、Turn admission、waiting/resume、interrupt/cancel、dispatch fence 和可重连事件流。 | `PendingSubmission`、`ConversationTurn`、`turn_executor.py`、SSE、恢复与并发测试。 | Harness 物理 owner 分散（IG-01）；核心模块过大（IG-14）。 | VS-01 | G-HARNESS, G-OBSERVE | 新 Harness boundary 成为唯一执行入口；旧 chat/conversation 分散 owner 被迁移。 |
| SF-06 | Model Runtime 与 Context Compiler | Provider-neutral 模型调用；按任务编译六类 Data Assets；预算、cache、compaction 不丢失原始目标。 | Model dispatch/provider adapter、context pipeline、context compactor、usage/cache 测试。 | 没有正式 Context Package schema 与权威标记（IG-10）；strategy routing 未冻结（IG-16）。 | VS-01 最小包；VS-02/VS-06 加固 | G-HARNESS, G-EVIDENCE | 所有模型请求消费 typed Context Package；临时 prompt 拼接不再承担事实 owner。 |
| SF-07 | Tool / Operation Discovery 与 Thin Adapters | 按任务、权限、Edition、连接状态披露能力；Tool 仅适配 Operation。 | Tool registry、per-turn catalog、Skills、MCP、渐进披露与 schema 测试。 | Registry surface 重复；Career Tool 含领域编排；现有 compactable tool 选择未按 Career 负载重估。 | VS-01、VS-03 | G-OPS, G-HARNESS | Domain Tool 全部变为薄 adapter；宏能力只作为 Skill/Plan/Recipe。 |
| SF-08 | Policy、Interaction、Verification 与 Reconciliation | 按 effect 和具体参数决定 allow/ask/deny；持久确认；对本地和外部结果验证。 | 六级 Tool effect policy、AgentInteraction、ToolCall audit、receipt refs、resource fence。 | Policy 仍以 Tool 为中心，未绑定 Operation/Verification Contract（IG-11）；Verification owner 未冻结。 | VS-01 | G-TRUST, G-HARNESS | 所有副作用在 dispatch 前获得可解释决定；unknown 资源被 fence 并可 reconciliation。 |
| SF-09 | Observation 与 Proactivity Runtime | 摄取 provider observation、去重、匹配、确认、触发、预算、暂停与 schedule repair。 | Gmail Observation、PersistentTask、Trigger、reminder、Celery beat、maintenance sweeps。 | 仅 Gmail 特化；无 Calendar/provider-neutral 应用边界（IG-08）；主动预算未冻结。 | VS-01 fixture；VS-09 完整化 | G-DOMAIN, G-TRUST, G-OBSERVE | Connector 只产 Observation；所有正式变化经 Operation；自动化可暂停、删除和审计。 |
| SF-10 | Memory Runtime 与 Ability Understanding | 低权威记忆候选、召回、冲突、失效、删除；聚合 AbilitySignal 为 AbilityUnderstanding。 | LongTermAgentMemory、settings、source refs、producer gate、AbilitySignal。 | 无 AbilityUnderstanding；数值 score 持久化冲突；legacy memory owner 残留（IG-09、IG-19～21）。 | VS-02 建 Memory governance；VS-06 建 Ability | G-EVIDENCE, G-OBSERVE, G-EXIT | AbilityUnderstanding 可重算；legacy memory 和永久能力分数退出；删除不复活。 |
| SF-11 | Experience Event、Projection 与 Client Action | 用 typed event 投影 Agent 状态、Today、Activity、对象上下文和客户端动作。 | Harness SSE、InteractionCard、ClientActionBridge、object reference handoff。 | Harness event 不覆盖完整循环（IG-06）；Client Action 主要绑定 Mock（IG-07）；新页面投影断裂。 | VS-01 | G-EXPERIENCE, G-HARNESS | 前端不解析文本推断执行状态；所有关键跳转有 typed target/ack。 |
| SF-12 | Observability、Evaluation 与 Data Governance | Turn/Task/Operation trace、成本/延迟、场景门禁、导出/删除/保留和架构边界。 | 大量 backend tests、career scenario gate、RAG eval、telemetry、architecture tests。 | Trace 不完整（IG-12）；evaluation 仍绑定旧蓝图（IG-15）；目标 import boundary 未建立（IG-13）；保留政策开放。 | VS-01 建新场景骨架；持续加固 | G-OBSERVE, G-EXIT | 新蓝图场景成为唯一 release manifest；旧 Stage 绑定退出；数据治理策略可执行。 |

---

## 4. Product Capability Coverage

### 4.1 职业身份、方向与个性化

| ID | Product Capability | 用户价值 | Target Owner | 当前资产与证据 | Implementation Gap | Planned Slice | Foundations | Acceptance Gate | Migration / Deletion Condition |
|---|---|---|---|---|---|---|---|---|---|
| PC-01 | Career Profile 正式事实与职业方向 | Agent 和用户始终基于可修正的真实职业身份工作。 | CareerProfile / Direction | 模型、draft/candidate、API、`CareerProfilePage`、service/API/frontend tests；`Reusable`。 | UI/API/Tool 尚未统一 Operation；legacy Resume 仍是读取 owner 之一（IG-02、IG-17）。 | VS-02 | SF-01～03, SF-10～11 | G-DOMAIN, G-OPS, G-EXPERIENCE | Profile Operation 和 Projection 全量切换；legacy Resume owner 仅保留迁移读取后删除。 |
| PC-02 | Source → Profile Candidate → 确认/拒绝/冲突 | 从简历、对话和资料提取信息，同时不让推断污染正式档案。 | CareerProfile Candidate / Draft | Profile draft/candidate workflow、resume extraction、attachment source；`Partial`。 | 缺少统一 Source/Evidence 与 Operation flow；当前入口分散。 | VS-02 | SF-02～06, SF-11 | G-DOMAIN, G-EVIDENCE, G-EXPERIENCE | 所有提取先进入 candidate；任何直接把模型提取写成 Profile 的路径退出。 |
| PC-03 | 偏好、Learned Memory 与提升为正式偏好 | Agent 长期理解用户，同时用户可查看、修正、删除并控制记忆。 | Canonical Preference + Learned Memory | Copilot preference、LongTermAgentMemory、Memory settings/UI；`Partial`。 | 提升为 Canonical Preference 的 Operation/体验、保留期和敏感类别未冻结；legacy memory 残留。 | VS-02，VS-10 完整治理 | SF-01～03, SF-06, SF-10, SF-12 | G-EVIDENCE, G-TRUST, G-EXIT | 新 Memory Contract 与用户控制生效；legacy models/migration 路径完成使命后退出。 |

### 4.2 机会发现、多流程与行动

| ID | Product Capability | 用户价值 | Target Owner | 当前资产与证据 | Implementation Gap | Planned Slice | Foundations | Acceptance Gate | Migration / Deletion Condition |
|---|---|---|---|---|---|---|---|---|---|
| PC-04 | 岗位发现、搜索与研究 | 基于职业方向发现适合机会，并看到来源、匹配依据和新鲜度。 | Discovery Result / Source Projection；被跟踪后才是 JobOpportunity | Web/jobs tools、JD capture、RAG；`Partial`。 | 未跟踪结果的 owner、持久化、去重、过期未冻结；当前没有完整发现体验（CMG-06）。 | VS-03 | SF-01～04, SF-06～07, SF-12 | G-EVIDENCE, G-EXPERIENCE, G-OBSERVE | 新 discovery lifecycle 生效；临时搜索结果不得被误写为正式流程。 |
| PC-05 | 跟踪、编辑、关联方向与机会去重/合并 | 将值得争取的岗位安全纳入用户级多流程管理。 | JobOpportunity / Merge / DirectionLink | 丰富模型、service/API、merge、JD snapshot、旧 `CareerProcessPage`；`Reusable`。 | 新 `CareerPage` 只覆盖浅层 CRUD，完整页被孤立；Agent/API 未共享 Operation（CMG-02、IG-02）。 | VS-03 | SF-01～03, SF-11 | G-DOMAIN, G-OPS, G-EXPERIENCE | 单一求职工作区与 Operation 路径上线；重复 Career 页面和旧写入口删除。 |
| PC-06 | Process Event 时间线、状态投影与修正 | 准确知道每个流程发生了什么，并能修正错误而不伪造历史。 | ProcessEvent + JobOpportunity Projection | append-only event、sequence、source、retraction、phase/outcome constraints；`Reusable`。 | 通用 Domain Event envelope 和跨入口 Operation 尚缺；当前新 UI 未完整呈现。 | VS-01 建邀请事件；VS-04 完整化 | SF-02～03, SF-11～12 | G-DOMAIN, G-OPS, G-OBSERVE | 所有状态从有效事件重建；任何原地改写历史或 UI 私有阶段退出。 |
| PC-07 | Recommendation / Proposal 生命周期 | Agent 可提出有依据的建议，但在用户接受前不制造正式任务。 | Recommendation Projection 或专门 owner（待决定） | Agent 文本与部分 insight 能力；`Missing/Conflicting`。 | 生命周期和反馈模型开放；当前 suggested NextAction 与蓝图冲突（IG-04）。 | VS-04 | SF-02～03, SF-06, SF-11 | G-DOMAIN, G-EXPERIENCE | 新 Recommendation 机制覆盖场景后，`NextAction.status=suggested` 与 `agent_suggestion` 写入被迁移/删除。 |
| PC-08 | 真实 Next Action、提醒与 Action Target | 把已经成立的行动放入日程，并直接进入完成它的业务上下文。 | NextAction；Reminder 是投影 | NextAction 强约束模型、plan/complete/close API、reminder service；`Partial/Conflicting`。 | 建议和行动混存；新 Career CTA 是 toast；Action Target/Client Action 未贯通。 | VS-04 | SF-02～03, SF-08, SF-11 | G-DOMAIN, G-OPS, G-EXPERIENCE | suggested 记录迁出；所有 NextAction 来源真实且点击进入 typed target。 |
| PC-09 | 求职策略、漏斗、风险与跨流程洞察 | 从多个流程中理解整体局面并决定关注方向。 | Rebuildable Projection / Recommendation | Funnel analysis、agenda/reminder/offer compare API、analytics page；`Partial`。 | 当前洞察入口孤立；Recommendation 与事实/行动边界未统一。 | VS-04 | SF-03, SF-06, SF-11～12 | G-DOMAIN, G-EXPERIENCE, G-OBSERVE | 洞察仅消费权威状态并可回到证据；旧孤立 projection 入口合并或退出。 |
| PC-10 | Today 四类议程投影 | 一眼看到真实下一步、待确认、求职动态和 Copilot 动态。 | Projection only | 新 `TodayPage` 视觉壳；`Experience Mock`。 | `SEED_TASKS`、假公司 fallback、本地 confirm；未绑定 Interaction/NextAction/Activity（CMG-01）。 | VS-01 提供邀请确认；VS-04 完整四象限 | SF-03, SF-08～12 | G-EXPERIENCE, G-OBSERVE | 所有 seed/fallback 删除；空账号保持真实空状态；四类内容来自权威 owner。 |

### 4.3 面试生命周期与能力成长

| ID | Product Capability | 用户价值 | Target Owner | 当前资产与证据 | Implementation Gap | Planned Slice | Foundations | Acceptance Gate | Migration / Deletion Condition |
|---|---|---|---|---|---|---|---|---|---|
| PC-11 | 面试邀请摄取、匹配、修正、确认与拒绝 | 从手动输入、自然语言或外部邀请可靠建立真实面试流程。 | Observation Candidate + Interview + ProcessEvent | Gmail Observation、JobOpportunity、InterviewRecord、Interaction；`Partial`。 | 没有统一 invitation Operation；无 Calendar owner；新 Interview Hub 无数据。 | VS-01 | SF-01～12（最小纵贯） | 全部门禁 | 新确认链成为唯一入口；任何直接从邮件/模型写 Interview/Process 的路径退出。 |
| PC-12 | 面试准备工作区 | 结合精确 JD、简历版本、流程阶段和历史弱项制定并执行准备。 | Interview Context Projection + AgentTask/Recommendation/NextAction | JD/resume snapshots、career context tools、chat object refs；`Partial`。 | 当前 Hub 的 prompt CTA 丢失；无 typed preparation workspace/plan contract。 | VS-01 只做 handoff；VS-05 完整化 | SF-02～08, SF-10～11 | G-OPS, G-HARNESS, G-EXPERIENCE | 通用 prompt query handoff 删除；所有准备入口携带 Interview/Opportunity identity。 |
| PC-13 | 模拟面试完整生命周期 | 针对目标或通用方向进行可恢复的训练、语音互动和结束复盘。 | MockInterviewRuntime + InterviewRecord | Mock API/service/runtime、TTS、ClientAction、完整 UI/tests；`Reusable/Partial`。 | 尚未通过 Shared Operations；Client Action 与 mock 强耦合；Hub 只是旧页嵌套。 | VS-05 | SF-02～08, SF-11～12 | G-HARNESS, G-EXPERIENCE, G-OBSERVE | Mock 状态与正式记录边界通过 Contract 固定；旧嵌套入口收敛。 |
| PC-14 | 真实面试 Source、转录与结构化证据 | 将录音/视频可靠变成可回溯的转录和问答证据。 | FileAsset / Transcript / InterviewSourceRef / InterviewQA | ASR、speaker evidence、immutable provenance、analysis worker、密集 tests；`Reusable`。 | Source 管线分散；新面试 IA 未提供完整记录入口；需接新 Operation/Event。 | VS-06 | SF-02～06, SF-12 | G-EVIDENCE, G-HARNESS, G-OBSERVE | 新 source/analysis operation 成为唯一入口；旧 attachment 特例迁移。 |
| PC-15 | 面试复盘、问答修正与成长建议 | 看见真实问答、证据、表现与下一次可采取的改进。 | Interview Record/QA/Debrief Projection + Recommendation | Review/QAPanel、analysis、QA edit、guidance、knowledge save；`Reusable/Partial`。 | 大型旧页面与新 Hub 未融合；建议与 NextAction 仍需正确分离。 | VS-06 | SF-02～07, SF-10～12 | G-EVIDENCE, G-EXPERIENCE, G-OBSERVE | 复盘所有判断可回证据；普通建议不创建 NextAction/Artifact。 |
| PC-16 | AbilitySignal → AbilityUnderstanding → AbilityProfile | 从多次真实证据形成可修正、可重算的长期能力理解。 | AbilitySignal + Learned Memory AbilityUnderstanding + View Projection | AbilitySignal、source refs、dispute API、Growth UI；`Partial/Conflicting`。 | 无 AbilityUnderstanding；score 被持久化为事实；前端无目标投影（IG-19～21）。 | VS-06 | SF-03, SF-06, SF-10～12 | G-EVIDENCE, G-OBSERVE, G-EXIT | 聚合/重算和用户异议闭环上线；永久 score/radar owner 与旧 Growth 投影退出。 |

### 4.4 资料、来源与文件交付物

| ID | Product Capability | 用户价值 | Target Owner | 当前资产与证据 | Implementation Gap | Planned Slice | Foundations | Acceptance Gate | Migration / Deletion Condition |
|---|---|---|---|---|---|---|---|---|---|
| PC-17 | Source Library、检索、引用与删除 | 统一管理简历、JD、网页和参考资料，并让 Agent 只读取有范围来源。 | FileAsset / KnowledgeDocument / Source-specific owner | Library、uploads、knowledge/RAG、attachment sources、deletion services；`Reusable/Partial`。 | 多套 source owner 与入口；Materials 只是旧页 wrapper；删除传播需统一。 | VS-02 提供 Profile source；VS-07 完整化 | SF-01～07, SF-12 | G-EVIDENCE, G-EXPERIENCE, G-EXIT | Source identity、scope、deletion contract 统一；重复附件/knowledge 特例退出。 |
| PC-18 | 明确文件请求的 Artifact 生成、版本、编辑与导出 | 只有在用户要求文件时生成可交付、可版本化材料。 | Artifact / ArtifactVersion | Artifact model/service/API/page、append versions、archive；`Reusable/Conflicting`。 | `/from-message` 与 message promotion 违反蓝图；格式、异步状态和编辑导出契约开放（IG-05）。 | VS-07 | SF-02～08, SF-11～12 | G-DOMAIN, G-OPS, G-EXPERIENCE | 显式文件意图成为创建前置条件；message promotion 和隐式保存入口删除。 |
| PC-19 | Artifact 与岗位关联、精确提交和 receipt | 区分“相关材料”与“实际提交的精确版本”。 | ArtifactJobRelation / SubmissionSnapshot | 关联与 submitted API、immutable snapshot、tests；`Reusable`。 | 尚未纳入统一 external verification；缺少完整提交体验。 | VS-07 | SF-02～04, SF-08, SF-11 | G-DOMAIN, G-TRUST, G-EVIDENCE | 所有“已提交”记录固定 version 与依据；无 receipt 的 UI 文案不得宣称完成。 |

### 4.5 Offer 与职业决定

| ID | Product Capability | 用户价值 | Target Owner | 当前资产与证据 | Implementation Gap | Planned Slice | Foundations | Acceptance Gate | Migration / Deletion Condition |
|---|---|---|---|---|---|---|---|---|---|
| PC-20 | Offer 摄取、条款来源、补充、替换与冲突 | 将口头、书面和外部观察形成可核对的当前条款。 | Offer + source/evidence | Offer model/service/API、term diff、analysis；`Reusable/Partial`。 | 新求职 IA 未整合；Observation/Operation 入口不统一。 | VS-08 | SF-02～09, SF-11 | G-DOMAIN, G-OPS, G-EVIDENCE | 所有条款保留来源；静默覆盖和 UI 私有 offer 状态退出。 |
| PC-21 | Offer 比较、决策材料与接受/拒绝 | 比较多个流程并记录用户真实决定，而不是让 Agent 替用户决定。 | Comparison Projection / Artifact（仅明确请求）/ ProcessEvent | Offer analysis、compare API、OfferPage；`Partial`。 | 比较作为 Skill 尚未按原子 Operation 组合；决定体验与外部动作验证未闭环。 | VS-08 | SF-02～08, SF-11～12 | G-DOMAIN, G-TRUST, G-EXPERIENCE | decision 只写 ProcessEvent；Offer 不再拥有隐藏 decision；旧孤立页面收敛。 |

### 4.6 沟通、外部行动与主动 Career Loop

| ID | Product Capability | 用户价值 | Target Owner | 当前资产与证据 | Implementation Gap | Planned Slice | Foundations | Acceptance Gate | Migration / Deletion Condition |
|---|---|---|---|---|---|---|---|---|---|
| PC-22 | 邮件/日历/平台 Observation 与通信索引 | 自动发现真实流程变化，同时保持来源与事实确认边界。 | Connector-owned Source/Observation + optional Projection | Gmail OAuth/connector/observation/cards；`Reusable/Partial`。 | 无 Calendar；provider-neutral ingress 与统一通信 Projection 待决定（IG-08、CMG-07）。 | VS-01 fixture；VS-09 provider integration | SF-01～04, SF-08～09, SF-12 | G-DOMAIN, G-EVIDENCE, G-OBSERVE | Provider 写入只形成 Observation；旧 Gmail-to-domain 特化编排改走统一 Operation。 |
| PC-23 | 外部邮件、日历和平台动作 | 在明确授权下起草、发送、安排、更新，并如实验证结果。 | External Action Execution + provider receipt | Gmail tool/connector、outbox、Tool effect policy；`Partial`。 | Calendar 缺失；外部写验证与预授权目录未冻结。 | VS-09 | SF-02, SF-05～09, SF-12 | G-TRUST, G-HARNESS, G-OBSERVE | 所有 external write 有 receipt/read-back/unknown；直接 provider 调用退出。 |
| PC-24 | PersistentTask、Trigger、提醒与主动推进 | Agent 在用户授权范围内持续观察、跟进并可随时暂停。 | PersistentTask / Trigger / Turn | 丰富 model/service/API/UI、Celery schedule、repair tests；`Reusable/Partial`。 | 未贯穿统一 Operation、主动预算和全产品 Activity；任务页仍为旧设计。 | VS-09 | SF-01～02, SF-05～12 | G-TRUST, G-HARNESS, G-OBSERVE | 所有自动化有 scope、budget、pause/delete；无意义建议不生成自动化。 |
| PC-25 | Activity Center、等待、验证、失败、恢复与审计 | 看见 Agent/Automation 正在做什么、卡在哪里以及如何继续。 | Harness/Execution Projection | PersistentTasksPage、Tool audit、history、SSE；`Partial`。 | `ActivityCenterPage` 只是 5 行 alias；没有跨 Turn/Task/Operation 统一投影（CMG-04）。 | VS-01 提供 slice activity；VS-09 完整化 | SF-05, SF-08～12 | G-EXPERIENCE, G-OBSERVE | Activity 成为统一 projection；别名壳和孤立 audit 页面被合并或退出。 |

### 4.7 跨产品 Copilot、控制与治理

| ID | Product Capability | 用户价值 | Target Owner | 当前资产与证据 | Implementation Gap | Planned Slice | Foundations | Acceptance Gate | Migration / Deletion Condition |
|---|---|---|---|---|---|---|---|---|---|
| PC-26 | 跨产品 Copilot 与 typed object context | 在任何业务对象旁用自然语言理解、操作、解释和验证。 | Harness Turn + Working/UI Context | GeneralChat/ChatPanel、object reference handoff、SSE、tools；`Partial`。 | Today/Interview 发出 `?prompt=` 但 GeneralChat 不读取；Copilot 仍像独立页面，未成为跨产品层（CMG-03）。 | VS-01 建对象 handoff；每个 slice 扩展 | SF-02, SF-05～08, SF-11～12 | G-OPS, G-HARNESS, G-EXPERIENCE | 任意入口携带 typed object/context；prompt-string 跳转和页面私有 agent 规则退出。 |
| PC-27 | AgentTask、计划、执行进度与恢复 | 对复杂目标看到计划、完成条件和真实进展，不把计划当业务任务。 | AgentTask / Revision + Turn | AgentTask models/service/tool/card、completion gate；`Reusable/Partial`。 | 计划表达与 strategy routing 开放；Event 未覆盖完整 Harness 循环。 | VS-01 最小计划可选；VS-05/VS-09 加固 | SF-05～08, SF-11～12 | G-HARNESS, G-EXPERIENCE, G-OBSERVE | AgentTask 不承载 NextAction/queue/audit；进度完全由 typed execution state 驱动。 |
| PC-28 | 设置、连接、模型、权限、通知、Memory 与自动化策略 | 用户统一控制 Agent 能力、数据、费用、主动性和外部连接。 | User settings / Integration accounts / Policy | Settings modal、旧 personalization/models/capabilities pages、provider/MCP/skill APIs；`Partial`。 | 两套设置体验重复；modal 声明的 capabilities tab 未呈现；数据治理默认值开放（CMG-05）。 | VS-10；前置切片按需接入 | SF-01, SF-08～12 | G-TRUST, G-EXPERIENCE, G-EXIT | 单一设置 IA 和 owner 生效；重复 routes/forms/stores 删除；撤销授权即时传播。 |

### 4.8 覆盖完整性检查

| 产品使命动词 | 被覆盖的能力 |
|---|---|
| 长期理解用户 | PC-01～03、PC-16、PC-26～28 |
| 寻找机会 | PC-04～05、PC-09 |
| 管理多个求职流程 | PC-05～10、PC-20～21 |
| 准备和完成关键行动 | PC-07～08、PC-12、PC-18～19、PC-23～24 |
| 面试训练与复盘 | PC-11～16 |
| 安全、持续推进 | PC-22～28 与 SF-05～12 |

没有任何产品能力可以只分配给 Agent。PC-01～25 必须至少拥有直接 UI 路径；适合自然语言表达的能力同时拥有 Agent Adapter；只有具备明确 Trigger、scope 和预算的能力才进入 Automation。

---

## 5. 补充 Implementation Gap

以下是本次能力映射新增的体验层取证，补充初始评估中的 IG-01～IG-21：

| ID | Gap | 当前证据 |
|---|---|---|
| CMG-01 | Today 的旗舰“待我确认”与四类投影没有连接权威状态。 | `TodayPage.tsx` 使用 `SEED_TASKS`、本地 `filter` 确认和空账号假公司 fallback；真实 `AgentInteraction` 只在 ChatPanel 使用。 |
| CMG-02 | 冻结产品入口与现有深层能力形成新旧双轨。 | 新 `CareerPage` 为浅层列表且 Action 只 toast；完整 `CareerProcessPage` 仍作为孤立旧 route；Interview/Materials 主要嵌套旧页面。 |
| CMG-03 | 主要自然语言和对象跳转契约断裂。 | Today/InterviewHub 生成 `?prompt=`，GeneralChat 只读取 typed object handoff；Today 的 `?opportunity=` 未被新 CareerPage 消费。 |
| CMG-04 | Activity Center 尚不是全产品运行与审计投影。 | `ActivityCenterPage` 仅返回 `PersistentTasksPage`，没有统一 Turn/Task/Operation/Verification 视图。 |
| CMG-05 | 设置存在重复 owner 和体验。 | 新 SettingsModal 与旧 Personalization、Models、Capabilities/Profile routes 并存，部分表单重复读取和更新同一数据。 |
| CMG-06 | 机会发现只有工具和抓取能力，没有冻结的 pre-track 产品生命周期。 | jobs/web/JD tools 可用，但 discovery result 的持久化、去重、过期和产品工作区未定义。 |
| CMG-07 | Communication/Calendar 能力尚未形成跨 provider 产品边界。 | Gmail 观察链较完整；没有 Calendar domain owner、provider-neutral observation operation 或用户级通信投影决定。 |

这些 Gap 不要求立即逐项修复。它们应在拥有相应用户闭环的 Vertical Slice 中一起解决。

---

## 6. 推荐 Vertical Slice Roadmap

### 6.1 路线总览

| Slice | 用户闭环 | 首要能力 | 必要依赖 | 主要基础能力增量 | 完成后应退出的旧路径 |
|---|---|---|---|---|---|
| VS-01 | 面试邀请接收、确认与准备交接生命周期 | PC-11、PC-12（handoff）、PC-25～27、PC-10（确认投影） | 无业务前置 | 首版 Operation Registry、Turn/Context/Policy/Verification/Event/Client Action、fixture Observation | Today seed confirmation；邀请相关直接写；通用 prompt 跳转 |
| VS-02 | 职业档案与方向，从来源到确认 | PC-01～03、PC-17（Profile source） | VS-01 的共享执行脊柱 | Candidate/confirmation operation、Source/Evidence、Memory governance | legacy Resume 作为正式 owner；Profile 重复写规则 |
| VS-03 | 机会发现、研究与跟踪 | PC-04～06 | VS-02；SF-02/03/04 | Discovery lifecycle、Tool disclosure、Opportunity operations | 浅层/完整双 Career 写路径；临时搜索冒充流程 |
| VS-04 | 多流程事实、建议、真实行动与 Today | PC-06～10 | VS-01、VS-03 | Recommendation boundary、NextAction target、Today projections、cross-process insight | suggested NextAction；Today 剩余 mock；孤立 insights projection |
| VS-05 | 面试准备与模拟训练 | PC-12～13、PC-27 | VS-02、VS-03；可复用 VS-01 invitation | Preparation Context Package、Plan/Workflow routing、通用 Client Action | Hub 营销壳与旧 Mock 嵌套双轨 |
| VS-06 | 真实面试证据、复盘与能力成长 | PC-14～16 | VS-05、SF-04、SF-10 | Evidence pipeline 接新 Operation、AbilityUnderstanding/AbilityProfile | 永久 Ability score owner；旧 Growth 投影；分散分析入口 |
| VS-07 | 明确材料生成、版本与提交 | PC-17～19 | VS-02、VS-03；SF-04 | Artifact Contract、异步生成、编辑/导出、submission verification | message promotion；legacy Resume/attachment Artifact 特例 |
| VS-08 | Offer 摄取、比较与决定 | PC-20～21 | VS-03；VS-07 提供可选材料 | Offer operations、comparison recipe、decision event | Offer 隐式决定或孤立页面写规则 |
| VS-09 | 沟通、外部行动与主动 Career Loop | PC-22～25 | VS-01、VS-04、VS-08 | Provider-neutral Observation、external verification、proactivity budgets、Activity Center | Gmail 特化 domain writes；活动中心 alias；无 scope 自动化 |
| VS-10 | 跨产品体验收敛与数据治理 | PC-26～28，收口所有能力 | 前九个切片 | 单一 IA、统一设置、历史/导出/删除/retention、legacy exit gate | 重复 routes/pages/forms、旧 evaluation manifest、剩余兼容 owner |

### 6.2 依赖图

```text
VS-01 面试邀请执行脊柱
├── VS-02 职业档案与方向
│   ├── VS-03 机会发现与跟踪
│   │   ├── VS-04 多流程 + Today
│   │   ├── VS-05 面试准备与模拟
│   │   │   └── VS-06 真实面试复盘 + Ability
│   │   ├── VS-07 材料与提交
│   │   └── VS-08 Offer 生命周期
│   └── VS-07 材料与提交
├── VS-04 多流程 + Today
└── VS-09 沟通与主动 Career Loop
    └── 依赖 VS-04 与 VS-08 的正式业务对象

VS-10 在每个切片持续收敛，最后承担全产品旧路径退出和数据治理验收。
```

VS-02 与 VS-01 完成后的部分基础工作可以并行；VS-05 与 VS-07 在 VS-03 的对象契约稳定后也可以并行。并行不改变每个 Slice 自己必须端到端完成的要求。

### 6.3 为什么 VS-01 应成为首个正式切片

“面试邀请完整生命周期”同时具备：

- 用户价值明确，输入和终态容易观察；
- 跨 Opportunity、ProcessEvent、Interview、Observation 和 Evidence；
- 同时需要事实确认、拒绝、修正与 typed failure；
- 可验证 UI、Agent 和 Automation fixture 是否共享同一 Operation；
- 可验证 waiting/resume、Policy、Verification、Today 与 Activity 投影；
- 可以用 fixture/manual provider 开始，不必先承担 Gmail/Calendar 的外部不确定性；
- 完成后能为后续所有切片留下真正可复用的执行脊柱。

它不是“先做一个邮件解析功能”，也不是“先重构 Harness”。它是用一个真实业务闭环建立目标架构的第一条生产路径。

---

## 7. VS-01 建议边界（等待正式 Spec 冻结）

本节只用于确定下一份 Vertical Slice Spec 的候选范围，不冻结 Operation 名称或 schema。

### 7.1 用户目标

当用户收到或描述一个面试邀请时，系统能够识别其来源，允许用户查看、修正、确认或拒绝事实，并在确认后建立可追溯的真实面试上下文，最后把用户带入准备工作区。

### 7.2 三种入口

1. **UI 直接操作**：用户手动录入并确认面试邀请；
2. **自然语言 Agent**：用户明确陈述邀请事实，Agent 通过 typed Operation 录入；
3. **主动入口**：fixture/manual Observation Provider 摄取一条外部邀请候选并触发事实确认。

用户明确陈述且参数完整的事实不应被强制重复确认；Agent 推断或外部 Observation 形成的候选必须进入事实确认。外部操作批准与事实确认是不同 Interaction。

### 7.3 候选执行流

```text
Perceive invitation input / observation
→ Persist source and provenance
→ Match or propose JobOpportunity
→ Build typed invitation candidate
→ Confirm / correct / reject
→ Execute one atomic confirmation transaction
→ Verify canonical state and event versions
→ Project result to 求职 / 面试 / Today / Activity
→ Typed Client Action opens preparation context
```

### 7.4 终态

| 终态 | 必须发生 | 不得发生 |
|---|---|---|
| Confirmed | 候选确认；关联或创建正确 Opportunity；建立/更新 Interview；追加真实 ProcessEvent；保存 Evidence；验证新状态。 | 不得顺便发送邮件、创建长期自动化、修改 Profile 或生成 Artifact。 |
| Corrected then confirmed | 保存用户修正并以修正后事实执行同一确认链；保留原候选与修正关系。 | 不得静默覆盖来源快照。 |
| Rejected | 候选进入 rejected/closed；保留来源与审计。 | 不得创建 Interview、ProcessEvent 或 NextAction 副作用。 |
| Conflict / stale | 返回 typed conflict，重新读取并让用户选择。 | 不得 last-write-wins。 |
| External result unknown（仅可选扩展） | 保留调用 identity、标记 unknown、fence 资源并安排 reconciliation。 | 不得宣称完成或自动重试产生重复副作用。 |

NextAction 不是完成本切片的强制副作用。只有邀请事实本身明确要求用户完成某个真实行动，或用户接受准备建议时，才由独立 Operation 创建 NextAction。

### 7.5 第一版非目标

- 不接真实 Gmail 或 Calendar provider；
- 不完成完整面试准备内容生成；
- 不重写模拟面试和真实面试分析；
- 不生成 Artifact；
- 不建立多 Agent；
- 不一次性搬迁全部 Tool 或全部页面；
- 不把 fixture Observation 表示成真实外部成功。

### 7.6 VS-01 完成定义

1. 三种入口至少在 fixture/manual 范围内调用同一 Operation 语义；
2. Confirm、correct-confirm、reject、conflict、retry、stream reconnect 和 interrupt 均有确定性测试；
3. Operation、Domain Event、Harness Event 和 Experience projection 具有稳定 identity/version；
4. Today 的“待我确认”来自真实 Interaction，不再使用 seed；
5. 求职和面试投影能打开同一 confirmed Interview；
6. Client Action 只负责打开准备上下文并返回 ack，不冒充业务完成；
7. Activity Center 至少显示该 Turn/Operation 的 waiting、verifying 和 terminal 状态；
8. 新场景进入基于新蓝图的 evaluation manifest；
9. 当前邀请相关的重复或绕过路径被删除、封闭或明确隔离。

---

## 8. Product Decision Required

下表只列需要产品所有者确认、会改变长期产品语义的事项。工程内部的文件拆分、类名和迁移顺序不在此列。

| ID | 决定 | 最晚决策点 | 建议 | 若不决定的影响 |
|---|---|---|---|---|
| PDR-01 | **Approved 2026-08-26**：VS-01 正式冻结为“面试邀请接收、确认与准备交接生命周期”，第一版使用 UI、自然语言和 fixture/manual Observation。 | 已归位到 Blueprint 附录 A 与 VS-01 Spec | 它覆盖架构主干且不被外部 Provider 阻塞。 | 已解决。 |
| PDR-02 | **Approved 2026-08-26**：`confirm_interview_invitation` 事务包含 invitation confirmation + Opportunity create/link + Interview create/update + ProcessEvent + Evidence/Domain Events；不包含 NextAction、准备计划、邮件和 Calendar action。 | 已归位到 Blueprint 5.3、附录 A 与 Operation Contract | 保持一个业务意图、一个授权边界和确定性回滚。 | 已解决。 |
| PDR-03 | Calendar Event、Interview Schedule 与 fixed-time NextAction 的所有权；VS-01 是否加入 fake Calendar external-action 支线。 | VS-01 可选外部验证支线前 | **建议：** 核心 VS-01 不依赖 Calendar；可增加独立可选 fixture 支线专门验证 approval/receipt/unknown。Interview 拥有已确认安排，Calendar 保持 provider source/执行投影，NextAction 只表示用户行动。 | 不影响核心确认闭环，但会延后 external-write 真值验证。 |
| PDR-04 | Recommendation/Proposal 的持久化与反馈生命周期。 | VS-04 前 | **建议：** 先定义轻量、有来源、可接受/拒绝/忽略/过期的独立 owner；接受后通过 Operation 创建 NextAction。 | 无法删除 suggested NextAction。 |
| PDR-05 | Discovery Result 在 track 前的持久化、去重和过期。 | VS-03 前 | **建议：** 使用低权威、可过期的 discovery projection/source record；只有显式 track 才创建 JobOpportunity。 | 机会搜索可能污染正式流程或无法跨会话去重。 |
| PDR-06 | AbilityUnderstanding 聚合、冲突、衰减、重算和 AbilityProfile rubric/version。 | VS-06 前 | **建议：** 先冻结语义与可重算契约，再选择算法；不把一个全局 score 作为 owner。 | 无法安全替换当前 score/Growth 投影。 |
| PDR-07 | Artifact 格式、异步状态、编辑和导出契约。 | VS-07 前 | **建议：** 以明确文件意图、append-only versions 和 typed generation job 为核心；格式分批开放。 | 无法判断何时创建 Artifact 及何时算完成。 |
| PDR-08 | 是否需要用户级统一 Communication 索引 Projection。 | VS-09 前 | **建议：** 保留 connector-owned source，增加只读可重建的用户级通信索引，不建立万能 Communication 事实表。 | 求职工作区的跨渠道沟通体验无法稳定。 |
| PDR-09 | 主动性预算、quiet hours、通知频率、成本上限和长期 external-write 预授权目录。 | VS-09 前 | **建议：** 默认保守、可撤销、按动作族分 scope；External Write 默认逐次确认，直到具体类别通过评测。 | 无法安全发布主动 Career Loop。 |
| PDR-10 | Copilot 的具体呈现组合和默认 trace 深度。 | VS-10 前；VS-01 只需最小对象 handoff | **建议：** 先验证全局入口 + 对象工作区组合；默认显示目标/状态/确认/验证，高级视图展开 Operation/Tool/receipt。 | 不阻塞业务 Contract，但影响最终 IA 收敛。 |
| PDR-11 | Memory 保留、敏感类别、删除 tombstone、数据导出与 Cloud/Community 驻留差异。 | VS-02 可做临时保守策略；VS-10 发布前必须决定 | **建议：** producer 继续默认关闭；先实现查看/删除/不复活，再批准自动写入。 | 长期 Memory 和生产数据治理不能开放。 |
| PDR-12 | 新蓝图场景集、主动 Loop 和 Memory producer 的发布阈值。 | 每个 Slice 发布前；最终阈值在 VS-09/10 前 | **建议：** 每个 Slice 先建立确定性场景，LLM judge 只补充质量判断，不裁定权限/真实性。 | 无法用一致标准宣称完成或发布。 |

### 8.1 当前决定状态

PDR-01 和 PDR-02 已于 2026-08-26 获得批准，不再阻塞首个 Vertical Slice Spec。PDR-03 只在决定把 fake Calendar external-action 支线纳入 VS-01 时阻塞该可选支线；核心 VS-01 不依赖该决定。其余问题应在对应 Slice 前解决，不应让整个重建停在长期产品讨论中。

---

## 9. VS-01 文档冻结进度

PDR-01 和 PDR-02 已批准。当前已按受控边界创建：

1. 首批共享 Contracts 的最小集合：Operation、Event/Interaction、Verification、Context Package 的 VS-01 必需部分；
2. `VS-01 Interview Invitation Lifecycle` Vertical Slice Spec；
3. 新的 Implementation Ledger 骨架，只登记 VS-01 的 owner、依赖、迁移和验收门禁；
4. 新蓝图 evaluation scenario 的 VS01-S01 至 VS01-S15 设计；正式 manifest 文件在实现阶段以红灯门禁方式登记，不修改现有历史场景语义。

上述文档仍处于待审阅草案状态。在它们获批前，不修改业务代码、数据库、迁移、测试或现有 evaluation。也不创建剩余九个 Slice 的空 Spec，因为后续边界应从已完成切片和已批准产品决定中逐步收敛。
