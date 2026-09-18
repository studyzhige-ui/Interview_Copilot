# Interview Copilot 架构文档权威索引

> 全仓文档体系正在按产品到实施的层级重新组织。总入口见 [`docs/README.md`](../README.md)；本文在过渡期只负责现有架构文档的权威关系。

> 状态：现行文档治理索引；不定义第二套产品或目标架构
> 生效日期：2026-08-26
> 当前唯一蓝图：[`career-agent-os-blueprint.md`](./career-agent-os-blueprint.md)

## 1. 用途

本文只回答三件事：当前哪份文档具有何种地位、发生冲突时按什么顺序裁定、旧文档还能以什么方式使用。产品使命、产品语义和目标架构只在已批准的 Career Agent OS Blueprint 及其下位正式规范中定义。

## 2. 当前权威链

当前仓库按以下顺序治理文档：

1. 当前已批准的 Career Agent OS Blueprint；
2. 用户批准并已登记、但尚未合并进蓝图的架构决策；
3. 正式 Contracts；
4. Vertical Slice Specs；
5. Implementation Ledger；
6. 当前代码、数据库迁移和测试所表达的实现事实；
7. Historical / Superseded 文档。

截至 2026-08-26：

| 层级 | 当前状态 | 入口 |
|---|---|---|
| Approved Blueprint | 已建立 | [`career-agent-os-blueprint.md`](./career-agent-os-blueprint.md) |
| Registered Decisions | 当前无尚未合并的决定 | 仅在真实决定产生时创建记录，不预建空目录 |
| Formal Contracts | VS-01 所需四份 Contract 已通过 Gate A | [`contracts/`](./contracts/) |
| Vertical Slice Specs | VS-01 1.0.0 已批准并实施中 | [`VS-01 面试邀请接收、确认与准备交接生命周期`](./vertical-slices/vs-01-interview-invitation-intake-confirmation-handoff.md) |
| Implementation Ledger | 现行账本；当前只登记 VS-01 | [`career-agent-os-ledger.md`](../implementation/career-agent-os-ledger.md) |

## 3. 文档状态登记

### 3.1 现行规范

| 文档 | 状态 | 责任 |
|---|---|---|
| [`career-agent-os-blueprint.md`](./career-agent-os-blueprint.md) | 唯一现行产品与目标架构蓝图 | 产品宪法、运行模型、三层架构、Domain、Operations、Harness、Data Assets、Trust、Experience、Evaluation 与目标工程边界 |

### 3.2 现行专项与实现文档

这些文档可以约束自己的专项范围或描述当前实现，但不得覆盖 Blueprint，也不会因被列在本节而自动升级为 Formal Contract。

| 文档 | 状态 | 使用边界 |
|---|---|---|
| [`codebase.md`](./codebase.md) | 当前实现参考 | 描述仓库现状、运行流、存储与依赖方向；不能反向定义目标架构 |
| [`editions.md`](./editions.md) | 现行专项部署政策 | 定义 Cloud / Community 的可用性边界；不能建立第二套产品语义 |
| [`interview-audio-to-qa-pipeline.md`](./interview-audio-to-qa-pipeline.md) | 现行专项实施设计 | 定义录音到可审计 QA 的证据流水线；冲突时先服从 Blueprint，再通过未来 Contract/Vertical Slice 归位 |
| [`mock-interview.md`](./mock-interview.md) | 现行专项实施说明 | 描述当前模拟面试实现；不是完整面试产品规范 |
| [`agent-memory-lifecycle.md`](./agent-memory-lifecycle.md) | 现行记忆实现说明 | 两阶段经验提取、整理、语义召回、删除传播与运行验证 |
| [`context-management-lifecycle.md`](./context-management-lifecycle.md) | 现行上下文实现说明 | 从规划、记忆/RAG 到最终消息预算、摘要提交、工具循环与恢复 |
| [`../implementation/career-agent-os-initial-assessment.md`](../implementation/career-agent-os-initial-assessment.md) | 非规范性实施评估 | 保存初始代码取证、Implementation Gap、旧文档待查点和当前实现冲突 |
| [`../implementation/career-agent-os-capability-map.md`](../implementation/career-agent-os-capability-map.md) | 现行产品覆盖与切片路线图 | 保证全产品能力有归属；其中 PDR-01/PDR-02 已归位，未批准事项不能覆盖 Blueprint |
| [`../implementation/career-agent-os-ledger.md`](../implementation/career-agent-os-ledger.md) | 实施账本草案 | 记录 VS-01 当前资产、工作项、迁移、门禁与退出条件；不定义产品语义 |
| [`../deployment/cloud.md`](../deployment/cloud.md) 与 [`../deployment/community.md`](../deployment/community.md) | 现行运维文档 | 描述部署与运营方式；不得改变产品与 Domain 语义 |

### 3.3 已批准的 Formal Contracts 与 Vertical Slice

这些文档由批准的 PDR-01/PDR-02 驱动创建，并已于 2026-08-26 通过 Gate A：

| 文档 | 范围 |
|---|---|
| [`contracts/application-operation-contract.md`](./contracts/application-operation-contract.md) | Shared Atomic Application Operations 与 VS-01 Operation Catalog |
| [`contracts/interaction-event-contract.md`](./contracts/interaction-event-contract.md) | Event Envelope、fact-confirmation Interaction 与 preparation Client Action |
| [`contracts/verification-contract.md`](./contracts/verification-contract.md) | Operation success、read-back、unknown 与 reconciliation |
| [`contracts/context-package-contract.md`](./contracts/context-package-contract.md) | Context authority、source manifest、scope、预算与压缩不变量 |
| [`vertical-slices/vs-01-interview-invitation-intake-confirmation-handoff.md`](./vertical-slices/vs-01-interview-invitation-intake-confirmation-handoff.md) | 第一条三入口端到端 Career Agent OS 主干 |

### 3.4 Historical / Superseded

| 文档 | 状态 | 仍可使用的内容 |
|---|---|---|
| [`full-cycle-career-copilot.md`](./full-cycle-career-copilot.md) | Superseded Product and Target-Architecture Baseline | 历史决策理由、现有代码来源和按需取证；无现行规范效力 |
| [`full-cycle-implementation-ledger.md`](./full-cycle-implementation-ledger.md) | Historical / Superseded Implementation Ledger | 2026-08-13 基线下的代码、迁移与测试映射；状态声明不得视为当前完成度 |
| [`stages/`](./stages/README.md) | Historical Implementation Reference | 已实现的物理合同、并发、持久化、证据和恢复不变量；只有经当前 Blueprint 复核后才能进入新 Contract |
| `docs/reports/` | Dated Historical Reports | 对应日期的审计或评测结果；不能替代当前规范或当前验证结果 |

## 4. 新决定如何登记和归位

用户确认的新产品或架构决定不得长期停留在聊天、Prompt 或临时任务说明中：

1. 能在同一变更中归位时，直接修改 Blueprint 或负责该语义的正式 Contract；
2. 暂时不能合并时，才创建已登记 Decision Record，至少记录决定、批准人、批准日期、影响范围、状态和目标归位位置；
3. Decision Record 合并后应标记为 incorporated，并链接到最终章节；
4. 实现发现不能自行改变产品语义，只能形成 Implementation Gap 或 Product Decision Required；
5. 不创建没有真实决定、Contract 或 Vertical Slice 内容的空目录和占位文档。

## 5. Supersession 规则

`Superseded` 表示文档不再拥有现行规范效力，不表示删除历史，也不表示其中所有工程不变量自动失效。

- 旧文档中的目标语义不能覆盖当前 Blueprint；
- 仍有价值的工程约束必须由当前代码、迁移或测试证明，并与当前 Blueprint 一致；
- 经复核保留的约束应进入负责该语义的新 Contract、Vertical Slice Spec 或 Implementation Ledger；
- 在归位完成前，它只能作为历史取证材料，不能被实现者直接当成新系统要求。

## 6. 下一治理阶段

Capability Coverage Map 已建立，PDR-01/PDR-02 已批准并归位；VS-01 所需 Contracts、Vertical Slice Spec 和新 Implementation Ledger 已于 2026-08-26 通过 Gate A。当前进入 Gate B 的 Schema / Owner seam 实施；PDR-03 不阻塞核心 VS-01。
