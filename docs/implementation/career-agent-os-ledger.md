# Career Agent OS Implementation Ledger

> 状态：现行实施账本；Gate A 已批准，VS-01 实施中  
> 日期：2026-08-26  
> 规范来源：[`Career Agent OS Blueprint`](../architecture/career-agent-os-blueprint.md)  
> 当前切片：[`VS-01 面试邀请接收、确认与准备交接生命周期`](../architecture/vertical-slices/vs-01-interview-invitation-intake-confirmation-handoff.md)

## 1. 账本职责

本文是非产品规范的实施状态源。它把已批准 Blueprint、Contracts 与 Vertical Slice Spec 映射到当前代码资产、目标 owner、依赖、迁移、测试、切换和删除条件。

本文不得：

- 改变产品或 Contract 语义；
- 因当前代码困难而缩小已批准边界；
- 把“文件存在”写成“能力完成”；
- 把测试通过写成产品发布完成；
- 为后续九个切片预建虚假进度；
- 与旧 `full-cycle-implementation-ledger.md` 竞争同一状态语义。

旧账本是 Historical 快照；从 VS-01 起，Career Agent OS 新实施只在本文登记。

## 2. 状态词汇

| 状态 | 含义 |
|---|---|
| `decision_required` | 真实产品决定未批准，当前工作会改变长期语义 |
| `draft` | 规范或设计已起草，尚未批准实施 |
| `planned` | 规范已明确，但尚未写业务代码 |
| `in_progress` | 目标 owner 已开始实现，尚未满足门禁 |
| `implemented_unverified` | 代码存在，但 Contract/evaluation 门禁未通过 |
| `gated` | 确定性测试通过，但尚未满足切片发布/外部条件 |
| `done` | owner、迁移、验收、切换和删除条件全部满足 |
| `blocked` | 已有明确外部阻塞；必须记录 blocker 和解除条件 |

任何行从 `implemented_unverified` 进入 `done` 前，必须能引用对应 Contract tests、scenario gate、迁移/一致性结果和旧路径退出证据。

## 3. 当前切片状态

| 字段 | 当前值 |
|---|---|
| Slice | VS-01 — Interview Invitation Intake, Confirmation, and Preparation Handoff Lifecycle |
| Product decisions | PDR-01、PDR-02 已批准并归位；PDR-03 不阻塞核心路径 |
| Current phase | Gate D / Gate E 并行实施；Gate F 场景门禁保持红灯 |
| Business code | Gate B/C 主干已实现；Harness 与三入口适配仍有未完成项 |
| Database/migration | 已创建 migration `0043`；静态门禁通过，真实 PostgreSQL up/down 尚未执行 |
| Tests/evaluation | 新 manifest 已登记 VS01-S01…S15；13 项 covered，S09/S14 partial，故 release gate 为 false |
| Entry gate for coding | **已于 2026-08-26 通过 Gate A** |
| Core exit gate | VS-01 Definition of Done 与 VS01-S01 至 S15 全部满足 |

### 3.1 本轮实施证据

| 能力 | 当前实现证据 | 当前结论 |
|---|---|---|
| Shared Operations 与 Domain owner | provider-neutral Source/Observation/Candidate/Evidence、ApplicationOperation、OperationVerification、CareerDomainEvent、Interview schedule 字段与 `0043` migration | 主干已实现；尚未通过真实 PostgreSQL migration gate |
| PDR-02 原子确认 | `confirm_interview_invitation@1` 统一 create/link Opportunity、create/update Interview、ProcessEvent、Evidence、Domain Events，并自动断言零 NextAction/外部动作 | deterministic tests 通过；commit ambiguity/reconciliation 仍未闭合 |
| Harness path | `fact_confirmation@1`、same-call resume、typed Context Package、Agent thin tools、通用 Client Action | 正常等待/恢复通过；VS01 专用 worker-kill/verifying recovery 仍不完整 |
| 三种入口 | 手动 UI、当前用户消息 Agent Tool、fixture Observation 均汇入 Shared Operations；Observation 强制停在 fact confirmation | 基本入口贯通；旧 Gmail invitation apply 路径尚未 cut over |
| Adaptive Experience | Today 读取真实 NextAction/Interaction/Event；Interview 展示 verified handoff；Activity Center 为可重建投影；Copilot prompt 不再丢失 | 目标路径可用；Career 双页面和部分旧路径尚未退出 |
| Evaluation | `career_agent_os_scenarios.json` 与独立 runner；46 项后端相关门禁通过、4 项 PostgreSQL-only skipped；7 个前端文件 21 项通过；TypeScript 与本切片定向 ESLint 通过 | manifest 有意保持红灯：S09、S14 尚为 partial；全量前端 lint 仍有 6 个切片外既有 warning |

全量回归补充：前端 `57` 个测试文件、`180` 项测试全部通过。后端全量首次运行得到 `1479 passed / 5 failed / 5 skipped`；其中本切片引入的两个失败（旧 Opportunity fixture 缺少 CAS version、Tool Registry 期望集合未登记三个新 Tool）已修复并通过定向回归。剩余三个失败位于未由 VS-01 修改的旧 Web 搜索降级断言、superseded 场景 manifest 的失效前端路径和旧 Prompt 模板占位符，另行处理，不改变本切片 release gate 结论。

## 4. Gate A 基线资产

本章保留 Gate A 批准时的代码取证，用于迁移比较；其中“差距”描述不作为当前实时状态，实时状态以第 3、6 章为准。

### 4.1 Domain 与数据

| 当前资产 | 可保护价值 | 与目标的差距 |
|---|---|---|
| `backend/app/models/job_opportunity.py` | Opportunity phase/outcome、append-only ProcessEvent、sequence、provenance、idempotency、owner/version | 邀请确认尚无一个共享原子入口；NextAction 旧 suggested 语义不能进入 VS-01 |
| `backend/app/services/career_process_service.py` | Opportunity、ProcessEvent、merge、NextAction 的成熟规则与测试 | 体量过大；邀请 create/link + Interview + ProcessEvent 事务尚未成为独立 Operation |
| `backend/app/models/interview_record.py` | Interview 与 Opportunity 关联、真实/模拟面试证据生命周期 | 当前核心偏记录/分析，未明确承担 invitation schedule 的目标字段与版本语义 |
| `backend/app/services/interview/interview_record_service.py` | Interview owner/状态与现有测试 | 尚无 VS-01 create/update schedule seam |
| `backend/app/models/gmail_observation.py` | Observation、snapshot、review card、状态与来源 | Gmail-specific owner；目标需要 provider-neutral invitation candidate/interaction 边界 |
| `backend/app/services/gmail_observation_service.py` | Snapshot 不可变、去重、ambiguous review、approve/reject/retract | 高置信条件可 auto-apply；`interview_scheduled` 主要只追加 ProcessEvent，不创建/更新 Interview |
| `alembic/versions/0022_link_interviews_to_opportunities.py` | 现有 Interview/Opportunity 关联基础 | 不足以证明 schedule owner 已完成 |
| `alembic/versions/0030_add_gmail_observations_and_event_cards.py` | Observation 与 review 物理基础 | 当前 review card 不能直接充当长期通用 fact-confirmation Contract |

### 4.2 Harness、Interaction 与执行

| 当前资产 | 可保护价值 | 与目标的差距 |
|---|---|---|
| `backend/app/models/pending_submission.py`、`conversation_turn.py` | durable admission、Turn identity/status、heartbeat/dispatch generation、waiting reason | 需要映射 VS-01 typed states 与事件，不应重写耐久核心 |
| `backend/app/services/chat/turn_executor.py` | claim、interrupt、cancel、resume、orphan repair、worker recovery | 目标 owner 命名和边界不清；需证明 fact-confirmation same-Turn resume |
| `backend/app/models/agent_interaction.py` | 一个 Turn 一个 pending Interaction、version CAS、durable resolution | 当前 kind 约束缺少 `fact_confirmation` / `profile_update_confirmation` |
| `backend/app/services/chat/interaction_service.py` | resolution 与 Turn 恢复的事务基础 | 需要 typed request/resolution、schema version、decision identity 与新 kind |
| `backend/app/services/chat/client_action_service.py` | persisted-before-delivery、client affinity、takeover、typed result、重试 | 当前协议和命名硬编码 Mock Interview；缺少通用 `interview.preparation.open@1` |
| `backend/app/agent_runtime/tool_policy.py` | 纯函数 effect/allow/ask/deny 与执行时策略基础 | 需要在 Shared Operation 参数/resource identity 上复用，不能被 Tool-only policy 限制 |
| `backend/app/agent_runtime/harness_events.py` | 现有 SSE typed constructors | 事件类别、统一 envelope、Verification 和 projection invalidation 尚不完整 |
| `backend/app/conversation/agent_strategy.py` | 当前真实 Agent loop、tool execution、streaming 与恢复 | 包命名误导且文件庞大；VS-01 只建立薄 Adapter，不启动全 Harness 重分包 |
| `backend/app/services/chat/context_assembly_pipeline.py` | durable summary、cursor、sanitization、token budget | 尚无 Context Package 的 authority/source manifest 与 VS-01 不可压缩字段契约 |

### 4.3 Experience

| 当前资产 | 可保护价值 | 与目标的差距 |
|---|---|---|
| `frontend/src/pages/today/TodayPage.tsx` | 新产品 Today 四象限视觉骨架 | “待我确认”使用 seed/local filter；空用户仍可能看到虚构公司；非真实 projection |
| `frontend/src/pages/review/chat/InteractionCard.tsx` | 当前 typed Interaction resolve UI 与 version handling | 只在 ChatPanel；未成为 Today 与跨产品共享 Projection |
| `frontend/src/components/layout/ClientActionBridge.tsx` | 全局客户端桥、takeover、polling、结果回传 | 只支持 Mock Interview actions，需通用 typed handler |
| `frontend/src/pages/career/CareerPage.tsx` | 新求职入口外壳与部分真实 CRUD | action 为 toast，typed opportunity/interview handoff 缺失；与深层旧页面重复 |
| `frontend/src/pages/interviews/InterviewHubPage.tsx` | 面试入口与旧功能容器 | 核心区域无数据；prompt query handoff 无消费方 |
| Activity Center 当前别名页 | 已有 PersistentTask 页面可复用 | 尚无 Turn/Interaction/Operation/Verification 统一活动投影 |
| `frontend/src/api/chat.ts` 与 `useChatStream.ts` | reconnectable SSE、interaction/tool blocks、cancel/resume | wire schema 需要版本化并支持新统一事件；前端类型当前手工镜像 |

### 4.4 测试与评测

| 当前资产 | 可保护价值 | 与目标的差距 |
|---|---|---|
| `backend/tests/test_services/test_gmail_observation_service.py` | dedupe、immutable snapshot、ambiguous review、approve/reject、retraction、auto-apply 回归 | 需新增 provider-neutral candidate 与“第一版不 auto-apply”Contract tests |
| `backend/tests/test_services/test_career_process_service.py` | Opportunity/ProcessEvent/NextAction 领域回归 | 需新增跨 Opportunity/Interview/Event 原子事务与禁止副作用断言 |
| `backend/tests/test_services/interview/test_interview_record_service.py` | Interview owner/状态回归 | 需 schedule create/update/version/Evidence tests |
| `backend/tests/test_services/chat/test_interaction_service.py` | pending uniqueness、CAS、resolution 基础 | 需 fact-confirmation schema、same-Turn resume、reconnect tests |
| `backend/tests/test_services/chat/test_turn_executor.py` | durable Turn/worker recovery 基础 | 需 VS-01 waiting→resume→operation→verify 场景 |
| `backend/tests/test_services/chat/test_client_action_service.py` 与 API/frontend tests | affinity、takeover、retry、result | 需通用 preparation handoff 和 Domain-state independence |
| `backend/tests/test_agent_runtime/test_tool_policy.py` | policy taxonomy 与顺序 | 需 Operation resource/argument traits 和 unknown fail-closed |
| `evaluation/career_scenarios.json` | 现有 18 个跨阶段回归绑定 | 仍引用 superseded blueprint/stages；尚无新蓝图 VS01-S01…S15 manifest |

## 5. 文档与 Contract 工作项

| ID | Requirement | Deliverable | Gate | Status |
|---|---|---|---|---|
| DOC-01 | PDR-01/PDR-02 归位 | Blueprint 5.3/附录 A；Capability Map 决定表 | 用户批准决定与正文一致 | `done` |
| DOC-02 | Shared Operation 最小契约 | `application-operation-contract.md` | 产品/架构审阅；PDR-02 一致性 | `done` |
| DOC-03 | Interaction/Event/Client Action 最小契约 | `interaction-event-contract.md` | 事实确认、事件顺序、handoff 语义审阅 | `done` |
| DOC-04 | Verification 最小契约 | `verification-contract.md` | success/unknown/reconciliation 语义审阅 | `done` |
| DOC-05 | Context Package 最小契约 | `context-package-contract.md` | authority/source/compaction 语义审阅 | `done` |
| DOC-06 | 首个 Vertical Slice | VS-01 Spec | 范围、三入口、场景与 DoD 审阅 | `done` |
| DOC-07 | VS-01 实施账本 | 本文 | 当前资产、批次、exit conditions 审阅 | `done` |

## 6. VS-01 实施工作项

### 6.1 Schema、Owner 与 Domain

| ID | Target owner | Requirement / target change | Current assets | Dependencies | Acceptance gate | Migration / deletion condition | Status |
|---|---|---|---|---|---|---|---|
| VS01-SCH-01 | Shared Contract Schemas | 为 Operation/Event/Interaction/Verification/Client Action 建立可生成、版本化 schema | Pydantic schemas 与手工 TS types | DOC-02…05 approved | schema snapshots；Python/TS compatibility；unknown version tests | 手工重复类型退出或由生成一致性 gate 保护 | `implemented_unverified` |
| VS01-DAT-01 | Source/Candidate owner | provider-neutral Invitation Source/Observation/Candidate，字段 Evidence、version、dedupe、lifecycle | GmailObservation/Snapshot/ReviewCard | SCH-01 | immutable/dedupe/provenance/reject/supersede tests | Gmail adapter 只做 provider ingress；不再拥有邀请业务确认 | `implemented_unverified` |
| VS01-DAT-02 | Interview owner | Interview 能表达已确认 schedule、original time/timezone、Opportunity link 与 version | InterviewRecord + migration 0022 | Product Spec；SCH-01 | create/update/CAS/source tests | 不保留第二份可独立漂移的 schedule owner | `implemented_unverified` |
| VS01-OP-01 | Shared Operation runtime | Operation envelope、idempotency/fingerprint、actor/owner/policy、typed result | 分散 service/API/tool semantics | SCH-01 | generic Operation Contract tests | UI/API/Tool 不再各自实现幂等与领域写入 | `implemented_unverified` |
| VS01-OP-02 | Domain Kernel Operation | 实现 intake/register/confirm/reject/query/handoff Operations | career/gmail/interview services | DAT-01/02；OP-01 | PDR-02 原子性；forbidden effects；owner/CAS/idempotency | 旧 approval/apply 邀请写路径汇入或封闭 | `implemented_unverified` |
| VS01-DOM-01 | Domain Event/Outbox | 在 confirm 事务产生 Domain Events 与 projection invalidation identities | ProcessEvent/outbox patterns | OP-02；EVT-01 | transaction/outbox/replay/dedupe tests | 不允许 API/Tool 在事务外拼事件 | `implemented_unverified` |

### 6.2 Harness、Policy、Context 与 Verification

| ID | Target owner | Requirement / target change | Current assets | Dependencies | Acceptance gate | Migration / deletion condition | Status |
|---|---|---|---|---|---|---|---|
| VS01-INT-01 | Interaction Runtime | 新增 `fact_confirmation@1` typed request/resolution 与 version migration | AgentInteraction + interaction_service | SCH-01；DAT-01 | one pending/Turn；CAS；confirm/correct/reject；ordinary-input no-resolve | Gmail review 与 Chat Interaction 不再形成两套用户确认协议 | `implemented_unverified` |
| VS01-TURN-01 | Turn Runtime | resolution 记录 + same-Turn resume；decision 与业务执行分离 | turn_executor、PendingSubmission、ConversationTurn | INT-01；OP-02 | worker kill、disconnect、duplicate resolution、interrupt tests | 保留现有耐久核心，删除专用绕行恢复 | `in_progress` |
| VS01-POL-01 | Permission Runtime | 按 Operation effect/argument/resource/version 做 execution-time recheck | tool_policy | OP-01 | UI/Agent/Automation parity；hard deny；unknown fail-closed | Tool-only隐藏 policy traits 退出 | `in_progress` |
| VS01-EVT-01 | Event Runtime | 统一 Domain/Harness/Experience envelope、schema、cursor 和 replay | harness_events、SSE wire | SCH-01 | ordering、replay、version、reconnect tests | 前端不再靠字段猜事件；旧 event mapper 退出 | `in_progress` |
| VS01-CTX-01 | Context Compiler | VS-01 typed Package、authority/source manifest、不可压缩字段和最小 scope | context_assembly_pipeline、compactor、source acquisition | DAT-01；INT-01；OP-01 | injection、stale state、compact/reconnect、scope tests | 邀请 prompt 拼接路径汇入 Compiler | `implemented_unverified` |
| VS01-VER-01 | Verification Runtime | durable-reference VerificationResult；local read-back；unknown/reconciliation | idempotency/audit/outbox patterns | OP-02；DOM-01；EVT-01 | postconditions、ambiguity、retry、no false success tests | service return/文案不再独立宣称完成 | `in_progress` |
| VS01-AGT-01 | Agent Adapter | 薄 Tool Adapter + 首个 Skill/recipe，调用 Shared Operations | agent loop、turn tool catalog、career/gmail tools | OP-02；CTX-01；POL-01；VER-01 | correct operation selection；no macro side effects；truthful final answer | 旧 career tool 中邀请写逻辑删除或改为 adapter | `in_progress` |

### 6.3 Experience 与 Automation

| ID | Target owner | Requirement / target change | Current assets | Dependencies | Acceptance gate | Migration / deletion condition | Status |
|---|---|---|---|---|---|---|---|
| VS01-UI-01 | Today Projection | “待我确认”读取真实 Interaction；动态读取真实 events；删除 seed/fallback | TodayPage、InteractionCard | INT-01；EVT-01 | empty account、CAS/multi-client、four-category tests | `SEED_TASKS`、fake companies、local confirm 删除 | `implemented_unverified` |
| VS01-UI-02 | Career Projection | Opportunity timeline 读取 confirmed Interview/ProcessEvent，typed deep link | CareerPage + CareerProcessPage | OP-02；DOM-01 | same object/version；no duplicate business rule | 新浅层/旧深层双 board 收敛到一个 owner | `in_progress` |
| VS01-UI-03 | Interview Projection | 安排详情、Evidence、Opportunity 与 preparation entry | InterviewHubPage + existing interview pages | DAT-02；OP-02 | confirmed-only display；source/view tests | marketing shell 不再作为数据页；prompt query handoff 退出 | `in_progress` |
| VS01-UI-04 | Activity Projection | Turn/Interaction/Operation/Verification 状态摘要 | PersistentTasks/Activity alias | EVT-01；VER-01 | waiting/verifying/terminal/reconnect tests | 活动中心不复制任务状态 | `implemented_unverified` |
| VS01-UI-05 | Copilot Experience | 当前 object context、Interaction、verified result 与 typed recovery | ChatPanel/useChatStream | EVT-01；CTX-01；AGT-01 | truthful state copy；no query-string prompt loss | 页面私有 chat hooks 逐步变共享边界 | `in_progress` |
| VS01-CA-01 | Client Action Runtime | 通用 `interview.preparation.open@1`，持久化、affinity、takeover、ack | mock client action service/bridge | SCH-01；DAT-02；EVT-01 | idempotent delivery；ack/fail；Domain independence | Mock-specific protocol 变 adapter，通用 runtime 单 owner | `implemented_unverified` |
| VS01-AUTO-01 | Observation Adapter | fixture/manual ingress → candidate → fact confirmation；第一版 no auto-apply | Gmail observation sync/service/tool | DAT-01；INT-01；TURN-01 | dedupe、retraction、no canonical write before confirmation | Gmail-specific apply path 不再处理目标邀请语义 | `implemented_unverified` |

### 6.4 Evaluation、Migration 与 Cutover

| ID | Target owner | Requirement / target change | Dependencies | Acceptance gate | Exit condition | Status |
|---|---|---|---|---|---|---|
| VS01-EVAL-01 | Career OS Evaluation | 新 manifest 登记 VS01-S01…S15，绑定 deterministic tests 与 scenario runner | 所有实现工作项 | 所有场景通过；无旧蓝图语义替代 | 新场景成为 VS-01 发布门禁 | `in_progress` |
| VS01-MIG-01 | Data Migration | 新/扩展 schema、backfill、downgrade、旧记录隔离和一致性扫描 | DAT-01/02；OP-02 | Alembic up/down；fixture；owner/source consistency | 所有活动用户数据可由新 owner 读取或明确 quarantine | `in_progress` |
| VS01-CUT-01 | Entry Cutover | UI/Agent/Automation 三入口逐一切到 Shared Operations | UI/AGT/AUTO；EVAL | shadow/read compare；write owner 单一；feature gate | 无旧独立邀请写入流量 | `in_progress` |
| VS01-DEL-01 | Legacy Exit | 删除 seed、mock-only branching、重复邀请 apply/write 路径与死代码 | CUT-01 | import/use scan；full test/eval；rollback window | 旧 owner 不再可达，文档同步 | `in_progress` |
| VS01-REL-01 | Slice Release | 完成 Spec §17 Definition of Done | EVAL/MIG/CUT/DEL | deterministic + integration + experience + recovery gates | VS-01 标记 `done` | `planned` |

## 7. 执行顺序与并行边界

```text
Gate A — 文档批准
  DOC-02..07

Gate B — Schema/Owner seam
  SCH-01 + DAT-01 + DAT-02 + OP-01

Gate C — Domain trunk
  OP-02 + DOM-01 + VER-01

Gate D — Harness trunk
  INT-01 + TURN-01 + POL-01 + EVT-01 + CTX-01 + AGT-01

Gate E — Three entry adapters
  UI-01..05 + CA-01 + AUTO-01

Gate F — Evaluation/Migration/Cutover
  EVAL-01 + MIG-01 + CUT-01 + DEL-01 + REL-01
```

- DAT-01、DAT-02 和 schema 设计可以并行，但必须在 OP-02 前共同审阅。
- Domain 与 Event schema 可并行设计，但 Domain transaction/outbox 必须一次提交。
- Experience 可以基于 contract fixtures 提前开发，但不得建立临时业务 owner。
- Evaluation scenarios 应在实现前写成红灯门禁，在功能完成后转绿。
- 任何数据库迁移都只能在文档 Gate A 通过后开始。

## 8. Migration 与数据真值计划

实施前必须先用只读审计确认：

1. 当前 `interview_scheduled` ProcessEvents 数量、source kinds 和关联 Opportunity；
2. 其中有多少存在对应 InterviewRecord；
3. Gmail review cards/observations 的 pending/applied/retracted 分布；
4. 是否存在同一来源重复 ProcessEvent 或重复 Opportunity；
5. 当前 Interview schedule 可从哪些字段可靠恢复；
6. 哪些数据只能 quarantine，不能推断补全。

迁移原则：

- 不从未来流程或邮件模糊文本推断缺失事实；
- 可证明关联才 backfill；否则保持历史记录并标记需审阅；
- 旧 immutable ProcessEvent 不原地重写；
- backfill 有稳定 operation/source identity，可重复运行；
- upgrade/downgrade 和一致性扫描纳入测试；
- 删除旧列/表必须晚于入口 cutover 和观察窗口。

## 9. 风险登记

| Risk | 影响 | 控制 |
|---|---|---|
| 把现有 Gmail auto-apply 直接复用为主动 Loop | 未经确认写正式事实 | fixture 第一版强制 fact confirmation；policy/eval gate |
| 新旧 Career 页面双写 | 状态漂移 | Shared Operation 单 owner；旧页面只做 Adapter/只读 |
| Interaction 决定与 Operation 结果混淆 | UI 显示已确认但写入失败 | decision 与 execution 分离；Verification gate；Activity 状态 |
| Interview schedule owner 选错 | Calendar/NextAction/Interview 三处漂移 | 核心由 Interview 承载 confirmed schedule；PDR-03 只影响未来外部支线 |
| 扩大首切片为完整面试重写 | 周期失控、无法验证主干 | 严守 Spec 非目标与 PDR-02 禁止副作用 |
| 事件协议一次性大爆炸 | 前后端迁移风险 | 只实现 VS-01 必需 kinds；versioned envelope；adapter 过渡 |
| Context compaction 丢 pending 决定 | 恢复后错误执行 | Contract 不可压缩清单 + worker/reconnect tests |
| 只做 happy path demo | 无法成为架构主干 | S01…S15，尤其 conflict/unknown/recovery/owner gates |

## 10. 当前未决事项

| ID | 问题 | 是否阻塞核心 VS-01 | 处理 |
|---|---|---|---|
| PDR-03 | Calendar Event / Interview Schedule / fixed NextAction 长期所有权与 fake external branch | 否 | 核心不含外部支线；未来单独决定 |
| EXP-01 | Copilot 常驻/抽屉/工作区具体形态 | 否 | VS-01 只要求 typed object handoff 和状态一致 |

### 10.1 当前发布阻塞项（不是开放产品决定）

1. **VS01-S09**：已证明 durable Interaction 与进程边界后的 same-call 幂等恢复；仍需覆盖 VS-01 verifying 状态的 worker-kill/reconnect 恢复。
2. **VS01-S14**：表结构可表达 `unknown/reconciled`，但 commit ambiguity 到 reconciliation 的适配器/runtime 路径尚未闭合，不能宣称完成。
3. **PostgreSQL migration gate**：migration chain、ORM 对齐等静态检查通过；本环境未连接 PostgreSQL，4 个真实 up/down 测试被跳过。
4. **Cutover/legacy exit**：新三入口已经使用 Shared Operations，但 Gmail-specific invitation apply、Career 双页面和部分旧读取/写入路径尚未完成流量证明与退出。
5. **统一事件门禁**：Domain Event 与 Activity envelope 已建立；Harness/Experience 全量 ordering、cursor、reconnect 仍未完成 EVT-01。

## 11. 变更记录

| 日期 | 变更 |
|---|---|
| 2026-08-26 | 创建新 Career Agent OS 实施账本；登记 PDR-01/PDR-02 与 VS-01 文档冻结、当前资产、实施批次和门禁；未修改业务代码。 |
| 2026-08-26 | 用户批准 Gate A；四份 Contract 与 VS-01 Spec 升为 1.0.0，进入 Gate B 实施。 |
| 2026-08-26 | Gate B/C 主干落地：确定 InterviewRecord 为 schedule 物理 owner，OperationVerification 为独立耐久记录；新增 provider-neutral invitation owners、Shared Operations、Domain Events 与 migration 0043。 |
| 2026-08-26 | Gate D/E 首轮落地：fact confirmation、Context Package、Agent/UI/fixture adapters、通用 preparation Client Action、Today/Interview/Activity/Copilot handoff；删除 Today seed/fallback 与求职卡片虚构未来阶段。 |
| 2026-08-26 | 创建新蓝图 VS01-S01…S15 evaluation manifest；13 covered、S09/S14 partial，因此 Gate F 与 Slice Release 有意保持未通过。 |
