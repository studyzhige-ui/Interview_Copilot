# Interview Copilot 文档入口

> 当前实现入口（2026-10-13）。以下实现文档描述本地代码；产品蓝图和文档治理草案描述设计方向，不能替代运行验证。

- [全项目复核与收尾](implementation/full-project-audit-2026-10-13.md)：逐目录检查范围、根因修复和验证限制。
- [当前代码架构](architecture/codebase.md)：模块职责、数据流与部署。
- [录音到问答主线](architecture/interview-audio-to-qa-pipeline.md)：声学证据、语义提取、回听与恢复。
- [工程收尾与面试追问依据](implementation/engineering-closure-2026-10-13.md)：设计取舍、源码入口、修复和限制。
- [Web／Docker 验收记录](implementation/web-release-acceptance-2026-10-12.md)：实际执行范围及未验收能力。

以下为文档体系的设计说明，其中审批阶段不代表当前代码仍停留在该阶段。

## 1. 为什么建立这套体系

Interview Copilot 已经拥有大量代码、测试、设计文档和重要产品决定，但过去的内容主要围绕“怎样重构系统”组织，尚未形成一条让产品负责人可以逐层审阅的完整链路。

新的文档体系要保证：

1. 每份文档只回答一个层级的问题；
2. 上层决定下层，下层不得反向发明产品；
3. 用户逐层批准后，Codex 才进入下一层；
4. 已有文档作为证据和候选答案复用，不因重新梳理而丢失；
5. 产品决定、实现事实和历史材料不混写；
6. 任一需求都能追溯到用户问题、产品价值、交互、领域操作、Contract、代码和评测。

详细规则见 [`Document System Charter`](./governance/document-system.md)。

## 2. 自顶向下的文档层级

```text
L0  Governance
    文档权威、状态、批准、变更和追溯规则

L1  Product
    产品定义 → MVP → 成功指标与非目标

L2  Experience
    用户旅程 → 信息架构 → Surface 职责 → 页面状态与交互

L3  Domain and Agent Behavior
    领域世界 → 业务规则 → Atomic Operations → Agent 行为与信任边界

L4  Contracts
    Operation / Interaction / Event / Context / Verification / API 契约

L5  Technical Architecture
    代码边界、运行时、数据、集成、安全、可观察性、部署

L6  Delivery
    Capability Map → Vertical Slice → Implementation Ledger → Release Gate

L7  Evidence and History
    当前代码取证、评测报告、审计、Historical / Superseded 文档
```

## 3. 产品设计文档的审阅顺序

新增产品设计从第一层工作文档开始；现有功能维护与修复以代码和验收记录为依据：

1. [`Product Definition`](./product/product-definition.md)
2. 文档体系本身如有问题，先修改 [`Document System Charter`](./governance/document-system.md)

在 Product Definition 获得批准前：

- 不创建新的产品功能；
- 不启动第二条 Vertical Slice；
- 不根据页面空缺追加组件；
- 不根据当前表结构反推产品需求；
- 已实施的 VS-01 保留为工程资产和架构验证，不扩大范围。

## 4. 后续文档只在上层批准后创建

| 顺序 | 审阅门 | 产物 | 回答的问题 |
|---|---|---|---|
| 0 | G0 | Document System Charter | 文档怎样产生、批准和裁定冲突？ |
| 1 | P1 | Product Definition | 产品为谁解决什么问题，承诺什么价值？ |
| 2 | P2 | MVP Definition | 第一版最小闭环是什么，明确不做什么？ |
| 3 | E1 | Core User Journeys | 用户在真实场景中怎样获得价值？ |
| 4 | E2 | Information Architecture and Surface Specs | 产品入口与页面分别负责什么？ |
| 5 | E3 | Interaction and State Specs | 每个动作、状态、失败和恢复怎样表现？ |
| 6 | D1 | Domain Model and Operation Catalog | 产品世界有哪些对象、规则和业务操作？ |
| 7 | A1 | Agent Behavior and Harness Requirements | Agent 为什么介入、知道什么、能做什么？ |
| 8 | C1 | Formal Contracts | 各层如何用稳定契约协作？ |
| 9 | T1 | Target Technical Architecture | 这些决定如何落入工程结构？ |
| 10 | V1 | Vertical Slice and Evaluation | 下一批代码精确实现什么，如何证明完成？ |

不预建空文档。每一层批准后，再创建下一层实际需要的文档。

## 5. 现有材料怎样使用

现有材料不删除，也不要求从头重写。它们的迁移与引用方式见：

- [`Current Document Map`](./governance/current-document-map.md)
- [`Career Agent OS Blueprint`](./architecture/career-agent-os-blueprint.md)
- [`Initial Assessment`](./implementation/career-agent-os-initial-assessment.md)
- [`Implementation Ledger`](./implementation/career-agent-os-ledger.md)

旧内容只能作为以下三种输入之一：

- **Approved input**：已经由用户明确确认，可提交到对应新层级重新审阅；
- **Engineering evidence**：由代码、迁移或测试证明的当前事实；
- **Historical rationale**：帮助理解过去为什么这样设计，但不自动成为新决定。

## 6. 当前停点

本轮只建立文档体系并开始 Product Definition。下一步由用户审阅 G0 和 P1，不继续业务代码实施。
