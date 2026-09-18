# Interview Copilot Document System Charter

> 状态：G0 草案，等待用户批准  
> 作用：定义 Interview Copilot 文档体系的层级、权威、状态和工作流  
> 不负责：定义产品功能、MVP、页面、领域模型或技术实现

## 1. 目标

本文建立一套自顶向下、单一职责、可审阅、可追溯的文档系统，使产品负责人能够从产品问题开始逐层把关，而不是在编码过程中临时补需求、交互和架构。

这套体系不要求丢弃已有成果。它负责决定已有内容应当被引用、重新审阅、拆分归位、保留为实现事实，还是降级为历史材料。

## 2. 核心原则

### 2.1 一个问题只有一个权威 owner

同一产品问题不能由 Blueprint、页面说明、API 文档和代码分别给出不同答案。每类问题必须有唯一负责的文档层级。

### 2.2 上层约束下层

```text
用户问题和产品价值
→ MVP 范围
→ 用户旅程
→ 页面与交互
→ 领域对象和业务操作
→ Agent 行为
→ Contracts
→ 技术架构
→ 实施
```

下层发现困难时，只能提出 Gap 或 Decision Required，不能偷偷改变上层语义。

### 2.3 产品决定与实现事实分离

- 产品文档描述“应该是什么”；
- Contract 描述“参与者必须如何协作”；
- 技术架构描述“由哪些工程边界实现”；
- Ledger 描述“现在完成到哪里”；
- 代码和测试描述“当前实际实现了什么”；
- 历史材料描述“过去怎样想过或做过”。

### 2.4 先批准，再向下展开

每个层级设置明确 Gate。上层未批准时，可以做取证和方案比较，但不得把候选答案当成下层开发输入。

### 2.5 不在聊天中长期保存决定

用户确认的决定必须在同一阶段归位到负责该语义的文档。聊天是讨论渠道，不是长期规范源。

### 2.6 不预建空结构

只创建当前阶段真正需要的文档。目录树是路由计划，不是要求一次生成大量模板。

### 2.7 需求必须端到端可追溯

进入代码的能力最终应能追溯：

```text
Product Need
→ MVP Capability
→ User Journey
→ Surface / Interaction State
→ Domain Rule / Atomic Operation
→ Contract
→ Vertical Slice
→ Code / Migration
→ Test / Evaluation
```

## 3. 文档层级和职责

### L0 — Governance

回答：谁能批准、文档处于什么状态、冲突怎样解决、变更怎样归位。

允许内容：

- 文档体系；
- 权威链；
- Decision Record；
- 文档迁移图；
- 术语治理规则。

不得内容：具体产品功能或实现设计。

### L1 — Product

回答：为谁、在什么场景、解决什么问题、提供什么独特价值、怎样算成功。

建议按顺序形成：

1. Product Definition；
2. MVP Definition；
3. Success Metrics and Product Non-goals。

产品使命不能代替 MVP；功能清单也不能代替产品定义。

### L2 — Experience

回答：用户怎样完成目标，以及产品怎样让状态、控制权和反馈对用户可见。

包括：

- Core User Journeys；
- Information Architecture；
- Surface Responsibility；
- Navigation and Handoff；
- Page State and Interaction；
- Content Design；
- Design System（在体验结构稳定后）。

视觉稿不能决定页面职责；页面也不能因视觉空缺而新增业务模块。

### L3 — Domain and Agent Behavior

回答：产品世界里什么是真实对象、什么规则成立、Agent 为什么以及何时参与。

分为两个相互约束但不混写的部分：

- **Career Domain**：Canonical State、Source、Evidence、Memory Records、业务规则、Atomic Application Operations；
- **Agent Behavior**：Perceive 到 Schedule Next Observation 的循环、主动性、Context、Tool、Permission、Verification、Memory Runtime 和用户沟通要求。

Domain 不依赖某个页面存在；Agent Tool 不拥有业务规则。

### L4 — Contracts

回答：跨边界协作时，输入、输出、状态、错误、权限、幂等和验证如何保持稳定。

包括但不限于：

- Application Operation Contract；
- Interaction / Approval Contract；
- Event Contract；
- Context Package Contract；
- Verification Contract；
- Client Action Contract；
- API / Transport Contract；
- Connector Contract。

REST endpoint 只是传输适配，不是业务语义 owner。

### L5 — Technical Architecture

回答：已经批准的产品、体验、领域、Agent 与 Contract 如何映射到工程结构。

包括：

- 目标代码边界和依赖方向；
- 数据所有权与持久化；
- Agent Runtime；
- 后台任务和恢复；
- 集成与连接器；
- 安全、隐私和权限执行；
- 可观察性；
- 部署、可靠性和运维。

技术架构不得为了迁就当前代码而重新定义产品。

### L6 — Delivery

回答：按什么顺序实施、当前完成度是什么、什么时候可以切换和发布。

包括：

- Capability Coverage Map；
- Vertical Slice Specs；
- Implementation Ledger；
- Migration / Cutover Plan；
- Release Gate。

Vertical Slice 是实施单位，不是产品范围来源。

### L7 — Evidence and History

回答：当前事实和过去依据是什么。

包括：

- 代码审计；
- 评测结果；
- dated reports；
- current-state codebase guide；
- Historical / Superseded 文档。

它们可以支持决定，不能替代决定。

## 4. 文档状态

每份受控文档必须在开头使用一个状态：

| 状态 | 含义 |
|---|---|
| `Working Draft` | 正在收集问题和候选答案，没有规范效力 |
| `Review Required` | 内容已完整到可审阅，等待用户决定 |
| `Approved` | 用户已批准，成为其负责范围的现行权威 |
| `Amendment Required` | 仍有效，但存在已登记且必须合并的变更 |
| `Implemented Evidence` | 描述实现事实，不拥有产品语义 |
| `Historical` | 仅保存历史背景，从未被现行规范取代关系覆盖 |
| `Superseded` | 曾经有效，现已由明确文档取代 |
| `Archived` | 不再参与日常设计和取证 |

`代码已实现`、`测试通过`、`Codex 已生成`都不是文档批准状态。

## 5. 权威顺序

新体系完全生效后的目标权威顺序是：

1. Approved Governance and registered user decisions；
2. Approved Product Definition and MVP；
3. Approved Experience Specifications；
4. Approved Domain and Agent Behavior Specifications；
5. Formal Contracts；
6. Target Technical Architecture；
7. Vertical Slice Specs；
8. Implementation Ledger；
9. Code、migrations、tests 所表达的当前事实；
10. Evidence、Historical 和 Superseded 文档。

同一层级冲突时，以范围更具体且批准日期更新的文档为准，但必须登记冲突并回写上位索引，不能依靠读者自行推断。

## 6. 过渡期规则

当前 [`Career Agent OS Blueprint`](../architecture/career-agent-os-blueprint.md) 已经获得批准，并同时承载多个新层级的内容。为了避免在重新梳理期间出现规范真空或两套“最高文档”：

1. Blueprint 在过渡期继续作为现行产品与目标架构基线；
2. 新建文档在用户批准前均为 Working Draft；
3. 每批准一个新层级，必须登记它取代或吸收了 Blueprint 的哪些章节；
4. 未被新文档覆盖的 Blueprint 内容继续有效；
5. 全部分层文档完成后，再决定将 Blueprint 收窄为架构总览、拆分后 Supersede，或保留为非重复的总索引；
6. 不允许新文档在未批准时覆盖已批准决定。

## 7. Gate 与审阅工作流

每一层遵循同一流程：

```text
收集现有输入
→ 区分已批准决定 / 工程事实 / 历史观点
→ 提出候选答案和真实开放问题
→ 用户逐项审阅
→ 修改并批准
→ 登记 supersession / traceability
→ 进入下一层
```

Gate 的通过条件：

- 文档目的和范围明确；
- 所有强语义都由用户确认或清楚标为开放；
- 没有借当前代码反向决定产品；
- 没有与上层批准文档冲突；
- 已记录对下层的约束和暂不决定事项；
- 已更新文档索引和追溯关系。

## 8. 变更分类

任何变更先分类，再修改文档：

| 变更 | 归位位置 |
|---|---|
| 目标用户、核心问题、价值承诺 | Product Definition |
| MVP 增删、成功标准 | MVP Definition |
| 用户流程、入口职责、页面状态 | Experience |
| 领域对象、业务不变量、Atomic Operation | Domain |
| Agent 主动性、Context、Tool、Memory、Permission | Agent Behavior |
| 输入输出、事件、错误、幂等、验证 | Contracts |
| 包结构、数据库、队列、部署 | Technical Architecture |
| 顺序、进度、迁移、删除条件 | Delivery |
| 测试结果、审计发现 | Evidence / Ledger |

如果一个变化横跨多层，必须先修改最高受影响层，再顺序向下传播。

## 9. 完成定义

文档体系建立完成，不代表所有文档已经写完。G0 的完成条件是：

1. 层级和职责获得用户批准；
2. 过渡期权威规则没有歧义；
3. 现有文档全部有迁移分类；
4. 第一份 Product Definition 工作文档已经建立；
5. 后续只按 Gate 创建真实需要的文档。

## 10. 当前开放问题

1. 用户是否批准本 Charter 作为 G0 Governance？
2. Product Definition 批准后，是让它高于 Blueprint 的产品章节，还是先以 Amendment 方式合并回 Blueprint？建议采用前者，并在过渡索引中明确覆盖范围。
3. 是否要求每个 Approved 文档记录批准人名称，还是只记录“用户批准”和日期？
