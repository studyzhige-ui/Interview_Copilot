# Interview Copilot Career Agent OS 产品与架构蓝图

> 状态：唯一现行产品与目标架构蓝图（已批准）
> 适用范围：Interview Copilot 的产品语义、目标架构与跨层契约
> 批准日期：2026-08-26
> 最近修订日期：2026-08-26

---

## 0. 文档契约

### 0.1 文档地位

本文档是 Interview Copilot 当前唯一现行的产品与目标架构蓝图。它自顶向下定义产品使命、运行模型、Career Domain Kernel、Agent Harness、Adaptive Experience、Career Data Assets，以及这些部分之间必须保持的边界。

本文档自 2026-08-26 起获得产品批准，并取代 [`full-cycle-career-copilot.md`](./full-cycle-career-copilot.md) 的产品与目标架构基线地位。该取代不自动废除仍与本蓝图一致的专项实现设计、部署政策或当前代码事实；这些文档的现行分类见 [`docs/architecture/README.md`](./README.md)。

本文档不是：

- 当前代码结构的说明书；
- 旧架构文档的续篇或摘要；
- API、数据表、Tool 或页面的现状清单；
- 迁移进度报告；
- 可被实现细节反向修改的产品描述。

当前代码、迁移和测试只用于识别已存在的正确工程资产、验证复杂不变量，以及标记 Implementation Gap。它们不能决定最终产品应当是什么。

### 0.2 权威顺序

发生冲突时，按以下顺序裁定：

1. 当前已批准的 Career Agent OS Blueprint；
2. 用户批准并已登记、但尚未合并进蓝图的架构决策；
3. 正式 Contracts；
4. Vertical Slice Specs；
5. Implementation Ledger；
6. 当前代码、数据库迁移和测试所表达的实现事实；
7. Historical / Superseded 文档。

用户确认的新产品决定必须尽快归位到 Blueprint 或对应 Contract，并在合并前以已登记架构决策的形式受控管理；不得长期只存在于聊天、Prompt 或临时任务说明中。

Historical / Superseded 文档中仍有参考价值的实现理由可以按需恢复，但必须同时符合当前已批准 Blueprint、已登记架构决策和正式 Contract，仍属于目标架构，并有当前工程事实或明确产品决定支持。

### 0.3 规范语言

本文档中的关键词含义如下：

- **必须 / 不得**：产品或架构不变量；实现不得偏离。
- **应该 / 不应**：默认目标；偏离时必须记录理由并通过评测证明。
- **可以**：允许的实现选择，不代表必须提供。
- **当前实现**：仅表示已存在的工程事实，不具有目标语义权威。
- **Implementation Gap**：当前实现与本文档目标之间的差距，不表示迁移进度。
- **Open Question**：本文档没有获得足够产品决定的问题；不得由实现者自行冻结答案。

### 0.4 变更规则

对本文档的变更必须按概念层级归位，不得按讨论时间追加：

1. 先判断是否改变产品宪法；
2. 再判断是否改变总体架构或内核边界；
3. 再修改对应正式契约；
4. 最后修改垂直切片与实施账本。

代码路径、迁移状态、测试通过数量和阶段进度不得写入主蓝图正文。它们属于独立的 Implementation Ledger。本文档附录只记录已经纳入的产品决定和非规范性实施评估入口，不作为迁移状态源。

### 0.5 核心术语

| 术语 | 定义 |
|---|---|
| Career Agent OS | Career Domain Kernel、Agent Harness 与 Adaptive Experience 组成的完整产品系统。 |
| Career Domain Kernel | 维护真实、结构化、可验证且可由用户修正的求职世界，并守住领域规则。 |
| Agent Harness | 包围模型并使其能够可靠感知、理解、规划、执行、验证、学习和沟通的运行环境。 |
| Adaptive Experience | 普通 UI、自然语言 Copilot 与主动 Career Loop 的用户操作和反馈层。 |
| Career Data Assets | 三部分共同使用、但由各自权威所有者管理的数据资产分类体系；不是第四个内核或万能存储。 |
| Canonical State | 产品确认的正式业务状态。模型推测和未确认候选都不是 Canonical State。 |
| Source Asset | 邮件、日历事件、JD、简历、网页、录音、转录等原始来源。 |
| Evidence | 将状态、判断或执行结果与真实来源、版本、时间和回执关联起来的证明关系。 |
| Observation | 对外部世界变化的一次有来源、可去重的观察；它本身不是指令，也不自动成为领域事实。 |
| Atomic Application Operation | 能在一个明确业务意图和主要授权边界内确定性完成的最小领域行为。 |
| Tool | Agent 调用能力的模型侧适配契约；Tool 不拥有领域逻辑。 |
| Skill / Recipe | 指导 Agent 如何组合多个原子操作完成复杂目标的策略，不直接隐藏副作用。 |
| AgentTask | 一个复杂 Turn 的可恢复目标、计划和完成条件；不是用户的 Next Action。 |
| PersistentTask | 用户确认的长期自动化定义；由触发事件唤醒，不等同于一次运行。 |
| Next Action | 用户真实需要完成且已经成立或已被接受的未来行动；不是建议。 |
| Artifact | 用户明确要求生成某种文件格式后形成的、可版本化的文件交付物。 |
| Client Action | Agent 请求客户端执行导航、聚焦、预填或进入工作区等纯体验动作的稳定协议。 |

---

## 1. 产品宪法

### 1.1 产品使命

> **Interview Copilot 是一个围绕用户持续运行的 AI 求职工作台。它长期理解用户的职业事实、目标、偏好、求职机会、行动、沟通、面试和能力变化，帮助候选人寻找机会、管理多个求职流程、准备和完成关键行动、进行面试训练与复盘，并安全、持续地推进整个求职过程。**

### 1.2 产品中心

产品围绕用户运行，不围绕单个岗位、一次面试、一份简历或一段对话运行。

一个用户可以同时拥有：

- 多个探索中、进行中和已结束的求职机会；
- 多个职业方向及其生命周期；
- 多场真实面试和模拟面试；
- 多份来源资料和用户明确生成的文件交付物；
- 多个已确认行动、长期自动化与运行中的 Agent 任务；
- 跨时间形成的能力观察、偏好和长期记忆。

岗位、面试、邮件、日历事件、资料和行动都是用户职业上下文中的对象。任何单一对象都不得成为产品唯一中心。

### 1.3 AI-native 的产品定义

Interview Copilot 不是“带聊天框的求职软件”，也不是“给 CRUD 页面增加 AI 功能”。AI-native 在本产品中意味着：

1. Agent 能按权限读取产品中的真实状态和来源；
2. 用户可以用自然语言表达目标，而不必知道页面和字段结构；
3. Agent 能通过共享的原子业务操作原生操控产品；
4. Agent 能组合操作、观察结果、处理失败并重新规划；
5. 产品能在授权范围内由真实事件或时间触发主动运行；
6. 每次正式改变都受领域规则、权限、幂等和验证约束；
7. 用户能看见、控制、确认、修正和撤销系统行为；
8. 系统能在长期使用中形成低权威、可管理的个性化理解；
9. 普通 UI 在模型不可用时仍能执行确定性业务操作；
10. Agent 的价值通过完成真实求职结果衡量，而不是通过生成文字的数量衡量。

### 1.4 用户最终控制权

用户拥有对以下内容的最终控制权：

- 个人职业事实；
- 职业方向和明确偏好；
- 求职机会及其事实时间线；
- 面试和 Offer 的确认状态；
- Next Action；
- Learned Memory；
- 自动化授权范围；
- 外部写操作；
- 已连接的外部账号与权限；
- 数据修正、失效、删除和导出。

Agent 的推测、总结、分类、推荐和记忆不得静默覆盖用户确认事实。外部观察也必须通过领域允许的来源规则和 Operation 才能改变 Canonical State。

### 1.5 真实性原则

系统必须区分：

- 已确认事实；
- 有来源但尚未确认的 Observation；
- Agent 推断；
- Agent 建议；
- 已批准但尚未执行的动作；
- 已调用但结果未知的动作；
- 具有 receipt 或 read-back 的已验证结果。

产品不得把“模型认为”“Tool 返回 success”“请求已发送”或“页面已跳转”表述为业务结果已经真实完成。

### 1.6 持续运行原则

“持续运行”表示系统能够长期保存状态、接收事件、按计划唤醒、暂停、恢复和验证，不表示模型必须常驻推理。

确定性的观察、去重、调度、权限预检和通知节流应由普通软件执行；只有理解歧义、规划复杂目标或决定下一步确实需要模型能力时，系统才唤醒 Agent。

### 1.7 产品成功标准

产品成功不是“拥有最多 Agent 功能”，而是用户能够更准确、更安全、更持续地：

- 发现与自身方向匹配的机会；
- 理解并管理多个并行求职流程；
- 在正确时间完成真实行动；
- 为面试建立有来源的准备材料；
- 训练、完成和复盘面试；
- 根据长期证据理解自身能力变化；
- 对 Offer 和职业方向做出更好的决定；
- 在不失去控制权的前提下减少求职管理负担。

---

## 2. 产品运行模型

### 2.1 三种使用方式

Interview Copilot 同时支持三种一等入口：

1. 用户直接操作 UI；
2. 用户通过自然语言 Agent 操作；
3. 主动 Career Loop。

三种入口必须共享：

- 同一套 Atomic Application Operations；
- 同一套 Career Domain State；
- 同一套领域规则；
- 同一套权限与授权事实；
- 同一套幂等与验证机制；
- 同一套 Evidence 与审计要求。

它们不是三套业务实现，也不得形成三个互相漂移的状态所有者。

### 2.2 用户直接操作 UI

简单、明确、可预测的操作必须允许用户直接完成，不应强制调用模型。例如：

- 新建或编辑求职机会；
- 修正职业档案；
- 确认或否决候选事实；
- 记录已经发生的流程事件；
- 创建、安排、完成或关闭 Next Action；
- 修正面试安排；
- 上传来源资料；
- 暂停长期自动化；
- 查看、修正、失效或删除 Learned Memory。

直接 UI 操作必须快速、确定、可访问、可回放，并在模型服务不可用时继续工作。

### 2.3 自然语言 Agent

用户可以直接表达目标，例如：

```text
把这封招聘邮件关联到腾讯后端岗位。
把已确认的面试时间改到下周三下午。
根据最近两场面试的证据，帮我安排薄弱项训练。
查找符合当前职业方向、且地点偏好匹配的新机会。
```

Agent 对一个目标可以选择：

- 直接回答；
- 读取必要的 Career Data Assets；
- 发起一个或多个原子业务操作；
- 创建可见的复杂 AgentTask；
- 请求澄清或确认；
- 请求 Client Action；
- 生成草稿但不写入正式状态；
- 安排后续观察；
- 明确拒绝不安全、无权限或无法验证的操作。

自然语言 Copilot 是一个统一产品入口。内部可以根据任务选择确定性查询、Workflow 或 Agent Loop，但不得要求用户理解底层“聊天模式”和“Agent 模式”的技术差异才能完成目标。

### 2.4 主动 Career Loop

主动 Career Loop 的产品循环为：

```text
Observe
→ Validate and Deduplicate
→ Understand
→ Plan
→ Approve
→ Act
→ Verify
→ Learn
→ Communicate
→ Schedule Next Observation
```

它可以在授权范围内处理：

- 招聘邮件和日历变化；
- 新出现或变化的求职机会；
- 临近的面试；
- 到期或长期未推进的行动；
- 长时间无变化的求职流程；
- 用户资料与目标岗位之间的新偏差；
- 重复出现且有证据支撑的能力模式；
- 用户确认的周期性检查任务。

外部内容是不可信数据，不能成为模型指令。Observation 必须先保存来源、版本、观察时间和去重身份，再进入理解与决策。

### 2.5 主动运行的分工

主动运行不得等同于“让一个自由 Agent 永久循环”。目标分工如下：

| 阶段 | 默认所有者 |
|---|---|
| 轮询、Webhook、时间触发 | Integration / Scheduler |
| 身份校验、去重、游标、快照 | Deterministic Observation Intake |
| 低价值过滤、安静时间、频率预算 | Proactivity Policy |
| 歧义理解、上下文关联、复杂规划 | Agent Harness |
| 正式状态改变 | Atomic Application Operation |
| 外部副作用 | Integration Adapter + Policy |
| receipt、read-back、reconciliation | Verification Runtime |
| 用户可见投影 | Adaptive Experience |

### 2.6 一个目标的标准执行路径

```text
User Intent / External Trigger
        ↓
Typed Ingress + Identity
        ↓
Context Package + Evidence
        ↓
Direct Operation / Workflow / Agent Decision
        ↓
Policy and Approval
        ↓
Atomic Application Operation or External Tool
        ↓
Verification and Reconciliation
        ↓
Domain State + Execution Record + Experience Projection
        ↓
Memory Candidate / Next Observation
```

### 2.7 停止条件

任何 Agent 或主动运行必须在以下情况之一停止或等待：

- 用户目标已满足且完成条件通过验证；
- 需要用户确认、澄清或外部连接；
- 权限不足或违反硬性政策；
- 必要来源不可用；
- 结果处于 unknown，必须等待 reconciliation；
- 用户取消；
- 资源、成本、时间或迭代预算达到安全上限；
- 继续运行不会产生新的可验证进展。

---

## 3. Career Agent OS 总体架构

### 3.1 三部分架构

```text
Career Agent OS
=
Career Domain Kernel
+
Agent Harness
+
Adaptive Experience
```

#### Career Domain Kernel

维护真实、结构化、可验证并可由用户修正的求职世界。它回答：

> 求职世界中有什么、当前正式状态是什么、状态从何而来，以及哪些变化是合法的？

#### Agent Harness

让模型能够可靠、安全、持续、可恢复地在 Career Domain 中工作。它回答：

> Agent 如何感知、理解、规划、执行、验证、学习并向用户沟通？

#### Adaptive Experience

让用户通过直接 UI、自然语言和主动议程看见、操作、控制和修正系统。它回答：

> 用户如何理解当前局面、完成行动、监督 Agent，并保持最终控制权？

### 3.2 Career Data Assets 的位置

Career Data Assets 是跨三部分的数据分类和生命周期体系，不是第四个内核，不是统一数据表，也不是一个通用 `DataAsset` 服务。

每类资产仍由自己的权威所有者管理：

- Career Domain Kernel 拥有 Canonical State 与领域事件；
- Integration 拥有外部 Source Snapshot 与连接状态；
- Agent Harness 拥有 Turn、Task、Tool Call、Approval 和 Verification 等执行资产；
- Memory Runtime 管理 Learned Memory 生命周期，Memory Record 作为一等数据资产持久化；
- Adaptive Experience 拥有 client-scoped 与短期 UI Context；
- Artifact、Interview、Opportunity 等领域各自拥有自己的 Evidence 边。

不得为了统一分类而创建会抹平所有权的万能来源注册表、万能上下文对象或万能资产表。

### 3.3 双内核关系

Career Domain Kernel 与 Agent Harness 是两个内核，但不对等地共同写状态：

- Domain Kernel 是正式业务事实与规则的唯一裁判；
- Harness 可以读取 Domain、提出候选、调用 Operation，但不得绕过 Domain 直接写状态；
- Domain 不依赖模型、Prompt、Tool Schema、SSE 或具体模型 Provider；
- Harness 不复制 Career Domain 状态机或另建一套求职事实；
- AgentTask、Tool Call 和 Learned Memory 不得冒充 JobOpportunity、NextAction、Profile 或 ProcessEvent。

### 3.4 三种入口与共享核心

```text
直接 UI 操作 ──────┐
                   │
自然语言 Agent ────┼── Shared Atomic Application Operations
                   │                    ↓
主动 Career Loop ──┘           Career Domain Kernel
```

UI Adapter、Agent Tool Adapter 和 Automation Adapter 只负责各自入口的身份、序列化、交互与传输差异。领域规则必须集中在共享 Operation 中。

### 3.5 总体控制流

```text
用户与外部世界
      │
      ├── Direct UI Command
      ├── Natural-language Intent
      └── Observation / Schedule Trigger
                    │
                    ▼
          Adaptive Experience / Ingress
                    │
          ┌─────────┴─────────┐
          │                   │
     Deterministic Path   Agent Harness
          │           Perceive → Decide → Act
          └─────────┬─────────┘
                    ▼
       Shared Atomic Application Operations
                    ▼
           Career Domain Kernel
          State + Rules + Events
                    │
                    ▼
      Evidence / Receipts / Projections
                    │
                    ▼
          Adaptive Experience
```

### 3.6 依赖原则

稳定依赖方向为：

```text
Presentation / Adapters
        ↓
Application Operations
        ↓
Career Domain Kernel
```

Agent Harness 通过 Operation Port 使用业务能力；Integration 通过 Application Operation 提交可验证变化；Infrastructure 实现数据库、队列、对象存储、向量索引和 Provider Port。Domain Kernel 不反向依赖这些外层。

### 3.7 状态所有权原则

每项状态必须只有一个权威所有者。跨层使用只能通过：

- typed identity；
- version / revision；
- immutable snapshot；
- source reference；
- domain event；
- query projection。

不得通过复制完整对象形成第二事实源，也不得把 Prompt 中的文本视为正式状态。

---

## 4. Career Domain Kernel

### 4.1 责任边界

Career Domain Kernel 负责：

- 领域实体和值对象；
- Canonical State；
- 领域状态机和不变量；
- Atomic Application Operation 的领域规则；
- 事务内必须保持一致的状态改变；
- 领域事件；
- 来源、Evidence 和修正关系；
- 用户所有权和跨用户隔离；
- 可回放的当前投影。

它不负责：

- 模型调用和 Prompt；
- Agent 计划、Tool Call 或 Turn；
- 页面路由和 UI 状态；
- 外部 Provider SDK；
- 通用任务调度；
- 将所有来源统一成一个万能 Evidence 对象；
- 让模型直接写表或字段。

### 4.2 用户职业身份与 CareerProfile

每个用户拥有一个正式 CareerProfile。它保存用户确认的职业事实和具有稳定身份的职业方向。

CareerProfile 必须满足：

- 用户是唯一所有者；
- 正式事实可版本化、可修正；
- 职业方向可以处于探索、活跃、暂停或归档等生命周期；
- 从简历、对话、模型推断或其他来源提取的内容只能先成为候选；
- 候选必须支持逐项确认、拒绝和冲突显示；
- 未确认候选不得进入 Canonical State；
- 用户修正优先于 Agent 推断和旧来源；
- Profile 不吸收求职过程事件、能力推断或 Learned Memory。

用户明确确认的长期职业偏好属于 Canonical Preference 或 CareerProfile 的明确部分；Agent 推断的偏好属于 Learned Memory，二者不得合并为同一权威层级。

### 4.3 JobOpportunity 与多流程管理

JobOpportunity 表示一个用户针对一个具体岗位和招聘批次的求职流程。产品必须允许多个 JobOpportunity 并行存在，并允许它们关联一个或多个 Career Direction。

JobOpportunity 的当前状态必须由已经发生并得到允许来源支持的 Process Event 推导。它不得预先创建未来招聘阶段。

产品可以使用少量稳定的高层投影帮助聚合，例如：

- 待投递；
- 已投递；
- 流程中；
- Offer。

这些高层投影不是对未来阶段的承诺。具体时间线只显示：

- 已经发生的事件；
- 外部流程或用户已经明确确认存在的下一阶段。

### 4.4 Process Event 与修正

Process Event 是求职流程中已经发生的正式事实。它必须：

- append-only；
- 具有稳定的 sequence；
- 记录 occurred time 与 observed time；
- 记录 source kind、source identity 和可用的 source version；
- 具有幂等身份；
- 允许通过 retraction 或 replacement 修正；
- 保留被修正的旧事实；
- 在需要时冻结当时的 JD、方向、渠道等分析上下文。

对历史的修正不得通过原地更新或删除旧事件完成。当前 JobOpportunity 投影必须可以从有效事件重建。

### 4.5 Recommendation、Proposal 与 Next Action

Agent 的建议与 Next Action 是不同概念。

#### Recommendation / Proposal

表示 Agent 建议用户考虑的事项。它可以出现在对话或相关业务工作区，但不作为 Today 的独立内容；在用户接受前不形成正式行动。

#### Next Action

只表示用户真实需要完成的未来行动。它只能来自：

- 用户主动创建；
- 外部流程已经明确要求；
- 用户接受了 Agent 建议。

Next Action 必须具有：

- 清晰的业务内容；
- 时间语义：固定时间、截止时间或灵活安排；
- 时间原文与时区来源（如适用）；
- 创建或确认来源；
- 当前生命周期；
- 完成或关闭的可追溯来源；
- 与 Opportunity、Interview、Offer 或 Artifact 等对象的可选关联；
- 能把用户带入对应业务操作的 Action Target。

点击 Next Action 后，Adaptive Experience 应通过 typed Client Action 或稳定路由上下文，将用户直接带入完成该行动的界面，而不是只打开一个通用任务详情页。

提醒是已经成立的 Next Action 的交付投影，不是第二套任务生命周期。

### 4.6 Interview Domain

Interview Domain 同时支持真实面试与模拟面试，但必须保留来源差异。

真实面试可以包含：

- 所属 JobOpportunity；
- 已确认的时间和阶段；
- 使用的简历与 JD 版本快照；
- 录音或视频 Source Asset；
- 转录与说话人证据；
- 结构化问答；
- 复盘报告；
- AbilitySignal 来源关系；
- 后续行动。

模拟面试可以关联某个 JobOpportunity，也可以是一般训练。模拟运行状态属于执行资产；完成后的 Interview Record、问答和复盘属于正式领域资产。

转录、问答和分析必须保持来源可追踪。模型不得凭空改写原始问答文本并将其表示为真实访谈内容。任何清理、结构化或摘要都必须保留回到原始证据的路径。

### 4.7 Materials、Source 与 Artifact

产品必须区分：

#### Source / Reference Material

用户上传或外部获取、用于阅读和检索的原始资料，例如简历、JD、网页、邮件、参考文档、录音和转录。它们不是因为被上传就成为 Artifact。

#### Artifact

只有用户明确要求生成某种文件格式时才创建 Artifact，例如 PDF、DOCX、Markdown、PPTX 或其他明确文件交付物。

Artifact 必须：

- 具有稳定身份；
- 内容版本 append-only；
- 当前版本由版本序列推导，不依赖可能漂移的第二指针；
- 记录生成或编辑来源；
- 区分“与岗位相关”和“某个精确版本已实际提交”；
- 对已提交版本保存确认依据或外部 receipt/read-back；
- 后续编辑不得改写历史提交快照。

普通 Agent 回答不是 Artifact。系统不得在普通回答后默认创建 Artifact，也不得通过默认“保存回答”逻辑绕过“用户明确要求文件格式”的产品原则。

### 4.8 Offer

Offer 表示某个 JobOpportunity 当前确认的 Offer 条款投影。它必须：

- 每个 Opportunity 至多一个当前 Offer 投影；
- 对每项条款保留实际来源；
- 区分书面、口头、Observation、Artifact 和外部 receipt 等来源；
- 对冲突条款先生成差异，不静默覆盖；
- 通过确认后的 supplement 或 replace 更新；
- 将接受、拒绝等决定记录为 Process Event，而不是 Offer 自己的隐藏 decision 字段。

“比较 Offer”是 Agent Skill/Planning Recipe。实际读取、确认条款、创建决策材料和记录决定仍由独立原子操作完成。

### 4.9 AbilitySignal 与成长

AbilitySignal 是一次或局部、带 Evidence 的能力观察。它表达“在特定来源、时间与适用范围内观察到了什么”，不是 CareerProfile 的正式事实，也不是长期能力结论。

它必须支持：

- 能力主题与信号类型；
- 语义总结、优势和局限；
- 适用范围；
- 形成时间；
- 置信度；
- rubric/version（如使用量表）；
- 一个或多个真实 Source Reference；
- dispute、invalidate 和 supersede；
- 用户修正与来源删除后的重新计算。

Memory Runtime 负责对同一能力的多个有效 AbilitySignal 做长期聚合、冲突处理和语义更新，形成专门的 Learned Memory：`AbilityUnderstanding`。AbilityUnderstanding 不得覆盖 CareerProfile 或其他 Canonical State。

前端 `AbilityProfile` 是 AbilityUnderstanding、AbilitySignal、Evidence 和趋势的展示投影。任何分数、雷达图和趋势值都只是有 rubric/version 与证据约束、可重新计算的 View Projection，不是后端永久能力事实，也不能成为脱离来源的永久人格标签。

用户必须能够查看来源、提出异议、修正、失效和删除相关能力观察与长期理解。来源被删除或 AbilitySignal 失效后，Memory Runtime 必须重新计算受影响的 AbilityUnderstanding，前端投影随之更新。

### 4.10 Observation 与 Communication

邮件、日历、招聘平台和其他外部系统产生的是 Source Asset 与 Observation，而不是 Agent 指令。

Observation 必须包含：

- provider / connector identity；
- 外部对象 identity；
- version / cursor / fingerprint；
- occurred / received / observed time；
- 最小必要 source snapshot；
- 当前处理状态；
- 可选的候选关联和分类置信度。

Observation 只有通过明确 Atomic Application Operation 才能：

- 关联 JobOpportunity；
- 形成 Process Event；
- 创建或更新 Interview；
- 形成 Offer 候选；
- 产生需要用户确认的事实候选。

外部 Connector 保留其 Provider 特有的快照和游标；Career Domain 不需要一个会吞并所有 Provider 语义的通用 Communication 表。

### 4.11 领域事件

Domain Event 表示求职世界已经发生的正式状态变化。它不同于 Agent 执行事件和 UI 更新事件。

Domain Event 至少应携带：

- event identity；
- aggregate / owner identity；
- operation identity；
- actor kind 与 actor identity；
- occurred time；
- schema version；
- source / evidence reference；
- 与新状态相关的最小 typed payload。

Domain Event 可用于投影、通知和后续 Observation，但不能被 Prompt 文本替代。

### 4.12 Domain Kernel 不变量

1. 一个正式事实只有一个权威所有者。
2. 用户数据必须按 owner 隔离。
3. 模型推断先形成候选或低权威资产。
4. 历史事实通过 append/retract/supersede 修正，不原地伪造过去。
5. 当前投影必须能由权威事实重建或核对。
6. 跨对象事务只包含同一业务意图必然产生的确定性变化。
7. 开放式推理不得藏在领域实体或数据库触发器中。

---

## 5. Shared Application Operations

### 5.1 唯一业务执行边界

Atomic Application Operation 是 UI、Agent 和 Automation 改变或读取 Career Domain 的共同执行边界。

```text
UI Adapter ──────────┐
                    │
Agent Tool Adapter ─┼── Application Operation ── Domain Kernel
                    │
Automation Adapter ─┘
```

所有正式业务规则、所有权校验、状态前置条件、事务、幂等、Evidence 要求和后置验证都必须在共享 Operation 或其调用的 Domain Service 中实现一次。

### 5.2 Operation 类型

#### Command

改变 Canonical State 或创建正式领域记录，必须具备明确业务意图、授权和幂等语义。

#### Query

读取权威状态或构建有范围的领域视图。Query 不得产生隐藏写入。

#### Projection

为 UI、Agent Context 或通知编译可重建视图。Projection 不是第二事实源。

#### External Action

对外部系统产生副作用。它通过 Integration Port 执行，并必须有 receipt/read-back/reconciliation 语义。

### 5.3 业务原子的判断标准

一个 Atomic Application Operation 必须：

1. 能用一个明确的业务动词描述；
2. 对应一个清晰的用户或系统意图；
3. 只有一个主要授权边界；
4. 具有稳定的幂等身份与请求指纹；
5. 有明确前置条件；
6. 有明确后置条件；
7. 能作为一个确定性事务成功、拒绝或失败；
8. 不包含开放式模型推理；
9. 不隐藏额外的用户决定；
10. 执行结果可以验证；
11. 对必须同步变化的多张表保持领域内聚；
12. 失败时可以给出 typed、可恢复的原因。

业务原子不等于一条 SQL，也不等于一个字段。已批准的首个垂直切片将 `confirm_interview_invitation` 冻结为一个确定性事务：它确认邀请候选或用户明确陈述的邀请事实，创建或关联正确的 JobOpportunity，创建或更新 Interview，追加 Process Event，绑定 Evidence，并产生对应 Domain Events 与可核对的新投影，因为这些变化都是同一确认必然产生的结果。

该 Operation 不得顺便创建 Next Action、生成面试准备计划、发送邮件、写入 Calendar、修改 Profile 或创建长期自动化，因为这些是新的意图或授权边界。Next Action 只有在邀请事实本身已经建立真实用户行动，或用户另行接受 Recommendation 时，才能通过独立 Operation 创建。

### 5.4 Operation Contract

每个 Operation 的正式契约至少定义：

| 字段 | 要求 |
|---|---|
| name / version | 稳定业务名称和 schema version |
| intent | 解决的单一业务意图 |
| actor | user、agent-on-behalf、automation、system connector 等 |
| input | typed input，不接受任意字段写入 |
| owner scope | 用户和对象所有权边界 |
| preconditions | 当前版本、状态、连接、来源和权限条件 |
| effect | read、draft、internal/canonical write、client action、external write 等 |
| idempotency | key、fingerprint 和 replay 结果 |
| evidence | 必需来源及其版本要求 |
| confirmation | 是否需要当前调用确认或预授权范围 |
| transaction | 同一意图内的原子变化 |
| result | typed result 与新版本/identity |
| domain events | 成功后形成的正式事件 |
| verification | 本地核对、receipt、read-back 或 reconciliation |
| failures | conflict、stale、denied、unavailable、unknown 等 |
| adapters | UI、Agent、Automation 的允许入口 |

### 5.5 能力平权，不是接口复制

UI、Agent 和 Automation 必须拥有相同语义和相同业务粒度，但不要求每个按钮、HTTP endpoint 与 Tool 一一对应。

- UI 可以通过表单适配一个 Operation；
- Agent Tool 可以增加 Turn、Tool Call、Evidence 和 Policy Context；
- Automation 可以增加 PersistentTask、Trigger 和预授权范围；
- 三者最终调用同一个 Operation Contract；
- 账号注册、OAuth callback、运维管理等非 Career Domain 接口不因“平权”而自动暴露给 Agent。

### 5.6 Agent Tool Adapter

Agent Tool Adapter 必须保持薄：

- 把 Tool input 解析为 Operation input；
- 注入当前用户、Turn、Task、调用和授权身份；
- 暴露 effect、资源 identity、并发安全和验证要求；
- 调用共享 Operation；
- 把 typed result 投影为模型和 Experience 可消费的结果。

Tool Adapter 不得：

- 复制领域状态机；
- 直接写数据库；
- 自行生成业务幂等语义；
- 绕过 Operation 做隐藏的多对象写入；
- 把模型生成文本当成执行事实。

### 5.7 Skill、Plan 与复杂目标

高层目标应由 Agent 组合原子能力完成。例如：

- 准备面试；
- 推进求职流程；
- 比较 Offer；
- 调整求职方向；
- 根据复盘安排训练。

这些高层目标可以表现为 Skill、Planning Recipe、Task Template 或 AgentTask。它们可以建议步骤和完成条件，但不能隐藏实际调用、授权边界、中间结果和失败。

对于边界清晰、无需每一步重新推理的组合，可以使用确定性 Workflow；对于步骤必须根据环境结果动态调整的任务，使用 Agent Loop。两者都只能通过共享 Operation 改变正式状态。

### 5.8 初始 Operation 族

以下是目标能力族，不是冻结的完整 API/Tool 清单：

- CareerProfile：读取、提出候选、确认、拒绝、修正方向；
- Opportunity：创建、编辑身份信息、关联方向、合并/撤回合并；
- Process：追加事实、修正事实、确认外部 Observation；
- NextAction：创建、接受建议后规划、改期、完成、关闭；
- Interview：确认邀请、更新安排、创建记录、完成、保存复盘；
- Materials：登记 Source、生成明确 Artifact、追加版本、关联、记录提交；
- Offer：登记、补充、替换确认、读取差异、记录决定；
- Ability：形成有证据候选、争议、失效、替代；
- Observation：摄取、匹配候选、确认、否决、撤回；
- Memory：查看、修正、失效、删除、提升为明确 Preference；
- Automation：创建、更新、暂停、恢复、删除和手动触发；
- Client Action：打开、聚焦、预填和进入目标工作区。

完整目录必须在独立 Operation Catalog 中逐项冻结，主蓝图不承担接口枚举职责。

### 5.9 并发、幂等与重放

- 每个写 Operation 必须拥有请求幂等键与内容指纹；
- 相同 key、相同 fingerprint 的重试返回原结果；
- 相同 key、不同 fingerprint 必须冲突；
- 修改已存在对象时应使用 expected version/CAS；
- 对同一资源的冲突副作用必须串行或拒绝；
- 已验证成功的 Operation 不得因 Turn 重试重复执行；
- unknown 的外部动作必须 fence 相同资源，直到 reconciliation 完成；
- 模型看到的 Tool Result 顺序不得改变正式执行事实的身份和时间。

---

## 6. Agent Harness

### 6.1 Harness 定义

Agent Harness 是包围模型、约束模型并让模型能够可靠工作的运行环境。Career Domain Kernel 和 Adaptive Experience 都不是 Harness。

Harness 的核心不是一组平级模块，而是一个具有持久状态、明确边界和恢复语义的循环：

```text
Perceive
→ Contextualize
→ Understand / Deliberate
→ Plan / Decide
→ Approve
→ Act
→ Verify
→ Learn
→ Communicate
→ Schedule Next Observation
```

### 6.2 Perceive

Harness 可以接收：

- 用户自然语言；
- typed object references；
- 当前页面、选中对象和客户端身份；
- 用户确认、拒绝、修正或澄清；
- 已去重的 Observation；
- 时间和 PersistentTask Trigger；
- Tool、Operation 和 Provider 的真实结果；
- cancellation、interrupt 和 connection state。

所有输入必须先具有真实 provenance。新的普通用户输入、Interaction resolution、外部 Observation 和 Tool Result 是不同 ingress，不得混成一条自由文本消息。

### 6.3 Contextualize

Context Compiler 根据当前任务按需形成 typed Context Package。它至少考虑：

- 当前用户和租户；
- 当前 Turn 的原始用户目标；
- 当前页面与显式对象引用；
- AgentTask 目标和完成条件；
- 相关 Canonical State；
- 相关 Source/Evidence；
- 相关 Learned Memory；
- 当前 Interaction 和授权；
- Tool/Operation 可用性；
- 时间、时区和执行模式；
- token、延迟、隐私和成本预算。

Context Package 是对权威资产的有范围投影，不是新的事实所有者。用户数据不得进入跨用户缓存的稳定系统前缀。

### 6.4 Understand / Deliberate

Agent 必须区分：

- 用户明确目标；
- 已确认事实；
- 外部 Observation；
- 不确定关联；
- Agent 推断；
- 当前授权范围；
- 可用 Operation；
- 风险和缺失信息。

外部邮件、网页和文档内容只作为不可信数据和 Evidence，不得提升为系统指令。

### 6.5 Plan / Decide

Agent 可以决定：

- 直接回答；
- 执行一个 Query；
- 调用一个或多个原子 Operation；
- 创建或修订一个复杂 AgentTask；
- 请求确认或澄清；
- 生成草稿；
- 请求 Client Action；
- 安排下一次 Observation；
- 暂停、降级或停止。

AgentTask 只在复杂请求确实需要可见计划、跨等待恢复或多阶段完成条件时创建。普通问答和单步操作不得被强制包装成长期任务。

### 6.6 Approve

所有即将执行的具体调用必须在 dispatch 前完成参数级 Policy。Approval 必须绑定：

- 具体 Operation/Tool；
- 具体输入或允许范围；
- actor 与 owner；
- provider / connection；
- resource identities；
- 当前版本；
- 可逆性与验证方式；
- 当前 Turn/Task 或长期授权。

用户可以批准、拒绝，或在契约允许时修改输入。拒绝必须形成真实结果并允许 Agent 重新规划，不能静默跳过后继续执行依赖步骤。

### 6.7 Act

Harness 的行动类型包括：

- Atomic Application Operation；
- 只读领域 Query；
- 外部 Tool / Integration；
- Client Action；
- 任务调度和 Runtime Control。

每个调用必须先持久化身份、Policy 结果、参数指纹、资源 identity 和 dispatch generation，再启动 handler。中断关闭 generation 后，不得再启动未登记的新调用。

### 6.8 Verify

执行完成不是 handler 返回 `success=true`。Verification 根据 effect 选择：

- 事务后读取新 Domain State；
- version、event 或 immutable snapshot 核对；
- 外部 receipt；
- Provider read-back；
- 资源存在性和内容校验；
- 部分成功分析；
- unknown 状态记录；
- 补偿或 reconciliation。

外部副作用结果不确定时必须保留原调用 identity，并 fence 冲突操作；迟到 receipt 追加到原执行记录，但不得复活已取消 Turn。

### 6.9 Learn

Learn 阶段可以：

- 更新 AgentTask 阶段和完成条件；
- 形成 Learned Memory Candidate；
- 形成或修订带 Evidence 的局部 AbilitySignal；
- 触发 Memory Runtime 重新计算受影响的 AbilityUnderstanding；
- 更新低权威个性化模式；
- 记录某种方法对用户有效或无效；
- 安排下一次 Observation。

Learn 不得直接把模型总结写入 CareerProfile、Process Event、Offer、Next Action 或其他 Canonical State。任何正式变化仍需对应 Operation。

### 6.10 Communicate

Harness 必须通过 typed events 向 Adaptive Experience 表达：

- 正在理解；
- 上下文或目标已更新；
- 已形成计划；
- 正在调用何种能力；
- 为什么需要确认；
- 正在等待连接、用户或外部结果；
- 正在验证；
- 已完成、部分完成、失败、取消或结果未知；
- 用户下一步可以做什么。

文本只是其中一种输出。前端不得通过解析自然语言猜测 Agent 运行状态。

### 6.11 Schedule Next Observation

下一次 Observation 可以来自：

- 已确认 PersistentTask 的 schedule；
- 外部 connector event subscription；
- 已计划 Next Action 的提醒；
- 当前 Operation 的 follow-up；
- unknown 外部结果的 reconciliation；
- 用户明确要求的后续检查。

Agent 不得仅凭一次普通建议静默创建长期自动化。PersistentTask 必须有用户确认的目标、读取范围、行动范围、可用能力和暂停/删除入口。

### 6.12 Conversation / Turn Kernel

Turn 是一次被接纳输入到终态的统一执行容器。它不等于 AgentTask、NextAction 或 PersistentTask。

Kernel 必须负责：

- 输入幂等接纳；
- active Turn CAS；
- FIFO PendingSubmission；
- user input 与 automation trigger 的 provenance；
- durable status 与 heartbeat；
- model/tool dispatch fence；
- waiting 与同一 Turn 恢复；
- explicit interrupt；
- cancellation；
- terminalization；
- 下一输入的原子 handoff；
- reconnectable event stream。

普通 Composer 输入在 active Turn 期间只形成 PendingSubmission，不得 mid-turn 冒充 approval 或自动改变当前目标。Interaction resolution 只恢复原 Turn，不消费普通输入队列。

### 6.13 Model Runtime

Model Runtime 负责：

- Provider-neutral request；
- 模型选择与能力检查；
- streaming；
- timeout 与 error classification；
- retry 与 bounded recovery；
- fallback；
- server-reported usage；
- context window 与 output reserve；
- provider prompt cache；
- context reduction / compaction；
- per-call cost 与 latency。

Provider 优化不得改变请求的完整语义。Tool、稳定 system instructions 和动态 user context 必须保持可解释的独立分区。

### 6.14 Tool 与 Operation Discovery

Agent 只应看到当前任务、权限、Edition 和连接状态下可用的能力。大量 Tool/Operation 应支持按域索引与渐进披露，避免把全部 schema 永久塞入上下文。

每个 Tool 必须具有：

- typed input schema；
- effect；
- handler identity；
- connection/provider identity；
- resource identity resolver；
- concurrency safety；
- interruption behavior；
- result budget；
- verification contract；
- user-facing display metadata。

### 6.15 Durable Execution

Durable Execution 负责：

- Tool Call 与 Model Dispatch 的持久身份；
- dispatch generation 和 owner fence；
- exactly-once effect 或可证明的幂等重放；
- batch preflight；
- 资源冲突；
- 等待确认后的同一调用恢复；
- Worker 重启和 orphan repair；
- 取消树；
- 迟到结果；
- completion order 与 model replay order 的分离。

### 6.16 Observation and Proactivity Runtime

该 Runtime 负责连接确定性触发与 Agent 决策：

- 观察摄取；
- cursor/CAS 与 deduplication；
- source snapshot；
- trigger merge；
- urgency 和 relevance；
- quiet hours 与频率预算；
- reversible auto-action scope；
- pending confirmation；
- pause/resume；
- schedule repair。

主动性质量必须通过评测和用户反馈控制。系统可以选择“不行动”；不得为了展示主动性而制造无意义建议。

### 6.17 Memory Runtime

Memory Runtime 负责：

- 候选提取；
- eligibility 和敏感信息过滤；
- selective recall；
- consolidation；
- 冲突识别；
- 对同一能力的多个有效 AbilitySignal 进行长期聚合、冲突处理和语义更新；
- 形成、修订、降置信度或失效专门的 Learned Memory `AbilityUnderstanding`；
- 更新、降置信度和 supersede；
- 来源删除与 AbilitySignal 失效传播，并触发受影响 AbilityUnderstanding 的重新计算；
- invalidation、deletion 和 forgetting；
- 用户管理；
- 将用户明确确认的内容提升到正确的 Canonical Preference，而不是继续留在 Memory。

Memory producer 与 recall 必须分别可控，并接受发布评测门禁。

### 6.18 单一责任 Agent 与并行边界

本蓝图要求每个 Turn 有一个最终负责理解目标、承接 Policy 结果和向用户交付的责任 Agent。它允许对真正无数据依赖、资源不冲突且可独立失败的 Tool Call 做安全并行。

本蓝图不要求多 Agent、swarm 或长生命周期 peer。未来如引入额外执行者，必须先定义独立上下文、权限委派、取消、成本、结果协议、写冲突和用户可见性，并通过真实产品评测证明其必要性。

---

## 7. Career Data Assets

### 7.1 资产分类与所有权

| 资产类别 | 典型内容 | 权威所有者 | 权威级别 | 默认生命周期 |
|---|---|---|---|---|
| Canonical Career State | Profile、Opportunity、Process Event、Next Action、Interview、Offer | Career Domain Kernel | 最高业务权威 | Durable Canonical |
| Source Assets | 简历、JD、邮件、日历事件、网页、录音、转录、参考资料 | 对应 Source/Integration/Domain owner | 原始来源 | Durable Source 或按政策保留 |
| Evidence and Provenance | source refs、版本、时间、receipt、verification、correction | 使用证据的具体领域 owner | 证明关系 | 随权威记录保留 |
| Learned Memory | 低权威偏好、方法效果、长期模式、AbilityUnderstanding | Memory Record；生命周期由 Memory Runtime 管理 | 低于 Canonical | Durable but revisable |
| Execution Assets | Conversation、Turn、AgentTask、Tool Call、Approval、Verification、Trigger | Agent Harness | 执行事实 | Audit/retention policy |
| Working and UI Context | 页面、选中对象、草稿、客户端、当前面板 | Adaptive Experience / Context Compiler | 临时上下文 | client/session/turn scoped |

Career Data Assets 是治理分类，不要求共同物理继承、共同表结构或共同存储介质。

### 7.2 Canonical Career State

Canonical State 必须：

- 有明确 user owner；
- 由领域允许的 Operation 产生；
- 有版本、事件或其他并发控制；
- 可被用户查看和修正；
- 不因模型输出或 Memory Recall 自动改变；
- 对历史事实保留修正轨迹。

### 7.3 Source Assets

Source Asset 保存“来源实际是什么”，不得保存“Agent 希望它是什么”。它应尽可能保留：

- provider / owner；
- identity；
- immutable version 或 checksum；
- observed time；
- content availability；
- deletion / revocation 状态；
- scope 与用户所有权。

大文件正文不必进入模型上下文；Context Compiler 只读取与当前任务相关的片段、摘要、结构或视觉证据。

### 7.4 Evidence and Provenance

Evidence 是具体记录之间的 typed 关系，而不是一个会复制所有正文的通用仓库。

Evidence 必须回答：

- 哪个结论或状态由什么支持？
- 来源属于谁？
- 读取的是哪个版本？
- 何时发生、何时被观察？
- 是用户陈述、外部 Observation、Tool Result 还是 Provider Receipt？
- 来源是否仍存在、已撤回或已删除？
- 当前结论是否已被 supersede 或 dispute？

### 7.5 Learned Memory Records

Memory Record 至少包含：

- semantic identity；
- content；
- applicability / scope；
- source references；
- formed time；
- confidence；
- valence 或效果语义；
- last confirmed / recalled time；
- conflict / supersession；
- revision/version；
- status；
- invalidate 和 delete 状态。

Memory 不保存精确历史替代品、产品事实、权限、当前任务状态或系统指令。用户删除的 Memory 不得仅通过换 semantic key 自动复活。

`AbilityUnderstanding` 是专门的 Learned Memory。它由 Memory Runtime 基于同一能力的多个有效 AbilitySignal 聚合形成，必须保留所依赖的 Signal 与 Evidence、适用范围、冲突、语义修订、置信度和重新计算版本。它不是 CareerProfile 正式事实，也不得把推测提升为 Canonical State。

前端 `AbilityProfile` 只消费 AbilityUnderstanding、AbilitySignal、Evidence 和时间趋势形成展示投影。分数、雷达图和趋势值不得作为独立的永久能力事实持久化；它们必须能够在来源删除、Signal 失效、用户修正或聚合规则版本变化后重新计算。用户必须能够从投影回到来源，并对相关 Signal 或 AbilityUnderstanding 提出异议、修正、失效和删除请求。

### 7.6 Execution Assets

Execution Assets 记录系统实际做过什么，而不是产品业务事实本身：

- Conversation / Turn；
- PendingSubmission；
- AgentTask / Plan Revision；
- Model Dispatch；
- Tool Call / Operation Run；
- Interaction / Approval；
- External Receipt / Verification Result；
- PersistentTask / Trigger；
- Trace 和成本数据。

执行资产可以引用 Domain identity，但不得复制一份可漂移的完整 Domain State。

### 7.7 Working and UI Context

Working/UI Context 可以包含：

- 当前页面或体验表面；
- 当前选中的 Opportunity、Interview 或 Source；
- 当前展开的面板；
- 表单草稿；
- 客户端身份；
- 当前 Copilot 关联对象；
- 短期交互偏好。

只有跨刷新、跨设备、恢复或审计确实需要的部分才持久化。视觉状态和临时交互不得默认进入长期 Memory。

### 7.8 System Prompt 与数据资产分离

System Prompt 只保存稳定内容：

- Agent 身份与产品使命；
- 行为和真实性原则；
- 权限与用户控制原则；
- Operation/Tool 使用规则；
- 不确定性与错误处理；
- 输出协议。

用户档案、岗位、邮件、资料、Memory、页面状态、Conversation summary 和运行状态属于数据资产。它们由 Context Compiler 按当前任务读取和编译，不得永久堆入 System Prompt。

### 7.9 Context Package 的权威边界

Context Package 必须标注或保留不同内容的角色：

- instructions；
- canonical facts；
- observations；
- evidence；
- low-authority memory；
- historical messages；
- current user input；
- tool/operation schemas；
- runtime controls。

模型可使用 Context Package 推理，但 Context Package 本身不是新资产所有者。压缩、摘要和截断不得把低权威内容提升成事实，也不得删除当前用户原始目标。

### 7.10 生命周期与删除

资产必须明确属于以下生命周期之一：

```text
Durable Canonical
Durable Source
Durable Learned Memory
Execution / Audit Retention
Session Context
Turn Context
Client Context
```

删除必须传播到受影响的来源关系、索引和召回资格，但不能为了“删除干净”而改写已经发生的不可变历史。需要保留最小 tombstone 时，必须限制内容和保留期限。

---

## 8. Trust、Permission 与真实性

### 8.1 Trust 不是独立内核

Trust 通过四个位置共同实现：

1. Domain Kernel 的来源、状态和修正规则；
2. Career Data Assets 的 Evidence、receipt 和 provenance；
3. Agent Harness 的 Policy、Approval、Verification 和 Recovery；
4. Adaptive Experience 的依据展示、确认、修正和撤销。

不得把 Trust 简化为一个 Prompt 章节或一个布尔权限字段。

### 8.2 事实与推断边界

系统必须显示并保存内容的真实语义：

| 内容 | 是否可直接成为 Canonical State |
|---|---|
| 用户在直接 UI 中确认的事实 | 可以，通过对应 Operation |
| 用户在对话中明确陈述的事实 | 可以，但仍需 typed Operation 与所有权/冲突检查 |
| 已验证 Provider Receipt | 仅在领域规则允许的字段和事件中可以 |
| External Observation | 不自动；先作为 Observation，再通过 Operation |
| Tool Result | 不自动；取决于来源、effect 和 verification |
| Agent 推断 | 不可以，只能形成候选、建议或 Learned Memory |
| Learned Memory | 不可以 |
| Conversation Summary | 不可以 |

不存在可以跨所有领域使用的简单“来源权威排名”。每个 Operation 必须定义哪些来源足以支持哪种变化。

### 8.3 Effect 与自治等级

目标 Policy 至少区分：

- **Read**：读取允许范围内的状态和来源；
- **Draft**：生成未提交、未成为正式状态的内容；
- **Runtime Control**：维护当前 Turn/AgentTask，不改变产品事实；
- **Internal/Canonical Write**：改变产品内部正式状态；
- **Client Action**：请求客户端导航、聚焦、预填或准备输入；
- **External Write**：向邮箱、日历、招聘平台等外部系统产生副作用；
- **Unknown**：无法可靠分类的远程能力，默认 fail closed。

是否需要确认不能只由 Tool 名称决定。Policy 必须结合具体参数、当前状态、资源 identity、可逆性、用户预授权、Provider scope 和验证能力判断。

### 8.4 Approval

Approval 分为：

- 当前具体调用的一次性确认；
- 用户明确授予的、可撤销的长期范围；
- 用户明确保留每次决定权；
- 硬性拒绝，不允许通过确认绕过。

一次 Approval 不能跨越不同：

- Operation/Tool；
- 参数；
- 用户或对象；
- Provider/connection；
- resource identity；
- 风险等级；
- 版本。

如允许用户编辑待执行参数，编辑后必须重新进行 Policy、幂等和前置条件检查。

### 8.5 “待我确认”的产品边界

“待我确认”体验只聚合：

1. 外部操作批准；
2. 事实确认；
3. 个人档案更新确认。

普通 Agent 输出、一般建议、错误通知、连接设置、Client Action readiness 和 Artifact 保存推荐不得混入该聚合。它们可以拥有各自的 Interaction 或通知形式，但不是“待我确认”对象。

### 8.6 外部操作真实性

外部写操作必须经历：

```text
Prepare
→ Policy
→ Approval or Scoped Authorization
→ Dispatch
→ Receipt / Read-back
→ Reconcile
→ Verified Result or Unknown
```

以下情况不得宣称完成：

- 只生成了邮件草稿；
- 只向 Provider 发出了请求；
- 请求 timeout 且没有 receipt；
- Tool 返回了模糊 success 字符串；
- 页面跳转成功但业务动作尚未提交；
- 外部系统返回部分成功；
- read-back 与预期状态不一致。

### 8.7 可逆性与修正

“可逆”必须有真实的逆操作或领域修正语义，不能只因为数据库可以更新就认为可逆。

- Process Event 通过 retraction/replacement 修正；
- Profile 通过版本化修改和候选确认修正；
- AbilitySignal 通过 dispute/invalidate/supersede 修正；
- Memory 通过 edit/invalidate/delete 修正；
- 外部邮件发送通常不可逆；
- Client Action 可以可逆，但它不能被误当成业务操作已经完成。

### 8.8 Prompt Injection 与不可信来源

邮件、网页、JD、简历、MCP 结果和用户上传资料中的文本都可能包含指令形内容。系统必须：

- 将其标记为数据而非 system instruction；
- 限定来源可调用的 Operation；
- 不允许内容自行扩大权限；
- 对外部 URL 和远程连接执行 SSRF、身份和 scope 校验；
- 对凭据、Token、个人敏感信息和 Tool 结果进行脱敏；
- 对未知 MCP effect 默认 ask/deny；
- 在执行前重新做参数级 Policy。

### 8.9 隐私与最小化

Context、trace、日志和评测数据必须遵守最小必要原则：

- 不向模型发送当前任务不需要的用户资产；
- 不在跨用户 Prompt Cache 中放入私人数据；
- trace 默认不记录明文凭据和无界文件正文；
- 外部 Provider 只获得完成任务所需的最小内容；
- 用户可以查看连接、权限、Memory 和自动化范围；
- 删除和导出必须覆盖正式数据、来源、索引和衍生召回资格。

### 8.10 主动性预算

主动性必须受以下约束：

- 用户授权的 trigger 与 scope；
- 安静时间；
- 通知频率；
- 重复建议去重；
- 同一对象的冷却窗口；
- 每日/每周成本预算；
- 未解决确认的数量上限；
- 用户暂停和全局关闭能力；
- 低置信度时不自动改变正式状态。

---

## 9. Adaptive Experience

### 9.1 责任边界

Adaptive Experience 负责把 Domain State、Agent Runtime 和 Evidence 转换为用户能够理解和控制的产品体验。它不拥有业务事实、Agent 队列顺序或外部执行结果。

### 9.2 体验设计原则

1. **目标优先**：围绕用户要完成的求职目标组织，而不是围绕表和接口。
2. **直接操作优先**：确定性小操作无需调用模型。
3. **Agent 可见**：复杂执行要显示目标、状态、确认和结果。
4. **证据就近**：判断和状态旁边显示来源，而不是藏在调试页。
5. **渐进披露**：默认简洁，需要时展开完整 Tool、Operation、receipt 和历史。
6. **用户可修正**：事实、Memory、关联和 Agent 理解必须有明确修正入口。
7. **失败可恢复**：显示失败发生在哪一步、是否产生副作用和如何继续。
8. **不依赖聊天**：用户可以完全通过普通 UI 完成核心求职流程。
9. **不伪造进度**：动画和状态必须由真实 Harness/Domain Event 驱动。

### 9.3 冻结的产品级信息架构与可变呈现

产品级信息架构冻结以下入口及其职责：

| 层级 | 入口 | 冻结的产品职责 |
|---|---|---|
| 一级入口 | `今天` | 投影用户当前需要行动、确认和了解的四类信息；具体边界见 9.8。 |
| 一级入口 | `求职` | 发现和管理机会，管理多个 JobOpportunity、求职流程、真实 Next Action、流程沟通与 Offer 上下文。 |
| 一级入口 | `面试` | 组织面试准备、模拟训练、真实面试记录、复盘，以及由面试证据产生的能力观察。 |
| 一级入口 | `资料` | 管理 Career Profile、Source Assets、求职材料，以及用户明确要求生成的 Artifact。 |
| 辅助入口 | `活动中心` | 查看 Agent 与 Automation 的运行、等待、验证、失败、恢复、历史和审计详情。 |
| 辅助入口 | `设置` | 管理个人偏好、Memory 控制、权限、连接、模型、通知和自动化策略。 |

Copilot 是横跨整个产品的自然语言交互与执行层，不是普通一级导航页面。它必须能够携带当前产品对象和工作上下文，并通过 Shared Application Operations 在所有相关体验中理解、执行、解释和验证用户意图。

本节冻结的是入口名称、产品层级和职责边界，不冻结物理路由、组件结构、视觉稿或具体呈现方式。Copilot 可以采用全局常驻、上下文浮层、对象工作区或其他组合呈现，但任何体验实现都不得改变其跨产品角色，也不得为不同入口复制业务规则。

### 9.4 语义交互与页面上下文

自然语言输入应携带 typed、低权威页面上下文，例如：

- 当前 route/surface；
- 当前选中对象的 kind 与 identity；
- 当前可见的表单或工作区；
- source client identity；
- 用户显式附加的对象和文件；
- 用户草稿。

Agent 不得从 DOM 文本猜测正式对象，也不得通过模拟不稳定点击操控产品。

### 9.5 Client Action Protocol

纯客户端动作通过稳定协议暴露，例如：

- 打开某个对象工作区；
- 聚焦某个输入；
- 预填表单但不提交；
- 打开某封邮件或来源详情；
- 进入面试准备、模拟或复盘界面；
- 滚动到证据；
- 请求麦克风或其他客户端 readiness。

Client Action 必须：

- typed；
- 有 action identity 和 schema version；
- 在投递前持久化；
- 绑定适用客户端或允许显式 takeover；
- 返回 acknowledgement、refusal 或 failure；
- 不伪装成 Domain Operation；
- 不因页面关闭而自动表示 Turn 取消。

### 9.6 Agent 状态投影

Experience 至少应能投影以下状态：

- understanding；
- planning；
- executing；
- waiting for user；
- waiting for connection；
- waiting for external result；
- verifying；
- completed；
- partially completed；
- blocked；
- failed；
- cancelled；
- unknown outcome。

这些状态来自 Harness Event 与权威执行记录，不通过分析 Assistant 文本推断。

### 9.7 多流程信息架构

用户级体验必须允许：

- 跨 Opportunity 查看整体局面；
- 按方向、时间、紧迫度和当前阶段筛选；
- 在不同 Opportunity 间切换而不丢失用户级上下文；
- 将一个 Interview、Artifact、Offer 或 Next Action 关联到正确流程；
- 明确显示对象属于哪一个流程；
- 防止 Agent 因当前页面对象而忽略用户级目标。

### 9.8 Today 议程投影

Today 是现有状态的用户级投影，不是新数据所有者。它只投影以下四类内容：

1. **下一步**：已经成立的真实 Next Action；
2. **待我确认**：外部操作批准、事实确认和个人档案更新确认；
3. **求职动态**：已经确认发生的求职流程变化；
4. **Copilot 动态**：正在执行、已安排、最近完成的 Agent / Automation 活动摘要。

Recommendation 不属于 Next Action，也不作为 Today 的第五类模块。只有用户接受 Recommendation 后，系统才通过 Shared Application Operation 创建真实 Next Action。

### 9.9 修正、撤销与审计

用户必须能从结果附近进入：

- 修正事实；
- 查看 Evidence；
- 查看是谁、何时、通过什么 Operation 改变了状态；
- retract/supersede 不可变历史；
- 撤销允许撤销的内部操作；
- 查看 unknown 外部动作的 reconciliation 状态；
- 修正或删除 Memory；
- 暂停 Automation；
- 撤销长期授权。

### 9.10 体验设计顺序

```text
产品使命与场景
→ Domain State 与 Data Assets
→ 低保真用户流程
→ Interaction/Event Protocol
→ Atomic Operations 与 Permission
→ 垂直切片
→ 前后端实现
→ 高保真视觉与动画
```

前端代码可以后置，但体验流程、状态、确认、失败恢复和事件协议不能等到后端完成后才决定。

---

## 10. Interaction and Event Model

### 10.1 三类事件

#### Domain Event

表示求职世界中的正式事实变化，例如：

- `opportunity_created`；
- `process_event_appended`；
- `interview_invitation_confirmed`；
- `next_action_planned`；
- `artifact_version_created`；
- `offer_terms_confirmed`。

Domain Event 由 Domain/Application 层拥有，可用于重建投影和触发后续动作。

#### Harness Event

表示 Agent 执行生命周期，例如：

- `understanding_updated`；
- `plan_created`；
- `task_started`；
- `operation_started`；
- `approval_requested`；
- `verification_started`；
- `task_completed`；
- `task_failed`；
- `task_cancelled`。

#### Experience Event

表示客户端应如何呈现或响应，例如：

- `assistant_message`；
- `text_delta`；
- `progress_updated`；
- `evidence_attached`；
- `client_action_requested`；
- `projection_invalidated`；
- `notification_created`。

三类事件可以通过同一流传输，但所有权、持久化、回放和 schema 必须分开。

### 10.2 统一事件信封

跨进程或跨客户端传输的事件至少包含：

```text
event_id
event_kind
event_category
schema_version
occurred_at
sequence / cursor
user_id or tenant scope
conversation_id? / turn_id? / task_id?
operation_id? / tool_call_id?
object_references[]
replayable
payload
```

不得要求客户端通过字段存在与否猜测事件版本。

### 10.3 Interaction Request

Interaction 是一个 active Turn 等待的 durable typed 用户输入。它可以用于：

- clarification；
- connection；
- approval；
- fact confirmation；
- profile update confirmation；
- client readiness。

只有外部操作批准、事实确认和档案更新确认投影到“待我确认”聚合。其他 Interaction 使用各自体验。

每个 Interaction 必须包含：

- interaction identity；
- owning Turn；
- kind 与 schema version；
- request payload；
- expected version；
- allowed resolution kinds；
- timeout/expiry（如适用）；
- resolved/rejected/cancelled 状态；
- resolution provenance。

同一 Turn 同时只允许一个需要用户决定的前台阻塞 Interaction，除非未来契约明确支持并行决策及其顺序。

### 10.4 Operation Event

一个 Operation 的 Experience 投影应至少区分：

```text
operation_proposed
operation_waiting_approval
operation_started
operation_progress
operation_succeeded
operation_failed
operation_cancelled
operation_unknown
operation_reconciled
```

`operation_succeeded` 只能在 Operation 的验证契约满足后发送。

### 10.5 Streaming、持久化与重放

- SSE、WebSocket 或其他传输只是投递方式，不拥有事件语义；
- 断开连接不等于取消；
- 可重放事件必须具有稳定 cursor/sequence；
- 文本 delta 可以是临时流事件，最终文本和结构化 block 必须持久化；
- Tool start/done 必须按 call identity 配对，不依赖 FIFO 邻接；
- UI 的实时完成顺序可以反映真实时间，模型历史回放仍保持原始调用顺序；
- 重连后 UI 应从 snapshot + event cursor 恢复，而不是重放副作用；
- 未知事件版本必须安全忽略或显式降级，不得错误解释。

### 10.6 状态变化与 Projection Invalidation

Domain Operation 完成后，应发布足够的 typed identity 使客户端失效并重新读取相关 Projection，而不是在每个事件中复制完整对象。

一个状态变化可以影响：

- 对象详情；
- 用户级议程；
- Opportunity 列表；
- 待确认计数；
- Next Action；
- AgentTask；
- Evidence 视图。

Projection invalidation 必须可去重，并与新的 object version 关联。

### 10.7 错误模型

错误必须至少区分：

- validation；
- ownership；
- stale/conflict；
- policy denied；
- approval rejected；
- connection required；
- provider unavailable；
- transient retryable；
- permanent failure；
- partial success；
- unknown external outcome；
- context/resource limit；
- cancelled/interrupted。

用户消息可以本地化，但程序必须依赖 stable error code 和 typed recovery options，而不是匹配中文错误文本。

### 10.8 协议版本化

- Event、Interaction、Client Action 和 Operation input/output 分别版本化；
- additive 字段默认向后兼容；
- 删除或改变语义必须提升版本；
- durable pending 记录必须保存当时 schema version；
- resume 时使用原契约或执行显式迁移；
- 前端和后端契约应由可生成类型的 schema 管理，避免手工镜像漂移。

---

## 11. 质量与评测

### 11.1 评测是发布门禁

Agent 功能不能仅凭单元测试或演示判断完成。每个核心能力必须同时具有：

- 确定性领域测试；
- Operation Contract 测试；
- Policy/Approval 测试；
- Harness 恢复测试；
- 端到端场景评测；
- 真实性和 Evidence 评测；
- 失败、取消和重复输入测试；
- 用户体验状态投影测试。

### 11.2 Domain 正确性

必须评测：

- 所有权隔离；
- 状态机合法性；
- append-only 历史；
- 修正与 supersession；
- CAS 和幂等；
- Projection 可重建；
- Evidence 完整性；
- 删除和失效传播。

### 11.3 Agent 任务成功

场景评测必须按真实用户目标衡量：

- 是否理解了正确对象和范围；
- 是否选择了正确 Operation；
- 是否遗漏必要步骤；
- 是否在应确认时确认；
- 是否在不应确认时制造摩擦；
- 是否正确处理失败和重规划；
- 是否满足完成条件；
- 是否给出与真实结果一致的最终沟通。

不得仅用“最终回答看起来合理”作为成功标准。

### 11.4 Tool 与 Operation 选择

评测至少覆盖：

- 不调用无关 Tool；
- 不绕过共享 Operation；
- 不使用宏 Tool 隐藏副作用；
- 不把 Query 当 Command；
- 不重复执行已成功操作；
- 不在未知外部副作用未解决时冲突写入；
- 能在能力不可用时解释并降级。

### 11.5 Permission 与安全

必须验证：

- 参数级 effect；
- exact-call approval；
- retained authorization scope；
- Provider scope；
- connection identity；
- hard deny 不可绕过；
- unknown effect fail closed；
- prompt injection 不扩大权限；
- 用户撤销后停止未来执行。

### 11.6 Memory 质量

Memory producer 和 recall 必须分别评测：

- 是否只从合格来源形成；
- 是否避开敏感或不适合长期保存的信息；
- 是否保持低权威；
- 是否在相关任务才召回；
- 是否识别冲突和时效；
- 是否在来源删除后失效；
- 是否尊重用户 edit/invalidate/delete；
- 是否避免已删除内容复活；
- 是否实际改善任务结果而非增加噪声。

未通过门禁时，自动 producer 必须默认关闭。

### 11.7 主动性质量

必须度量：

- observation precision/recall；
- 匹配正确率；
- 重复建议率；
- 用户接受、忽略和拒绝率；
- 错误打扰率；
- 错过高优先级事件率；
- 自动操作可逆和验证成功率；
- quiet hours 与频率预算遵守率；
- 关闭/暂停后的零越权执行。

### 11.8 Verification 与恢复

必须进行：

- Worker kill；
- Provider timeout；
- SSE disconnect；
- approval 后恢复；
- partial success；
- late receipt；
- duplicate trigger；
- stale version；
- same-resource conflict；
- unknown outcome reconciliation；
- cancellation 与新输入 handoff。

### 11.9 Observability

每个端到端运行应能够关联：

- ingress identity；
- conversation/turn/task；
- model dispatch；
- context composition 与 token budget；
- tool/operation call；
- policy/approval waiting time；
- provider/connection；
- verification；
- domain events；
- final outcome；
- latency、token、cache 和 cost；
- recovery attempt。

Trace 中的敏感内容必须可配置、默认最小化。Observability 不能依赖单一商业 Provider 才成立。

### 11.10 评测分层

```text
Unit Invariants
→ Contract Tests
→ Runtime Recovery Tests
→ Vertical Slice Scenarios
→ Offline Agent Evals
→ Controlled Live Connector Evals
→ Production Monitoring and Feedback
```

任何上层门禁不能替代下层确定性测试。LLM-as-judge 可以辅助语义评估，但不能单独裁定权限、幂等、Evidence 和外部真实性。

---

## 12. 目标工程架构

### 12.1 目标物理边界

目标代码应逐步形成以下责任边界。目录名称可以在实施规格中微调，但所有权和依赖方向不得改变。

```text
backend/app/
  career/
    domain/             实体、值对象、不变量、领域事件、纯领域策略
    application/        Atomic Operations、Queries、Projections、Ports

  harness/
    kernel/             Conversation、Turn、admission、waiting、interrupt、terminalization
    context/            Context Compiler、Context Package、compaction、source assembly
    loop/               Agent loop、decision、AgentTask、completion gate
    operations/         Tool/Operation adapters、registry、discovery、executor
    policy/             effect、permission、approval、resource scope
    execution/          model/tool dispatch、fence、retry、recovery、reconciliation
    memory/             Memory Runtime
    observation/        proactive intake、trigger、schedule bridge
    events/             Harness event 与 interaction contract
    observability/      trace、metrics、cost、audit projection

  integrations/         Gmail、Calendar、Web、Job Provider、remote MCP 等 adapters
  rag/                  scoped retrieval、grounding、citation、ingestion
  preferences/          用户明确设置与确认偏好
  infrastructure/       DB、Redis、queue、object storage、vector、provider clients
  api/                  HTTP/SSE presentation adapters

frontend/src/
  experience/           体验表面与工作区
  projections/          Domain/Harness read projections
  interactions/         approval、confirmation、client actions
  api/                   生成或严格绑定的协议客户端
```

实施时不得一次性创建这些全部空目录。边界应由第一个真实垂直切片建立，并在迁移相应所有权时创建。

### 12.2 Domain 与 Application 分离

`career/domain` 不依赖：

- FastAPI；
- React；
- SQLAlchemy Session；
- Celery；
- 模型 SDK；
- Vector Database；
- MCP；
- Provider API。

`career/application` 负责编排事务、owner lookup、Port、幂等与 Domain Event 发布。数据库实现可以通过 repository/transaction port 或受控 infrastructure adapter 提供；是否引入完整 Repository 抽象取决于真实用例，不能为了目录美观创建空接口。

### 12.3 Harness 与 Domain 的调用边界

Harness 不直接 import 具体业务 service 集合。它通过 Application Operation Registry/Port 获取：

- Operation schema；
- effect 与 policy metadata；
- resource identity；
- handler port；
- verification contract；
- result schema。

具体 Career Tool Adapter 可以位于 Harness 外缘并依赖 Application Port，但不能把领域业务实现写进 Tool 文件。

### 12.4 Operation Registry

目标系统需要一个显式、可测试的 Application Operation Catalog。它不是 HTTP route registry 或 Tool registry 的别名。

Catalog 应能回答：

- 产品有哪些可执行业务行为？
- 哪些入口可以调用？
- effect 和授权是什么？
- 输入、结果和错误 schema 是什么？
- 哪些资源会被读取或修改？
- 如何验证结果？
- 对应哪些 Domain Event？

API route 与 Agent Tool 分别绑定 Catalog 中的 Operation。架构测试应阻止它们绕过 Operation 直接复制业务逻辑。

### 12.5 事务、Outbox 与外部副作用

内部 Operation 的 Domain State、Domain Event 和必要执行引用应在一个事务边界内提交。

外部动作不得把数据库事务跨网络保持打开。目标模式为：

```text
Persist intent / dispatch identity
→ commit
→ external call
→ persist receipt or unknown
→ read-back / reconcile
→ publish verified projection
```

需要可靠异步投递时使用 Outbox。重试依赖幂等 identity，不依赖“Worker 大概率只执行一次”。

### 12.6 Queue 与长时执行

不同工作负载可以使用独立队列，例如：

- interactive turns；
- transcription / media pipeline；
- ingestion / analysis pipeline；
- background observation and automation；
- maintenance / default。

队列是 Infrastructure，不拥有 Turn 或业务任务状态。权威运行身份保存在数据库；Worker 只是 lease owner。

### 12.7 数据存储

- PostgreSQL 保存 Canonical State、Execution Assets、配置和来源元数据；
- 对象存储保存用户文件和大体积 Source/Artifact bytes；
- 向量索引是可重建的检索投影，不是事实源；
- Redis 用于缓存、队列和短期协调，不作为不可恢复的唯一状态；
- JSON/JSONB 只用于有界、版本化、领域类型明确的结构，不得成为逃避模型设计的万能字段；
- 所有时间使用带时区 UTC 存储，并保留用户原始时间文本与源时区（如业务需要）。

### 12.8 Provider 与模型边界

模型请求先形成 provider-neutral 语义，再由 Adapter 转换为 Anthropic、OpenAI-compatible 或其他 Provider 的物理请求。

Provider Adapter 负责：

- model capability；
- message/tool mapping；
- prompt cache；
- streaming normalization；
- usage normalization；
- timeout/retry/fallback 信号；
- receipt/response identity。

Provider 特有优化不得改变 Tool 可见性、用户数据权威或历史顺序。

### 12.9 Integration 边界

每个 Integration 必须独立拥有：

- connection identity；
- credential broker；
- Provider scope；
- cursor/version；
- Source Snapshot；
- Tool/Operation adapter；
- retry 和 rate limit；
- receipt/read-back；
- revoke 与删除。

Integration 不直接写 Career Domain。它通过 Observation Intake 或 Application Operation 提交候选变化。

### 12.10 RAG 边界

RAG 负责来源解析、chunk、index、retrieval、rerank、grounding 和 citation。它不拥有 CareerProfile、JobOpportunity、Memory 或正式历史。

检索结果是 Evidence Candidate，不是事实。检索 scope 必须由当前用户、对象、Conversation/Interview 和资产生命周期决定。

### 12.11 前后端契约

- OpenAPI/JSON Schema 或等价 IDL 是 HTTP 与结构化协议的来源；
- Event/Interaction/Client Action 具有独立 schema version；
- 前端类型应生成或由契约测试校验，避免手工复制后端 union；
- 前端 Query cache key 应按领域 Projection 统一；
- 页面不直接拼接内部数据库结构；
- 新 UI 以目标体验和协议重建，不受当前草稿页面约束。

### 12.12 架构约束测试

目标架构测试至少强制：

- import graph 无环；
- Domain 不向外依赖；
- API 与 Tool 不绕过 Application Operation；
- Tool Adapter 不包含直接 ORM write；
- 每个正式 Operation 有 contract test；
- 每个 Agent 可用写能力有 Policy 与 verification；
- Event schema 有版本；
- 所有 ORM 时间使用 UTC 类型；
- Postgres structured value 使用 JSONB 或明确类型；
- Source/Evidence 不被复制成万能 registry。

### 12.13 Observability 实现目标

目标 Observability 应为 provider-neutral、OpenTelemetry-compatible 的 trace/span/metric 体系，至少覆盖：

- ingress/admission span；
- context compilation span；
- model dispatch span；
- tool/operation execution span；
- blocked-on-user span；
- external verification span；
- domain commit span；
- trigger/automation span；
- memory producer/recall span。

商业 tracing 产品可以作为 exporter，但不能成为唯一可用实现或唯一执行事实源。

### 12.14 Cloud 与 Community

Cloud 和 Community 共享同一产品语义、Domain Kernel、Operation Contract 与 Harness 不变量。Edition 只决定部署、Provider、连接与用户可配置范围，不得形成两套业务产品。

Cloud 可以限制远程 MCP、模型端点和基础设施配置；Community 可以允许 operator 管理的本地模型和 stdio MCP。任何放宽都必须由部署 owner 明确配置并保持用户数据隔离。

### 12.15 重建方式

工程重建采用：

```text
新边界
+
完整垂直切片
+
逐所有权迁移
```

不得：

- 先创建所有空包；
- 让新旧路径长期双写同一事实；
- 为维持当前草稿 UI 而污染新 Domain Contract；
- 一次性推倒全部正确 runtime 资产；
- 在主蓝图中维护迁移状态。

每个切片必须先定义体验流程、Domain State、Operation、Policy、Event、Failure、Evaluation 和回滚边界，再实施代码。

---

## 13. 产品验收不变量

以下不变量用于审查产品、架构、代码和评测。任一核心不变量被破坏时，功能不得宣布完成。

### 13.1 产品与用户

1. 产品围绕用户，不围绕单个岗位。
2. 用户可以同时管理多个求职流程。
3. 用户拥有最终事实权。
4. 用户可以直接使用 UI 完成核心业务，不依赖模型可用性。
5. 用户可以通过自然语言完成所有适合语义表达且已授权的 Career Domain 行为。
6. 用户可以暂停、撤销和删除长期自动化与 Memory。

### 13.2 Domain 与事实

7. Agent 推断不得直接成为 Canonical State。
8. 外部 Observation 不得自动成为模型指令。
9. 未来求职阶段不得预先虚构。
10. Process Event 历史不得原地改写。
11. JobOpportunity 当前状态必须可由有效事实重建或核对。
12. Next Action 只表示已成立的真实行动，不是 Agent 建议。
13. 用户接受建议前，不得创建 planned Next Action。
14. 点击 Next Action 必须进入对应业务操作上下文。
15. AbilitySignal 必须是一次或局部、带 Evidence、范围和不确定性的能力观察，不是 CareerProfile 正式事实。
16. Memory Runtime 必须聚合同一能力的多个有效 AbilitySignal，处理冲突和语义更新，并形成 AbilityUnderstanding。
17. AbilityUnderstanding 必须是专门的 Learned Memory，不得覆盖 CareerProfile 或其他 Canonical State。
18. 来源删除或 AbilitySignal 失效后，必须重新计算受影响的 AbilityUnderstanding。
19. 能力分数、雷达图和趋势值只能是可重新计算的 View Projection，不得成为后端永久能力事实。
20. 用户必须能够查看能力理解的来源，并提出异议、修正、失效和删除。
21. Offer 条款与接受/拒绝决定由不同权威记录拥有。

### 13.3 Artifact 与来源

22. 普通 Agent 输出不是 Artifact。
23. 只有用户明确要求文件格式时才创建 Artifact。
24. Artifact Version 不可原地改写。
25. “相关”不得冒充“已提交”。
26. 已提交记录必须冻结精确 Artifact Version。
27. Source Asset 删除不得静默改写正式历史。
28. Evidence 必须指向真实 owner identity 和可用 version。

### 13.4 Operations

29. UI、Agent 和 Automation 共享同一套 Atomic Application Operations。
30. 不得为 UI、Agent 和 Automation 分别维护业务规则。
31. Agent Tool 不得直接绕过 Domain 写任意表或字段。
32. 一个原子 Operation 不得隐藏新的用户意图或授权边界。
33. 高层 Skill/Plan 必须以可观察原子操作执行副作用。
34. 每个写 Operation 必须具有幂等、版本和 typed failure 语义。
35. unknown 外部副作用解决前，冲突资源必须被 fence。

### 13.5 Harness

36. 每个被接纳输入拥有 durable Turn identity。
37. PendingSubmission 在 claim 前不是 UserMessage 或 Turn。
38. 普通输入不得自动解除 waiting Interaction。
39. 断开流或关闭页面不等于取消。
40. 中断后不得启动未登记的新模型或 Tool 调用。
41. Tool Use 与 Tool Result 必须按 call identity 配对。
42. AgentTask 不得承载 Next Action、queue 或 Tool audit。
43. PersistentTask 定义、Trigger 与实际 Turn 必须分开。
44. 运行恢复不得重复已成功副作用。
45. Context compaction 不得替换当前用户原始目标。

### 13.6 Trust 与 Memory

46. 外部操作未经过 receipt 或 read-back 验证，不得宣称完成。
47. 结果未知必须明确表示为 unknown。
48. Approval 必须绑定具体调用或明确可撤销范围。
49. “待我确认”只聚合外部操作批准、事实确认和档案更新确认。
50. Memory Runtime 属于 Harness，Memory Record 是一等数据资产。
51. Learned Memory 不得覆盖 Canonical State。
52. Memory 必须支持来源、置信度、范围、冲突、修订、失效和删除。
53. 用户删除的 Memory 不得自动复活。
54. 自动 Memory producer 未通过评测门禁时必须默认关闭。

### 13.7 Experience 与评测

55. 前端不得通过解析自然语言推断关键执行状态。
56. Client Action 不得模拟不稳定 DOM 点击或冒充业务完成。
57. Today 是 Projection，不是新数据 owner，且只包含 9.8 冻结的四类内容；Recommendation 不得成为第五类模块。
58. `今天`、`求职`、`面试`、`资料`、`活动中心`、`设置`的产品层级与职责已冻结；物理路由、组件结构、视觉稿和具体呈现方式不得成为 Domain 不变量。
59. Copilot 必须保持横跨整个产品的自然语言交互与执行层，不得退化为普通一级导航页面。
60. 每个核心闭环必须有端到端场景评测。
61. LLM-as-judge 不得单独裁定权限、幂等、Evidence 和外部真实性。
62. Trace、成本和恢复数据必须能按 Turn/Task/Operation 关联。

---

## 14. 明确非目标

Interview Copilot 不是：

- 招聘方使用的 ATS；
- 企业销售式 CRM；
- 通用项目管理或任务管理软件；
- 岗位数据后台；
- 简历文件管理器；
- 固定流程漏斗；
- 一组 CRUD 页面；
- 在传统 SaaS 旁附加聊天框；
- 只有回答能力、没有真实操作能力的聊天机器人；
- 可以绕过用户授权全自动投递、发信或接受 Offer 的系统；
- 用 Learned Memory 替代正式事实的个人画像系统；
- 把所有数据塞进 System Prompt 的长期上下文系统；
- 把所有来源复制进万能 Source Registry 的数据平台；
- 为每个历史 API 机械生成一个 Tool 的工具集合；
- 用不可观察宏 Tool 隐藏多个副作用的自动化平台；
- 依赖当前页面、路由和视觉草稿的固定产品结构；
- 通用多 Agent/swarm 平台；
- 通用插件市场、编码沙箱、Worktree、LSP 或终端 Agent；
- 依赖实验性外部协议任务状态作为自身 Turn/PersistentTask 权威的系统。

本蓝图也不负责：

- 记录迁移进度；
- 决定最终视觉风格；
- 一次性冻结所有 Atomic Operation 字段；
- 自行关闭尚未确认的开放产品问题；
- 指示一次全仓库推倒式重写。

---

## 15. 开放问题

以下问题尚未由冻结决定完整裁定。实现者不得自行把答案写成永久产品语义。

### 15.1 Product 与 Experience

1. Copilot 采用全局常驻、上下文浮层、对象工作区还是组合呈现？该实现选择不得改变其横跨整个产品的自然语言交互与执行角色。
2. Recommendation/Proposal 的持久化范围、生命周期和用户反馈模型是什么？
3. “待我确认”之外的 clarification、connection 和 client readiness 应如何统一呈现？
4. 用户需要看到多深的 Operation/Tool/trace 细节，默认与高级视图如何分层？

### 15.2 Domain 与 Operations

5. 初始 Atomic Application Operation Catalog 的完整目录和 schema 是什么？
6. Communication 是否只保留 connector-owned Source/Observation，还是需要用户级统一通信索引 Projection？
7. Calendar Event、Interview Schedule 与 Next Action fixed time 的精确所有权如何划分？
8. Job discovery result 在被用户跟踪前的持久化、去重和过期策略是什么？
9. AbilityUnderstanding 的聚合、冲突、衰减与重算算法，以及 AbilityProfile View Projection 的 rubric/version 契约如何定义？
10. Artifact 的允许格式、异步生成状态、编辑和导出契约是什么？
### 15.3 Harness

12. Agent 内部何时选择 direct answer、确定性 Workflow 或完整 Agent Loop？
13. AgentTask 的计划阶段是否保持扁平，哪些复杂场景需要更丰富依赖表达？
14. Context Package 的正式 schema、slot 优先级和数据权威标记如何定义？
15. Operation/Tool 渐进披露按领域、任务还是检索式 Catalog 实现？
16. Provider fallback 是否允许跨模型能力等级，如何防止行为和权限语义漂移？
17. Verification Result 是否需要独立 durable owner，还是按具体 ToolCall/Operation/Domain owner 保存？
18. 主动性预算、quiet hours、通知频率和成本上限的默认产品值是什么？
19. 多 Agent 的真实需求门槛与评测条件是什么？

### 15.4 Memory、Trust 与数据治理

20. Learned Memory 的默认保留期、置信度衰减和冲突合并策略是什么？
21. 哪些信息被定义为禁止自动形成 Memory 的敏感类别？
22. Memory 提升为 Canonical Preference 的确认体验和 Operation 是什么？
23. External Write 的长期预授权粒度和可逆性目录是什么？
24. 用户数据导出、删除、最小 tombstone 和法定保留之间的完整政策是什么？
25. Cloud 与 Community 的 trace、模型 Provider 和数据驻留默认差异是什么？

### 15.5 评测与切片

27. 哪些生产指标是主动 Career Loop 的硬发布门禁？
28. Memory producer 的离线和在线门禁阈值是什么？
29. 新蓝图的场景集如何替换现有依赖旧蓝图路径的 evaluation manifest？

---

## 附录 A：已纳入蓝图的产品与架构决定

本蓝图已经吸收并保持以下批准决定：

1. 产品使命为“围绕用户持续运行的 AI 求职工作台”；
2. 总体架构为 Career Domain Kernel + Agent Harness + Adaptive Experience；
3. Career Data Assets 不是第四个内核；
4. Context Compiler 按任务读取资产，用户资产不永久堆入 System Prompt；
5. 三种使用方式为直接 UI、自然语言 Agent、主动 Career Loop；
6. 三种入口共享 Atomic Application Operations、Domain State、规则、权限、幂等和验证；
7. UI、Agent、Automation 共享相同语义和业务粒度；
8. 高层任务属于 Skill/Plan/Task Template/Recipe，不属于隐藏副作用宏 Tool；
9. Harness 围绕 Perceive → Contextualize → Deliberate → Plan → Approve → Act → Verify → Learn → Communicate → Schedule 组织；
10. Career Data Assets 的六类分类；
11. Memory Runtime 属于 Harness，Memory Record 属于一等数据资产；
12. Learned Memory 不得覆盖 Canonical State；
13. 用户中心、最终事实权、动态求职阶段、Next Action、待我确认、Artifact 和外部验证等十一条冻结原则；
14. 当前代码只作为工程事实，旧文档不得覆盖冻结决定；
15. 主蓝图按 0–15 顶层关系自顶向下组织；
16. 蓝图只有在获得产品批准后才能标记为“唯一现行蓝图”；
17. 产品级信息架构冻结为四个一级入口、两个辅助入口，以及横跨产品的 Copilot 层；
18. Today 只投影下一步、待我确认、求职动态和 Copilot 动态四类内容；
19. Ability 采用方案 B：AbilitySignal 是局部观察，Memory Runtime 聚合形成 AbilityUnderstanding，AbilityProfile 仅为可重算展示投影。
20. 首个正式垂直切片冻结为 `Interview Invitation Intake, Confirmation, and Preparation Handoff Lifecycle`（面试邀请接收、确认与准备交接生命周期），第一版使用 UI、自然语言和 fixture/manual Observation 三种入口，不以真实 Gmail 或 Calendar 为前置条件；
21. `confirm_interview_invitation` 的原子事务包含邀请确认、JobOpportunity 创建或关联、Interview 创建或更新、Process Event、Evidence 与 Domain Events；不包含 Next Action、准备计划、邮件、Calendar、Profile 或长期自动化。

## 附录 B：初始实施评估引用

主蓝图初稿形成时的代码取证、Implementation Gap、旧文档待查点和当前实现冲突，已完整移至非规范性实施文档：

[`docs/implementation/career-agent-os-initial-assessment.md`](../implementation/career-agent-os-initial-assessment.md)

该实施评估只说明当前实现事实与目标差距，不定义产品语义，不覆盖 Blueprint、已登记架构决策或正式 Contract，也不在主蓝图中维护迁移进度。
