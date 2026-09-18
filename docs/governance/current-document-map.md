# Current Document Map

> 状态：Implemented Evidence  
> 日期：2026-08-27  
> 作用：把现有文档映射到新体系；不评价产品决定是否正确

## 1. 分类规则

| 处理方式 | 含义 |
|---|---|
| Retain | 职责已经单一，可继续保留在原位置 |
| Reuse as Input | 内容可用于回答新层级问题，但必须重新审阅 |
| Split and Relocate | 当前跨越多个层级，未来按批准内容拆分归位 |
| Current Evidence | 只描述当前实现或评测事实 |
| Historical / Superseded | 保留历史，不参与现行产品裁决 |

## 2. 现有现行文档

| 当前文档 | 新层级 | 过渡期处理 | 说明 |
|---|---|---|---|
| `docs/architecture/career-agent-os-blueprint.md` | L1–L5 混合 | Reuse as Input / future split | 当前批准基线；使命、原则、IA、Domain、Harness、Data、Trust、工程边界分别进入后续层级 |
| `docs/architecture/README.md` | L0 | Merge into root governance | 过渡期保留；全仓文档入口改由 `docs/README.md` 承担 |
| `docs/architecture/contracts/application-operation-contract.md` | L4 | Retain | 已批准 Contract；待 Domain 与 MVP 复核后确认适用范围 |
| `docs/architecture/contracts/context-package-contract.md` | L4 | Retain | 已批准 Contract；未来由 Agent Behavior 需求向下约束 |
| `docs/architecture/contracts/interaction-event-contract.md` | L4 | Retain | 已批准 Contract；未来拆分 Interaction 与 Event 的必要性再评估 |
| `docs/architecture/contracts/verification-contract.md` | L4 | Retain | 已批准 Contract；属于 Trust / Operation 的下位契约 |
| `docs/architecture/vertical-slices/vs-01-*.md` | L6 | Retain as current slice | 当前实施切片；不作为 MVP 范围来源 |
| `docs/implementation/career-agent-os-capability-map.md` | L6 | Reuse as Input | 等 MVP 批准后重排优先级和切片归属 |
| `docs/implementation/career-agent-os-ledger.md` | L6 | Retain | 只保存实施状态；产品复核期不扩大范围 |
| `docs/implementation/career-agent-os-initial-assessment.md` | L7 | Current Evidence | 代码资产和 Gap 取证，不定义目标产品 |
| `docs/architecture/codebase.md` | L7 / L5 evidence | Current Evidence | 当前代码放置、运行流和约束；未来技术架构只引用所需事实 |
| `docs/architecture/editions.md` | L5 | Retain with review | 部署版本政策；待 MVP 和商业边界明确后复核 |
| `docs/architecture/interview-audio-to-qa-pipeline.md` | L3–L5 混合 | Reuse as Input / future split | Evidence 不变量进入 Domain/Contract，流水线实现进入 Technical Architecture |
| `docs/architecture/mock-interview.md` | L2–L5 混合 | Reuse as Input | 当前实现说明；不能替代未来模拟面试用户旅程和产品规格 |
| `docs/deployment/cloud.md` | L5 | Retain | 运维文档，服从后续批准的部署架构 |
| `docs/deployment/community.md` | L5 | Retain | 运维文档，服从后续批准的部署架构 |
| `docs/getting-started.md` | L5 / user docs | Retain | 当前使用说明，不是产品需求源 |
| `docs/zh/getting-started.md` | L5 / user docs | Retain | 中文使用说明；与英文入口保持同步 |
| `docs/zh/README.md` | Documentation portal | Update later | 待新体系稳定后同步新的文档入口 |

## 3. Historical / Superseded

| 当前文档 | 分类 | 可复用内容 |
|---|---|---|
| `docs/architecture/full-cycle-career-copilot.md` | Superseded | 历史产品语义、设计理由、已实现复杂不变量的线索 |
| `docs/architecture/full-cycle-implementation-ledger.md` | Historical | 旧实现映射与阶段性证据 |
| `docs/architecture/stages/*` | Historical implementation reference | Turn、附件、Profile、Artifact、Integration、Memory 的物理合同线索 |
| `docs/reports/full-product-and-systems-audit-2026-08-04.md` | Dated evidence | 对应日期的成熟度、运营和发布缺口 |
| `docs/reports/rag-evaluation-2026-08-08.md` | Dated evidence | RAG 数据集、门禁和未达标指标 |

## 4. 内容迁移路由

| Blueprint 当前内容 | 未来 owner |
|---|---|
| 产品使命、用户中心、事实权、核心价值 | Product Definition |
| 产品目标、完整求职闭环、范围与非目标 | MVP / Product Strategy |
| 三种使用方式、一级入口、Today 投影 | Experience |
| Career Domain Kernel、对象和业务规则 | Domain Model |
| Atomic Application Operations | Domain Operation Catalog + Contract |
| Agent Harness 循环及子系统 | Agent Behavior + Harness Architecture |
| Career Data Assets、Memory 位置 | Domain / Agent Behavior / Data Architecture |
| Trust、Permission、真实性 | Product Principle + Domain + Agent Behavior + Contract |
| Interaction and Event Model | Experience + Formal Contracts |
| Evaluation | Product Success Metrics + Delivery Evaluation |
| 目标工程架构 | Technical Architecture |
| 验收不变量 | 由各 owner 文档保存，跨层不变量由根索引追踪 |

## 5. 当前禁止动作

在相应新层级批准前：

- 不批量移动现有文件；
- 不把 Blueprint 立即标为 Superseded；
- 不复制 Blueprint 正文形成第二套现行规范；
- 不因新目录出现就创建空白 Experience、Domain 或 Architecture 文档；
- 不删除旧代码或旧文档；
- 不启动基于未批准 MVP 的新功能切片。
