# 全流程求职 Copilot 实现符合性账本

> 记录基线：`docs/architecture/full-cycle-career-copilot.md`（2026-08-13）及 Stage 0～5 Spec。
> 本文用途：把已经冻结的产品语义映射到当前生产代码、迁移、API/Tool/UI 入口和可执行验证，使后续开发可以按真实 owner 继续，而不必重新推测方案。本文不是第二份产品定义；冲突时以权威蓝图负责该对象的主题章节和对应 Stage Spec 为准。

## 0. 记录与状态规则

本账本继续遵守蓝图 §0 的记录原则：

1. 记录已确认结论时同时保留约束、理由、例外、失败/恢复语义、用户入口和验收条件，不能只写结论。
2. 新决定只替换明确冲突的局部；术语变化不能删除仍有效的细节。
3. 每个概念只有一个完整定义和一个真实 owner；本账本只映射实现，不复制第二套状态机。
4. 能从真实记录计算的投影不重复持久化；只有独立不变量、生命周期、权限、失败或恢复语义才能新增对象。
5. 未冻结选择只留在 §18；源码当前采用的阈值、组件或 Provider 默认值不自动升级为产品事实。
6. 验证绑定与实际运行结果分开记录。测试文件存在或协议级 fake 通过，不等于真实生产 Provider、浏览器、Postgres、队列或备份恢复已经验证。

本文用两个互不替代的状态轴：

| 轴 | 值 | 含义 |
|---|---|---|
| 代码状态 | `code_complete` | 已冻结语义已有真实 owner、Application Service、运行入口、用户入口、迁移（需要时）和自动化验证绑定；不表示已部署 |
| 代码状态 | `implemented_unverified` | 实现与测试代码已经写入工作树，但本批尚未完成最终 Ruff/pytest/frontend typecheck；不能合并计入 `code_complete` 或宣称测试通过 |
| 代码状态 | `gated` | 代码已实现，但蓝图要求的 release gate 默认关闭，不能通过配置或文案伪装为已上线 |
| 产品状态 | `open` | 蓝图 §18 尚未冻结，实现不得替用户选择 |
| 部署状态 | `deployment_required` | 需要目标环境的凭据、真实基础设施、迁移、浏览器或 Provider smoke；本仓库测试不能代替 |

## 1. 全局所有权与禁止重复建设

| 已冻结决策 | 当前唯一实现落点 | 明确不存在/不得恢复 | 状态 |
|---|---|---|---|
| Cloud-first；服务端 Conversation、产品状态、文件、RAG、Agent Runtime 与 PersistentTask 为权威平面 | `backend/app/conversation/`、`backend/app/agent_runtime/`、`backend/app/services/`、`backend/app/models/`；客户端只经 API/SSE 与 typed Client Action 协作 | 通用本地 Agent、本地/云端双 Runtime、宿主解析器、客户端事实源 | `code_complete`；云环境部署为 `deployment_required` |
| 七个业务域只是产品范围，不是运行时 Tool Group | 领域读写由 CareerProfile、Opportunity/Event/Action、Artifact、Interview、Offer、PersistentTask 等 Service 承担；Agent 的任务形入口在 `career.py`、`career_domains.py` 及真实 Integration Tool | CareerState 万能表、业务意图路由层、七套 Registry/Executor/Policy、固定求职周期 | `code_complete` |
| 五类 Product Context Sources 各守 owner | Product Domain State；Artifact/FileAsset/Observation；Interaction Records；Long-term Agent Memory；Personalization & Policy State | 通用 Evidence/Source Registry、Source Ledger、Checkpoint 作为第六来源、RAG 索引取得事实所有权 | `code_complete` |
| 页面、Agent、同步器和后台触发共用 Application Service | API 与 Tool handler 均调用 `backend/app/services/`；确定性 Gmail/调度入口也进入同一领域命令 | 页面本地状态机、Agent 私有领域写者、Connector 直接把模糊内容写成事实 | `code_complete` |
| 单主 Agent；只在具体 Tool Call 层安全并行 | `agent_strategy.py`、`tool_call_executor.py`、`turn_tool_catalog.py` | 通用子 Agent、任务树、forked Skill、生成式 UI、任意 route/DOM/click/type/HTML/JS Tool | `code_complete` |

## 2. §1～§3：产品域、工作空间与 Context Sources

### 2.1 产品范围和真实交付

- 六类行为最终都落在真实结果上：普通回答留在 History；Artifact 写入返回真实 Artifact/version；内部写入返回 Application Service 结果；外部写入必须带 receipt/read-back；持续执行返回可查看/暂停/删除的 PersistentTask；缺能力、连接、来源或授权时返回 `waiting`、`blocked` 或真实失败。
- Shared Kernel 的完成裁定和 Tool pipeline 阻止“模型说完成”冒充执行完成。Offer 接受/拒绝、签署、确认入职和受限面试代答没有伪按钮、伪 Tool 或 Auto 绕过。
- 公开 Web/URL、岗位搜索、Gmail、文件、Artifact、历史、面试、Career Domain、PersistentTask、Mock handoff 均以 concrete Tool 或 Application Service 进入；没有真实 handler 的未来 Connector 不注册。

实现入口：`backend/app/services/chat/turn_executor.py`、`backend/app/agent_runtime/tool_call_executor.py`、`backend/app/agent_runtime/tools/`、`backend/app/services/artifact_service.py`、`career_process_service.py`、`offer_service.py`、`persistent_task_service.py`。

验证：场景 `stage0-tool-policy-and-recovery`、`stage2-career-owner-and-process`、`stage3-artifact-offer-and-interview`、`stage4-persistent-task`。
状态：`code_complete`；真实外部动作的 live receipt 验证为 `deployment_required`。

### 2.2 四个工作空间

`frontend/src/components/layout/SideNav.tsx` 把现有真实读模型组织为：

- Copilot：`GeneralChatPage`、`HistorySearchPage`、`PersistentTasksPage`；
- 求职进程：`CareerProcessPage`、`CareerInsightsPage`、岗位 Offer 详情；
- 求职资料：`CareerProfilePage`、`ArtifactsPage`、`LibraryPage`；
- 面试中心：Mock、Interview Review、能力趋势；
- 回答模型、协作偏好与插件市场在“设置与连接”；Gmail、Canva、Notion 的连接与撤销直接内联在各自插件卡片下，不再维护第二个“外部连接”页面。插件市场同时容纳真实 Adapter 与 Skills/MCP；未接入的 Calendar 等只显示 `coming_soon`，不注册 Tool、不伪装安装成功。

这只是导航/组合视图，不创建四个聚合根。`AppShell.tsx` 是全局 Client Action Bridge 的稳定消费点；页面路由、选中项、DOM 和未提交表单不会隐式进入 Prompt。`copilotObjectReference.ts` 只在用户可见的“交给 Copilot”动作中提交 closed kind + identity，服务端由 `product_object_reference.py` 在 claim 和执行前重新读 owner。

本批新增的 `CopilotStatusSummary` 仍只是 Copilot 工作空间的三-owner只读投影：它分别调用 `getCareerProfile`、`listJobOpportunities`、`listNextActions`，从 `CareerProfile`、`JobOpportunity`、`NextAction` 的现行 API 组合档案摘要、活跃岗位和行动提示。组件不保存聚合结果、不新增 `CareerState`/Dashboard owner，也没有写命令；任一源变化后以原 owner 的下一次读取为准。

验证：`cross-stage-exact-history-and-workspaces`、`stage0-typed-product-object-anchor`、`stage3-mock-client-action-handoff`。
状态：工作空间、typed handoff 与 `CopilotStatusSummary` 均为 `code_complete`。最终页面组合、视觉密度和交互文案仍为 §18.1 `open`。

### 2.3 Context 来源和读取过程

| 读取语义 | 实现 | 权威边界 |
|---|---|---|
| Fact & Source Retrieval | `shared_source_acquisition.py`、`source_requests.py`、`attachment_sources.py`、Artifact/Career/Observation Service | closed typed History/Observation/Artifact/Career Domain 请求直接路由既有 owner；URL 使用与 Agent 相同的 SSRF-safe `read_url`，保留 URL、观察时间和 SHA-256 版本 |
| History Search | `interaction_history_service.py`、`api/history.py`、`search_interaction_history`、`read_interaction_history` | 精确读取 Interaction Records 和脱敏 Tool 轨迹；旧记录不声称当前事实 |
| Memory Recall | `agent_memory_service.py` → `conversation/engine.py` | 只选相关、active、同用户、低权威 canonical Memory；允许为空 |
| Attachment/Debrief Source | `rag/application/attachment_sources.py` | ConversationAttachmentRef 与 InterviewSourceRef 在候选检索前做 owner/scope/version/status 校验 |
| Provider 投影 | `conversation/provider_context.py` | stable system、chronological messages、当前 typed dynamic data 分区；当前 accepted input 始终是最后任务锚点 |

`HistorySourceRequest`、`ObservationSourceRequest`、`ArtifactSourceRequest`、`CareerDomainSourceRequest` 只是当前 Chat Turn 的有界读取协议，不是持久 CareerState 或 Source Registry。Debrief Chat 可用 `query_planner.py` 规划有限补充读取；Agent 直接迭代 concrete Tool，不经过另一个 Planner。显式 URL/来源读取失败在生成前形成 typed block/failure，不静默遗漏。

本批又收紧 Shared Source admission：用户已随 admitted Turn 明确提交并通过 owner/scope preflight 的 typed source refs 是不可删除的输入集合，Planner 只能追加有界补充读取，不能省略、替换或重写这些 refs。显式 URL 也不再在超过上限时静默截取；URL 数量 overflow 直接在模型生成前形成 typed blocked/failure，使用户知道哪些来源尚未读取。

验证：`stage0-shared-source-acquisition`、`stage0-agent-task-and-context`、`stage0-native-provider-cache-and-execution-mode-cas`、`cross-stage-exact-history-and-workspaces`。
状态：Context-source闭环、admitted-ref 不可删除与 URL overflow 均为 `code_complete`。

## 3. §4：CareerProfile、AbilitySignal 与 Artifact

### 3.1 CareerProfile 是唯一“个人详情/求职档案”owner

- 模型：`CareerProfile` + 稳定 identity 的 `CareerProfileDirection`；事实和方向仍保持不同校验/生命周期，但没有 CandidateProfile/TargetDirection 第二 owner。
- 候选：`CareerProfileDraftChange` + `CareerProfileCandidateItem`；简历/文档/模型提取只产生 pending candidate，逐项 CAS 接受/拒绝，冲突保留当前值、候选值和来源。
- Service/API：`career_profile_service.py`；`api/career_profile.py` 的 facts、directions、drafts/candidates 命令。
- Agent/UI：`read_career_context`、`confirm_career_profile_change`、`prepare_resume_profile_candidates`、`resolve_resume_profile_candidates`；`CareerProfilePage.tsx` 以一个连续在线简历页面投影相同 owner，左侧目录、中间事实/方向正文、右侧完整度均不形成第二存储；学历、职级、办公方式、币种、技能类别等封闭值使用选项，只有开放事实使用文本输入。
- 多方向与岗位关系：`JobOpportunityDirectionLink`（revision 0028）；一次临时搜索不写 Profile，当前 Turn 明确输入优先。

### 3.2 AbilitySignal 是独立推断型产品状态

- 模型：`AbilitySignal` + `AbilitySignalSourceRef`，保存 topic/type、范围、时间、不确定性/置信度、rubric/producer identity 和真实 source identity。
- Service/API：`ability_signal_service.py`；list/read/recompute/dispute/invalidate API。
- Producer：Interview/Mock/复盘通过同一 Service 重算 source-linked signal；不会写回 CareerProfile、Artifact、Interview QA 或 legacy Memory。
- 用户自述只能保留为标识清楚的 source/candidate；删除全部 live source 时信号降低、重算或失效。

### 3.3 Artifact 与简历

- `Artifact`/`ArtifactVersion` 是材料和 durable delivery 的唯一内容 owner；普通回答不会自动创建 Artifact。
- `ArtifactJobRelation` 表达 `related`；`ArtifactSubmissionSnapshot` 冻结 exact ArtifactVersion，后续 v2 不改历史 v1。
- `ArtifactResumeState` 只保存默认选择和解析 sidecar，不成为第二正文 owner。`/resumes` URL 是现有客户端的 transport 入口，所有 production 写入均委托 `resume_artifact_service.py` 写 Artifact；退休 `resumes/resume_sections` 不再是运行时 source/writer。
- 显式 ConversationAttachmentRef → Artifact 晋升复用 exact `file_asset_id + file_asset_version`，不复制解析正文；resume 晋升只创建可确认 Profile candidate。
- API/UI：`api/artifacts.py`、`api/resumes.py`、`ArtifactsPage.tsx`、资料库 Resume 入口；Agent `read_artifacts`、`save_artifact`、Artifact-backed `write_file`、`record_artifact_submission`。

迁移：revision 0029、0038，详见 §12。
验证：`stage2-career-owner-and-process`、`stage2-resume-profile-ability-and-insights`、`stage3-artifact-offer-and-interview`、`stage1-attachment-claim-and-project-source`。
状态：`code_complete`。首份简历候选的最终批量确认 UX 仍为 §18.2 `open`。

## 4. §5～§7：岗位线、行动、Interview 与 Offer

### 4.1 JobOpportunity、ProcessEvent 与漏斗

- `JobOpportunity` 是具体岗位/批次 owner，保留 provider/site identity、canonical URL、对来源快照的关系/当前投影和多方向关系；搜索/浏览结果默认不入漏斗，JD 正文版本由下面的 append-only snapshot row 承担。
- `JobDescriptionSnapshot` 是岗位 JD 的 append-only来源快照，不是 Opportunity 第二 owner。每次真实观察形成独立 row/version/source identity；后来的页面读取或重新抓取不得覆盖旧正文。application 类 `ProcessEvent` 冻结当时实际使用的 JD snapshot identity；修正事件仍追加并保留原 event→snapshot 关系，历史漏斗/材料分析必须读取这条真实冻结关系，而不是套用 Opportunity 当前最新 JD。
- `track_search_job` 只接受同用户、completed `search_jobs` Tool Call 的 exact result 加用户确认；页面创建也调用同一 `career_process_service.py`。
- `ProcessEvent` append-only；纠错/撤销追加 relationship，不改原历史。当前 phase/current step/outcome 是投影；模糊 Observation 和单纯无回复不能成为事件/终局。
- 去重按强 identity 优先；模糊相似只提出候选。`JobOpportunityMerge`（0036）保存显式确认、operation key、canonical/duplicate identity 和可撤回关系，不搬迁或删除原两条历史。
- `funnel_analysis_service.py` 按当时方向、submitted material、渠道和事件形成样本/覆盖/混杂因素报告；不会把转化直接归因为能力。
- API/UI/Tool：`api/career_process.py`、`CareerProcessPage.tsx`、`CareerInsightsPage.tsx`、`read_career_context`、`track_search_job`、`capture_job_description`、`record_career_event`、`read_career_domain_state`。JD snapshot 支持 create/list/read 产品入口和页面投影；`track_search_job` 会在 exact 搜索结果本身含完整详情时原子保存快照，`capture_job_description` 则把用户明确指定的 owned completed `search_jobs` detail/`read_url` ToolResult 晋升为同一 owner 的 append-only 快照。Career read 按 active merge 关系呈现 canonical/duplicate 身份，并有界带出相关 ProcessEvents 与冻结 JD snapshot，而不把 merge/read model 变成新 owner。

迁移：0039，详见 §10.2。
验证：既有 `stage2-career-owner-and-process`、`stage2-resume-profile-ability-and-insights`、`stage4-gmail-observation-automation`；本批新增 `test_job_description_snapshot_service.py`、`test_career_process_jd_snapshots_api.py`、`test_stage2_job_description_snapshot_contract.py` 与 `test_career_context_extended.py`。
状态：岗位线/Event/漏斗、JD snapshot、application freeze/correction 与 active-merge/Event/JD Career read 均为 `code_complete`。

### 4.2 NextAction 与 Reminder

- `NextAction` 是独立业务状态，固定 `suggested/planned/done/closed`；不是 AgentTask、current_step 或 PersistentTask。
- 可关联 Opportunity/Interview/Offer/Artifact，但不复制其状态。更新/plan/complete/close 使用 version CAS 和可追溯来源。
- 时间保持 fixed/deadline/flexible 语义；agenda 读模型聚合冲突、今日/即将到期、planned 和 suggested，不压成唯一全局行动。
- Reminder 只是 planned NextAction 的通知投影；`reminder_service.py`、`notification_preferences` 和 in-app inbox/quiet hours 承担投递，不创建第二目标或第二任务生命周期。
- Agent/UI：`manage_next_action`，Career Process/Insights 页面；API 位于 `career_process.py` 与 `career_insights.py`。

迁移：0031 增加 typed links、version、reminder state、notification preference 和 ProcessEvent analysis context。
验证：`stage2-career-owner-and-process`、`stage2-resume-profile-ability-and-insights`。
状态：`code_complete`。关闭原因、批量行动物理关系和最终聚合 UX 仍为 §18.7～8 `open`。

### 4.3 Interview、Debrief、Mock 与 Offer

- Real/Mock `InterviewRecord` 可选 FK 到 owned JobOpportunity；Mock 无岗位也合法。`interview_record_service.py`、analysis intake/orchestrator 和 Mock Flow 在模型规划/Client Action 前校验 owner。
- 一个 InterviewRecord 是唯一 Debrief Project scope；多 Conversation 共享的文件通过 `InterviewSourceRef` 显式晋升。Conversation guidance、InterviewRecord/Debrief guidance、全局 CopilotPreference 三个 owner 分开。
- Mock 保持独立实时 Flow；`start_mock_interview` 通过 durable Client Action 区分 prefill ack、device readiness、真实 Runtime create/start identity 和 entered-UI ack。
- 每个 Opportunity 至多一个 current `Offer`。原始 source excerpt/formality 与 normalized terms 分离；非冲突 supplement 使用 CAS；replace/conflict 返回 typed diff，并要求 owned message 或稳定 product-UI operation key 的一种显式确认。
- `offer_analysis_service.py` 把换算、估值、风险、比较假设与 Offer 事实分开；保存报告时进入 Artifact。没有“本地接受/拒绝 Offer 即成功”的按钮或 Tool。
- API/UI：`api/interviews/`、`api/offers.py`、`api/career_insights.py`；Review/Mock/Offer/Artifacts 页面；`start_interview_debrief`、`read_interview_history`、`analyze_offers`。

验证：`stage3-artifact-offer-and-interview`、`stage3-mock-client-action-handoff`、`stage2-resume-profile-ability-and-insights`。
状态：`code_complete`；真实设备/浏览器 handoff 为 `deployment_required`。

## 5. §8：Personalization 与 Long-term Agent Memory

### 5.1 明确指导的 owner

| 用户表达范围 | owner/实现 | 生命周期 |
|---|---|---|
| 仅本 Turn | accepted user input + `CurrentTurnAnchor`（`current_turn_source.py`） | Turn 结束不自动延长 |
| 当前 Conversation | Conversation guidance，`personalization_service.py` + conversation guidance API/UI | 源 message 可回读，version CAS；不是 Memory |
| 本次复盘多 Conversation | `InterviewRecord` 的 Debrief guidance + `DebriefGuidanceControl` | 仅该 InterviewRecord；删除/清除按 owner |
| 以后/默认/所有 Conversation | 唯一 user-level `CopilotPreference` + Settings UI | 只保存明确协作规则；不含业务事实、权限或 Auto |

`manage_personalization_guidance` 根据当前真实 owner 和用户原话 scope 执行；Context 按“安全/Policy > 当前输入 > Conversation > Debrief > CopilotPreference > relevant Memory > 默认”装配一次。

### 5.2 canonical Long-term Agent Memory

- 唯一模型/owner：`AgentMemorySetting`、`LongTermAgentMemory`、`LongTermAgentMemorySource`；source Conversation/Turn 只是 provenance，不创建 scoped Memory。
- 内容边界：可跨未来任务改善协作的低权威经验，不限求职情境；禁止复制 CareerProfile、AbilitySignal、Domain State、Artifact/文件正文、精确 History/ToolResult、显式指导、Policy/Secret、Compaction/Recovery。
- 一条 Recall：`render_recall_block` 只选相关、active、同用户、live-source items；关闭 recall 或本 Turn “ignore memory”时不得隐性影响。
- 两个独立控制：账户 `recall_enabled`/`contribution_enabled` 与 Conversation overrides，均有 version CAS；关闭控制不等于删除。
- 管理：list/edit/invalidate/delete/promote-to-preference API/UI。删除清空 body，仅保留 content-free semantic/hash/source boundary suppression；来源 Conversation 删除会标记 source deleted，并在没有其他 live source 时失效，防止旧范围重放复活。
- 自动 producer：`consolidate_completed_turn` + `worker/tasks/agent_memory.py` 是唯一逻辑 producer，按 terminal/idle/contribution/source identity/semantic identity 幂等；失败不影响 History 或当前 Turn。
- 强制 release gate：`AGENT_MEMORY_PRODUCER_ENABLED: bool = False`。没有经过 Stage 5 代表性数据集全部门禁，设置页必须展示不可用，不能把用户 toggle 当作生效。

迁移：0033 建 canonical store、source provenance、账户/Conversation 双控制；legacy Memory 只作为离线迁移输入，见 §12.2。
验证：`stage5-guidance-and-canonical-memory`；静态强制门禁在 `validate_canonical_memory_boundary`。
状态：Recall/管理/删除为 `code_complete`；自动 producer 为 `gated`，当前禁止启用。

## 6. §9：Observation、Gmail 与 Attachment

### 6.1 Gmail Connector 与 Observation

- 第一条冻结的真实 Connector 是 Gmail readonly；没有通用 Connector/Secret/Source Registry。
- `GoogleGmailConnector` 实现 OAuth state + PKCE、exact redirect allowlist、browser-binding one-time state、verified subject/scope、grant generation fencing、bounded Gmail read/history cursor、refresh/revoke。
- App DB 的 `GmailIntegrationAccount` 只保存 masked account/scopes/status 和加密 opaque broker handle；raw access/refresh token 只在 `GmailCredentialStore` 边界。Community 可使用独立 recovery key、DB 外绝对路径、进程锁、原子替换、owner-only 权限的 encrypted-file broker；Cloud 必须注入 managed external broker，否则 Tool/连接不可用。
- `GmailObservation`/immutable `GmailObservationSnapshot` 按 provider message identity 去重、cursor CAS 增量拉取；邮件内容是不可信 data。高置信唯一匹配才经领域 Service 可逆应用；模糊项形成 task-local `GmailObservationReviewCard`，不直接写 ProcessEvent。
- API/UI/Tool：插件市场 Gmail 卡片内联 connect/status/test/revoke；Observation list/sync/review/retract；`gmail_search_messages`、`read_gmail_observations`、`review_gmail_observation`。

迁移：0030 增加 cursor、Observation/snapshot/review card；0034 删除 App DB token table并把非 revoked account 标为 reconnect required，凭据不迁移且 downgrade 只恢复空 schema。
验证：`stage4-gmail-connector`、`stage4-gmail-observation-automation`。
状态：协议与产品代码 `code_complete`；真实 Google consent/refresh/revoke/domain TLS 为 `deployment_required`。Outlook、日历、招聘平台等仍是目标能力，其接入顺序/contract 属于 §18.11～12；未实现 handler 不注册。

### 6.2 Canva 与 Notion 插件连接

- `OAuthPluginConnector` 只覆盖 closed provider `canva | notion`；授权状态以 HttpOnly browser-binding cookie + digest-only one-time DB state 绑定，Canva 叠加 S256 PKCE。
- `ExternalPluginAccount` 只保存 masked account、scope、状态与加密 opaque credential handle；access/refresh token 仅进入 DB 外的 `PluginCredentialStore`。Community 是独立 key 的 encrypted-file 实现；Cloud 没有 managed store 注入时必须不可用。
- 插件卡片直接承载 status/connect/test/revoke，不再跳转到第二个连接管理页。旧 `/settings/connections` 只保留到 `/plugins?plugin=gmail` 的兼容 redirect。
- 首批 capability 保守只读：`canva_search_designs` 搜索用户拥有/共享设计的 metadata；`notion_search_pages` 只搜索 OAuth page picker 明确共享页面的标题与链接。两者都不生成、导出、发布或写页面。
- 配置不完整时 API 返回 `adapter_available=false`、按钮禁用、Tool 不注册；已部署但用户未授权时才使用 connection-required waiting。

迁移：0041。验证：`stage4-plugin-market-connectors`。状态：代码与协议测试 `code_complete`；真实 Canva/Notion consent、refresh、revoke 与 Cloud managed secret-store 为 `deployment_required`。

### 6.3 Attachment 的 claim、读取、覆盖和生命周期

- `FileAsset` 拥有 bytes/version；`KnowledgeDocument`、chunks、vector 是可重建解析/检索投影。
- Composer upload 只创建 `ConversationAttachmentDraft`。统一 admission preflight 在写 History 前锁定校验；claim 与 UserMessage/Turn 同事务创建 immutable `ConversationAttachmentRef`，冻结 asset/version、Conversation、Turn、submission、顺序。
- processing 让同一 Turn `waiting(attachment_parsing)` 并释放 Agent 资源；callback + maintenance scan 只按 expected waiting reason/generation 恢复一次。failed 提供 retry、remove-and-continue 或 cancel。
- Source Resolver 显式 ref 优先，只在当前 Conversation 或 owned InterviewRecord scope 内按任务/relevance 读取；不会装载所有 ready 文件。`read_file` 只接受 exact attachment/source/Artifact identity，另可按同 Turn exact `tool_call_id` 分页回读 canonical ToolResult；不存在 owner-wide document/file bypass。
- 文本/分段/RAG/音频转写共享 scope identity。完整审阅由 `attachment_coverage.py` 证明连续 text segment；视觉审阅用 `inspect_attachment_pages` 读取 exact FileAsset version，当前限制为 PDF/PNG/JPEG、25 MiB、100 页、每次最多 4 页、长边 1600、2.5M pixels/page、2 MiB/page、7 MiB/call，并要求真实 model-page receipt + 连续全页覆盖。视觉任务显式区分 `local` 与 `full` scope：local 只允许声称已看选定页窗；full 必须在同一 source identity/FileAsset version 上形成从第一页到末页的连续 page coverage，任何局部 inspection 都不能满足全文视觉结论。无 vision model/transport/format/bytes 时 typed fail；Chat 不用 OCR/text 冒充视觉审阅。
- scope revoke、永久 FileAsset 删除、替换、Attachment→Debrief/Artifact 晋升和 Conversation 删除是不同命令。永久删除先展示引用和已外传影响，要求 exact filename 强确认，只承诺清理 Copilot 可控存储；正式引用保留 tombstone。
- Conversation 删除先关闭新 admission/claim、安全终结 active work、撤回 PendingSubmission/草稿 scope，并按 owner 清理。存在 unknown/in-flight/reconcile 外部调用时只保存 bounded content-free receipt correlation tombstone，由 maintenance purge。

API/UI：`attachment_sources.py`、`file_assets.py`、Composer chips/queued sources/AttachmentSources/Artifacts 页面；Service 位于 `attachment_ingress_service.py`、`attachment_source_service.py`、`attachment_artifact_promotion_service.py`、`file_asset_deletion_service.py`、`conversation_deletion_service.py`。
迁移：0035、0038；legacy attachment quarantine 见 §12.2。
验证：`stage1-attachment-claim-and-project-source`、`stage1-attachment-format-and-coverage-truth`、`stage0-durable-admission-and-interrupt`。
状态：Attachment/coverage/vision 与 visual `local/full` scope 均为 `code_complete`。最终格式矩阵、孤儿时限、preview/warning 阈值仍为 §18.10 `open`；真实对象存储/vision Provider 为 `deployment_required`。

## 7. §10～§11：Application Profile、Context、Turn 与 Agent Loop

### 7.1 Profile、Strategy 与同一上下文宇宙

- `runtime_profile.py`/`factory.py` 选择 Career 或 Debrief Profile；同一 Conversation 每个 admitted Turn 冻结 Chat/Agent strategy snapshot。Mock 不进入 Router。
- Chat 与 Agent 共用 `ContextAssemblyPipeline`、Source Resolver、RAG/grounding/citations、personalization 和 Provider context projection。Chat planner 只增加当前 Turn 的 bounded read request，不能排除显式来源或获得执行能力。
- `provider_context.py` 是唯一 provider-neutral `system + chronological messages` 投影。动态附件/RAG/Memory/产品数据作为低权威 user data 靠近当前 input；Runtime checkpoint/recovery JSON 不进入 Prompt。
- `model_provider_adapter.py` 把同一请求转换到 OpenAI-compatible 或 Anthropic；Anthropic 物理 cache order 是 tools → stable non-private system → messages，私有 History/guidance/retrieval/current input 不打跨用户 cache marker。cache read/create usage 进入 telemetry；不支持 cache 的 Provider 收到语义完整请求。
- 一个 canonical `ContextAssemblyPipeline` writer 以 exact message seq 合并 old summary，并原子提交 summary + cursor；`context_compactor.py` 只做 loop-local投影/压力恢复，不写第二份 Summary。Token 压力采用 provider usage + delta，fresh/no-usage 时估算完整 tools/system/messages。

验证：`stage0-agent-task-and-context`、`stage0-native-provider-cache-and-execution-mode-cas`、`stage0-shared-source-acquisition`、`stage1-attachment-format-and-coverage-truth`。
状态：`code_complete`；live cache hit/miss 与真实模型兼容为 `deployment_required`。

### 7.2 PendingSubmission、Turn、Interaction、AgentTask 与完成裁定

- `PendingSubmission` 是唯一普通输入 ingress。`turn_executor.py` 在 Conversation lock 下做 fingerprint/version、附件草稿和 typed object preflight；仅在没有 active Turn 且队列为空时原子 claim 并创建 UserMessage/Turn/Anchor，否则分配服务端 FIFO。claim 前可 CAS edit/withdraw；失败项形成 hold，不跳过。
- waiting resolution 只解决同一个 `AgentInteraction` 并恢复同 Turn/call；普通 Composer 永远不猜成 approval/connection/clarification。一个 Turn 同时至多一个 unresolved Interaction。
- 显式“停止当前并发送”绑定 submission/version，关闭 model/Tool dispatch generation，取消 stream，闭合未启动/已启动 Tool 的真实结果；旧 Turn durable cancelled 后才原子 claim 选中项。SSE detach/刷新/换页不等于 cancel。
- 简单 Turn 不创建 AgentTask。复杂请求最多一个 `AgentTask` + immutable revision metadata + 扁平 phase；waiting/blocked/failed/cancelled 不复制到 phase。
- Shared Kernel 只用 completed/waiting/blocked/failed/cancelled。无 structured Tool Call 只是 candidate completion；completion gate 检查 unresolved call、真实 Application Service/Artifact/receipt 和适用 AgentTask phases。
- `AgentModelDispatch`（0032）保存 provider/model/fingerprint/generation/partial/usage/status，迟到 generation 不得复活 Turn。局部重复、空输出、截断、超时和 compaction 风险各有有限 repair，不使用全局 max steps/tool calls/token 代替语义完成。
- 完整 redacted Tool result 的 canonical owner 是 `AgentToolCall.result_json`。超过 model inline budget 时只投影 preview + exact call id；`read_file(tool_call_id, offset, limit)` 按 current user/session/Turn fence 从数据库回读，不写 worker-local `agent-results` 文件，也不形成第二份 store。
- 本批为真实副作用增加跨 Turn/Conversation reconcile latch：`AgentToolCall` 在 dispatch/audit 记录中保存 typed concrete resource identities；删除 Conversation 时，未结算 call 的最小 `ConversationDeletionReceipt` 同步保留这些 identity。任何后续 Turn 或另一 Conversation 准备对同一 user/resource 发起冲突副作用时，Executor 必须查询 unresolved running/unknown/reconcile call 与删除 receipt；在 receipt/read-back 得出终局前 fail closed/要求 reconcile，不能因为旧 Conversation 已删除或 call id 不同而重复执行。resource identity 只用于冲突隔离与回执关联，不保存用户正文、不获得领域 owner 地位，也不把所有读取全局串行化。

UI：`ChatPanel`/`usePendingSubmissions`；固定单列 Activity Control Layer 中 `AgentTaskCard` 在上、`InteractionCard` 在下；streaming 时保留 inline Tool 动态，Turn 完成后同一批轨迹默认折叠成可重开的摘要。回答复制只取 assistant text blocks，不复制 Tool 参数/结果。`MessageBlocks` 和 audit API 从同一 call identity/read model 派生默认、inline、deep audit。
迁移：0032、0035、0037、0040。
验证：`stage0-durable-admission-and-interrupt`、`stage0-tool-policy-and-recovery`、`stage0-agent-task-and-context`、`stage0-native-provider-cache-and-execution-mode-cas`。
状态：Turn/Tool recovery 与跨 Turn/Conversation resource reconcile latch 均为 `code_complete`。

## 8. §12：PersistentTask

- `PersistentTask` 是用户显式创建的顶层持续自动化，只保留 active/paused；一个 task 始终一条 Dedicated Conversation。
- `PersistentTaskTrigger` 是 durable automation ingress，不是第二 Run model。manual/scheduled idempotency、strict five-field cron、IANA timezone、minimum interval、DST-aware next cursor 和 maintenance repair 位于 `persistent_task_schedule.py`/worker。
- 每次 trigger 创建现有 `ConversationTurn`；同一 task 最多一个 active/waiting Turn，后续 trigger 合并并在结算后最多一次补偿。Dedicated Conversation 的 PendingSubmission 与 trigger 分开保存但共用 Conversation admission/CAS，用户输入固定优先。
- unattended catalog 在 claim 时重读当前 task definition/version 和 exact eligible read Tool names；排除 Client Action、Skill/MCP discovery、未知/写 Tool。需要用户时形成当前 Interaction 并释放 Worker。
- stop-this-run、pause-future、resume 和 delete 分开。delete 先 preflight/impact preview + strong confirmation，关闭调度/admission，安全终结 Turn，撤回队列/草稿并删除 Dedicated scope；已经晋升的 Domain State/Artifact 不级联。unknown external result只留下 bounded receipt tombstone。
- API/UI/Agent：`api/persistent_tasks.py`、`PersistentTasksPage.tsx`（含 Dedicated Conversation/trigger history）、`manage_persistent_task`。

迁移：0017/0020 建基础与 schedule cursor；0032 增 Skill refs（无人值守仍需重验）；0035 提供删除 receipt tombstone。
验证：`stage4-persistent-task`、`stage4-gmail-observation-automation`、`stage0-durable-admission-and-interrupt`。
状态：`code_complete`；真实 Scheduler/Redis/Celery restart/repair smoke 为 `deployment_required`。

## 9. §13～§15：Tool、Skill、Provider、Policy 与并行

### 9.1 一条 Tool pipeline

唯一链路为 `ToolDefinition → registry/discovery → concrete preflight → tool_policy → tool_call_executor → typed ToolResult`。`tool_registry.py` 只注册真实 handler；`turn_tool_catalog.py` 以稳定顺序投递 schema，full schema 只在 Provider `tools` 参数一次出现。`tool_search` 只加载 deferred concrete schema，不执行或授权目标 Tool。

当前真实 task-shaped Tool 包括：

- 公共读：`web_search`、`read_url`、`search_knowledge`、`read_file`、`inspect_attachment_pages`、`read_resume`、`read_interview_history`、History 两个 Tool；
- Career/Artifact：`read_career_context`、`track_search_job`、`capture_job_description`、`record_career_event`、`read_artifacts`、`save_artifact`、八个 `career_domains.py` Tool；
- Runtime/Flow：`task_create`、`task_update`、`start_mock_interview`；
- Integration/Observation：配置真实 adapter 后的 Gmail read/Observation Tool；
- Personalization：`manage_personalization_guidance`。

`write_file` 只写 Artifact，不暴露任意文件系统。`save_memory`、legacy `recall_memory`、`task_checkpoint`、`task_verify`、demo/placeholder handler 已移除。Tool input/result/error 在 DB、History、SSE、replay、audit 与日志前走 `tool_redaction.py`；ToolResult 是不可信 model data，外部写成功必须 receipt/read-back。

### 9.2 Skill、MCP 与 Provider

- Skill 三层加载由 `skill_service.py` + `turn_tool_catalog.py` 实现：catalog/`skill_search` → 完整 `skill_load` → 按主说明 `skill_resource_load`。revision/content hash/source/profile/required/allowed Tool 持久化；AgentTask 绑定 exact version，PersistentTask 每次重验。
- allowed-tools 只取交集收窄当前可用集合。Skill 不能提供 handler、connection、scope、Policy 或成功证明，也不 fork Agent。
- MCP 与 built-in Tool 进入同一 executor/policy/redaction。Cloud hard-deny stdio；Community stdio 只传最小环境白名单。远程 HTTP/MCP 使用 SSRF/redirect/size边界；未知 effect 默认 fail closed。
- Tavily/Web/Job/Gmail 使用各自 deployment/provider配置，不借用用户模型 API key。`web_search` 的主源 Tavily 缺配置、超时或返回非成功状态时自动降级到 keyless DuckDuckGo best-effort 搜索；Lever 仍是逐公司 site 的公开 Postings API，无效 slug/超时/零匹配分别报告。只有真实 user grant 缺失才进入 connection waiting，部署配置缺失不写伪 Interaction 或固定成功。

迁移：0032、0037。
验证：`stage0-tool-policy-and-recovery`、`stage0-agent-task-and-context`、`stage0-native-provider-cache-and-execution-mode-cas`、`cross-stage-exact-history-and-workspaces`。
状态：`code_complete`；远程 MCP/Provider live transport 为 `deployment_required`。

### 9.3 Standard/Auto 和参数级 Policy

- execution mode 有用户“新 Conversation 默认”、Conversation CAS 和 admitted Turn snapshot 三个边界；修改默认不回写旧 Conversation，修改 Conversation 不改变 active/queued frozen snapshot。
- 每个具体 call 固定顺序检查 hard deny → connection/account/data scope → current task/PersistentTask范围 → domain identity/source/state → retained decision/critical fact → Standard/Auto → allow/ask/deny。
- Standard 中 read 可直接执行；当前任务明确包含且领域允许的可逆内部写可直接执行；普通外部副作用在未被当前原文精确授权时 ask。Auto 只省 routine task-scoped approval；不能越过 hard deny、Provider scope、用户保留决定、不可逆动作或不确定参数。
- ask 绑定 exact call/objects/account/content/version，恢复同 Turn/call。候选并行批次只要一项 ask/connection wait，整批在 dispatch 前零启动；恢复后重做 handler/scope/policy/resource conflict 检查。
- 并行只允许无依赖、已解析、分别 allow、资源 identity 不冲突、失败可独立解释的 calls。完成事件按 call id 原位更新，model/history replay 保持原 model order（0037 的 model order/completion sequence）。

验证：`stage0-tool-policy-and-recovery`、`stage0-native-provider-cache-and-execution-mode-cas`、`stage4-persistent-task`。
状态：`code_complete`。

## 10. §16：代码所有权与迁移

### 10.1 当前代码分层

| 蓝图 owner | 当前主要代码 | 不拥有 |
|---|---|---|
| presentation | `backend/app/api/`、`frontend/src/`、SSE/read projections/ClientActionBridge | 队列顺序、领域事实、Tool 成功 |
| conversation | `backend/app/conversation/`、`services/chat/turn_executor.py`、context/source/interaction services | Agent loop、queued input 之外的领域状态 |
| agent_runtime | `backend/app/agent_runtime/` | PendingSubmission、UI card state、产品 owner |
| career domain/application | career/ability/artifact/offer/interview/action services + models | FastAPI/React/model SDK/向量库 |
| rag | `backend/app/rag/`、attachment source/coverage services | 来源所有权、业务事实 |
| preferences | `personalization_service.py`、`agent_memory_service.py`（两个概念仍分 owner） | 业务事实、执行授权 |
| integrations | Web/URL、Gmail、MCP adapters | 直接绕过 Application Service 写领域事实 |
| infrastructure | DB/storage/queue/model adapters/cache telemetry | 产品生命周期与事实权威 |

### 10.2 revision 0029～0041 线性迁移记录

| Revision | down | 具体变化 | 执行/回滚注意 |
|---|---|---|---|
| 0029 | 0028 | 建 `artifact_resume_states`、逐项 `career_profile_candidate_items`；Interview 保存 exact resume Artifact/version 和 ability generation；AbilitySignal 加 producer idempotency。已有 resume Artifact补 sidecar；legacy Resume 确定性写入 Artifact v1、保留 `legacy_resume_id` alias、回填 Interview；已有 draft 展开为 candidate items | production 后只读写 Artifact。legacy tables 仅迁移/历史输入；未映射 identity 必须明确 `resume_artifact_not_found/not_migrated`，不得运行时回退。downgrade 会删除 `legacy_resume:*` 创建的 Artifact，执行前必须备份/评估 |
| 0030 | 0029 | Gmail account 加 history cursor/sync状态；建 Observation、immutable source snapshot、task review card，按 account+provider message 与 task+observation 去重 | cursor 与 Observation 分开；模糊 card 未批准不写事件 |
| 0031 | 0030 | ProcessEvent 加 analysis context；NextAction 加 Interview/Offer/Artifact links、version、reminder delivery fields；建 notification preferences | Reminder 必须 attached to non-suggested NextAction；当前只允许 in-app channel |
| 0032 | 0031 | 建 durable model dispatch；Skill 加 revision/hash/source/profile/required/allowed tools；资源表、AgentTask Skill binding、PersistentTask skill refs | migration 对现有 Skill content 计算 SHA-256；恢复/自动化必须按 exact revision/hash 重验 |
| 0033 | 0032 | 建唯一 user-level Memory settings/store/source provenance；Conversation 加 recall/contribution overrides 与 CAS version | producer 配置仍默认 off；此 revision 不迁入 legacy mixed Markdown |
| 0034 | 0033 | 将所有非 revoked Gmail account 标为 reconnect required，并删除 App DB token table | token 有意不复制到 broker；用户必须重新授权。downgrade 只恢复空 schema，不能恢复/伪造 credential |
| 0035 | 0034 | 建 Conversation 删除后的 bounded receipt-correlation tombstone，含 user/conversation/turn/call/generation/status/correlation/retain-until | 只能保存最小 correlation，无正文/History；resolved/到期由 maintenance purge |
| 0036 | 0035 | 建可撤回 JobOpportunity merge relation，保存 operation/retraction keys、confirmation source、version 和 active duplicate unique gate | 不物理合并/覆盖事件、来源或岗位；误合并追加 retract |
| 0037 | 0036 | AgentToolCall 加 model step/index/order、completion sequence、handler/provider/connection identities、typed timeline/receipt refs | UI 可按完成更新，但 model/history 必须按 model_call_order；仍统一脱敏 |
| 0038 | 0037 | ArtifactVersion 加 exact `file_asset_version` | Attachment→Artifact promotion 必须冻结原版本，不能绑定同名/最新 asset |
| 0039 | 0038 | 建 append-only `JobDescriptionSnapshot` 真实表和 Opportunity/source/version 约束；application ProcessEvent 保存 exact JD snapshot identity，使纠正/漏斗可沿历史冻结关系读取 | 新观察只能新增 snapshot；不得更新旧正文或让“最新 JD”倒改历史 application event。迁移、Service、API、Agent、UI 与自动化验证均已接入 |
| 0040 | 0039 | `AgentToolCall` 与 `ConversationDeletionReceipt` 增 typed resource identities，用于 unresolved external-effect 的跨 Turn/Conversation conflict/reconcile 查询 | 只复制最小 resource correlation；终局前对同 user/resource 的冲突副作用 fail closed，终局后解除 latch。不得保存正文、复活 Conversation 或把不同资源全局串行 |
| 0041 | 0040 | 建 Canva/Notion provider-specific OAuth account 与一次性 state 表 | App DB 只保留 masked account/scopes/status 与 opaque credential handle；token 位于独立加密 credential store。Canva 只注册 design metadata search，Notion 只注册用户授权页面的 title/link search；未配置真实 OAuth 时卡片禁用且 Tool 不注册 |

目标链保持 `0028 → 0029 → … → 0039 → 0040 → 0041` 单 head。API startup 会拒绝未到 head 的 DB。静态 Alembic/ORM/identifier/single-head 检查已经进入 mandatory test；这些检查仍不能代替真实 Postgres 的 fresh upgrade、现存数据 upgrade、downgrade/restore、index/constraint/cascade 检查。

### 10.3 legacy 分类、quarantine 与删除

| Legacy 数据 | 处理规则 | 实现/报告 |
|---|---|---|
| Resume/ResumeSection | 0029 确定性 materialize 为 Artifact；旧 identity 只经 `ArtifactResumeState.legacy_resume_id` 定位 migrated Artifact。生产 API/Tool/Interview/Mock 不读/写旧正文表 | 0029、`resume_artifact_service.py`、`test_resume_artifact_service.py`、`test_resume_worker.py` |
| mixed MemoryDocument Markdown | 无法证明 owner，全部 quarantine；不能整体复制到 CareerProfile、CopilotPreference 或 Long-term Memory | `legacy_memory_migration.py` / `scripts/migrate_legacy_memory.py` JSON report |
| legacy ability state | 仅有 numeric score、解释和可验证 live source 时创建 low-confidence canonical AbilitySignal；确定性 rubric idempotency；否则 quarantine | 同上；`test_legacy_memory_migration.py` |
| legacy deleted-memory audit body | apply 时清空 before/after body，避免“忘记”后审计快照仍保存正文 | 同上 |
| legacy `KnowledgeDocument(source_kind=chat_attachment)` | 只有 canonical draft/ref/InterviewSourceRef 已存在时视为 parser projection；否则 report + soft quarantine，保留 FileAsset 供用户显式重新附加/晋升，绝不制造 Turn/History/scope | `legacy_attachment_migration.py` / `scripts/migrate_legacy_attachments.py`；`test_legacy_attachment_migration.py` |
| SessionTask/capability/memory万能路径 | callable/runtime writer/Recall 已移除；不保留兼容 owner | scenario static gate、Tool registry/runtime tests |

所有 operational migration helper 默认 dry-run，`--apply` 由部署者显式执行并保存 UTF-8 JSON report；caller 负责 commit/rollback。迁移后 legacy rows 不得影响 Context、Analytics、UI 或 Tool。

状态：代码迁移 `code_complete`；目标数据库执行、备份与恢复演练为 `deployment_required`。

## 11. §17：可执行评测与发布判定

`evaluation/career_scenarios.json` 是 Stage 0～5 的可执行 claim→test matrix；`evaluation/career_scenario_eval.py` 先验证所有 Stage Spec、scenario id、claim 和测试路径，再运行去重后的 backend/frontend tests。backend pytest 产生 JUnit；任何 mandatory skip、缺报告、缺文件、超时或非零返回都使 gate 失败。runner 强制 `CUDA_VISIBLE_DEVICES=-1`，frontend 单 worker，避免验证进程重复占用 GPU。

静态结构/Memory gate：

    python evaluation/career_scenario_eval.py --static-only

完整协议级矩阵：

    python evaluation/career_scenario_eval.py

完整矩阵证明仓库实现和协议级 fake，不证明 live Gmail、真实浏览器、多实例云基础设施或模型 Provider。发布报告必须另存 dataset revision、model/provider config、exact code revision、denominator、numerator、skips 和失败。

状态：评测框架 `code_complete`；环境缺失导致的 mandatory skip 必须维持 `deployment_required`，不能改成可选通过。Memory representative dataset 尚未存在，producer 保持 `gated`。

### 11.1 2026-08-13 最终仓库验证报告

本批新增不变量已经与全仓门禁一起实际执行，不再使用先前 usage-limit 期间的 `implemented_unverified` 结论：

| 门禁 | 当次结果 |
|---|---|
| 后端完整测试集 `python -m pytest backend/tests -q` | `1443 passed, 5 skipped`；5 个 skip 均是需要可达真实 PostgreSQL 的迁移用例 |
| 前端完整测试集 | `51 files / 162 tests passed`，单 worker |
| 前端静态与生产构建 | TypeScript build、ESLint 零 warning、Vite production build 全部通过 |
| Python 静态与编译 | 全仓 Ruff check、Ruff format、compileall、`git diff --check` 通过 |
| 场景与迁移静态门禁 | 17 个 Stage 0～5/cross-stage 场景加载通过；Alembic `0041` 单 head；ORM/迁移列、identifier、链路静态测试通过 |
| 新增 targeted 链 | JD snapshot/Agent capture、Career merge/Event/JD read、Shared Source、visual local/full、resource reconcile latch、CopilotStatusSummary 均已纳入上述完整测试并通过 |
| 插件市场增量链 | Canva/Notion OAuth service/API/Tool、Gmail 回归、Tool registry、ORM/storage、迁移共 `105 passed`；真实浏览器已验证 Gmail/Canva/Notion 卡片内联展开、旧连接导航消失、未配置状态 fail closed |

本机应用 PostgreSQL 已把现存 schema 从 0040 真实升级到 0041；这证明当前应用库升级可执行，但不允许拿它做破坏性的 fresh/downgrade 演练。当前仍未配置专用 `TEST_PG_ADMIN_URL`，所以隔离库上的 fresh/legacy upgrade、downgrade/restore、index/constraint/cascade 仍严格保留为 `deployment_required`，没有把 mandatory skip 伪装成通过。

## 12. 场景与测试证据索引

以下是每个 section 表中 scenario id 的精确执行绑定；最终 pass/fail 只认 runner 当次报告。

| Scenario | Backend tests | Frontend tests |
|---|---|---|
| `stage0-durable-admission-and-interrupt` | `test_turn_executor.py`、`test_conversation_deletion_service.py`、`test_chat_api.py`、`test_tool_call_executor.py`、`test_maintenance_sweeper.py`、`test_celery_routes.py` | `src/api/chat.test.ts`、`ChatToolbar.test.tsx` |
| `stage0-tool-policy-and-recovery` | `test_tool_policy.py`、`test_tool_call_executor.py`、`test_model_dispatch_service.py`、`test_tool_call_audit_api.py`、`test_chat_api.py`、`test_maintenance_sweeper.py` | `InteractionCard.test.tsx`、`MessageBlocks.test.tsx` |
| `stage0-agent-task-and-context` | `test_agent_task_service.py`、`test_agent_strategy_stream.py` | `AgentTaskCard.test.tsx` |
| `stage0-shared-source-acquisition` | `test_shared_source_acquisition.py`、`test_planner.py`、`test_context_pipeline.py`、`test_chat_strategy.py`、`test_grounding_protocol.py` | — |
| `stage0-native-provider-cache-and-execution-mode-cas` | `test_model_provider_adapter.py`、`test_model_runtime.py`、`test_provider_context.py`、`test_chat_strategy.py`、`test_agent_strategy_stream.py`、`test_telemetry_service.py`、`test_chat_api.py`、`test_alembic_migrations.py` | `useSessionExecutionMode.test.tsx` |
| `stage0-typed-product-object-anchor` | `test_product_object_reference.py` | `copilotObjectReference.test.ts`、`GeneralChatPage.test.tsx`、`Bubble.test.tsx` |
| `stage1-attachment-claim-and-project-source` | `test_attachment_ingress_service.py`、`test_attachment_source_service.py`、`test_attachment_artifact_promotion_service.py`、`test_attachment_sources.py`、`test_file_assets_api.py`、`test_file_asset_deletion_service.py`、`test_artifact_service.py`、`test_resume_artifact_service.py`、`test_career_tools.py`、`test_alembic_migrations.py` | `AttachmentSources.test.tsx`、`src/api/chat.test.ts`、`src/api/fileAssets.test.ts`、`ArtifactsPage.test.tsx` |
| `stage1-attachment-format-and-coverage-truth` | `test_document_ingestion.py`、`test_attachment_vision_tool.py`、`test_model_provider_adapter.py`、`test_attachment_coverage.py`、`test_chat_strategy.py`、`test_legacy_attachment_migration.py` | `attachmentUpload.test.ts`、`AttachmentSources.test.tsx` |
| `stage2-career-owner-and-process` | `test_career_profile_api.py`、`test_career_process_api.py`、`test_career_tools.py`、`test_career_domain_tools.py`、`test_career_process_service.py`、`test_legacy_memory_migration.py`、`test_job_description_snapshot_service.py`、`test_career_process_jd_snapshots_api.py`、`test_stage2_job_description_snapshot_contract.py`、`test_career_context_extended.py` | `src/api/careerDomains.test.ts`、`CareerProfilePage.test.tsx`、`CareerProcessPage.test.tsx` |
| `stage2-resume-profile-ability-and-insights` | `test_resume_artifact_service.py`、`test_resume_worker.py`、`test_ability_signal_service.py`、`test_career_insights_service.py`、`test_career_insights_api.py` | `CareerProfilePage.test.tsx`、`CareerProcessPage.test.tsx` |
| `stage3-artifact-offer-and-interview` | `test_artifacts_offers_api.py`、`test_interview_api.py`、`test_career_domain_tools.py` | `ArtifactsPage.test.tsx`、`src/api/careerDomains.test.ts` |
| `stage3-mock-client-action-handoff` | `test_client_action_service.py`、`test_client_actions_api.py`、`test_mock_interview_tool.py` | `ClientActionBridge.test.tsx` |
| `stage4-persistent-task` | `test_persistent_task_service.py`、`test_persistent_task_schedule.py`、`test_stage4_integrations_api.py`、`test_career_domain_tools.py`、`test_maintenance_sweeper.py`、`test_celery_routes.py` | `PersistentTasksPage.test.tsx`、`src/api/persistentTasks.test.ts`、`src/api/stage4.test.ts` |
| `stage4-gmail-connector` | `test_google_gmail_connector.py`、`test_gmail_oauth_api.py`、`test_gmail_tool.py` | `PluginConnectionPanel.test.tsx`、`CapabilitiesPage.test.tsx`、`src/api/stage4.test.ts` |
| `stage4-plugin-market-connectors` | `test_oauth_plugin_connector.py`、`test_external_plugins_api.py`、`test_external_plugin_tools.py`、`test_alembic_migrations.py` | `PluginConnectionPanel.test.tsx`、`CapabilitiesPage.test.tsx` |
| `stage4-gmail-observation-automation` | `test_gmail_observation_service.py`、`test_gmail_observations_api.py`、`test_gmail_observation_tool.py` | `GmailObservationCards.test.tsx` |
| `stage5-guidance-and-canonical-memory` | `test_personalization_service.py`、`test_personalization_tool.py`、`test_agent_memory_service.py`、`test_personalization_api.py`、`test_career_scenario_gate.py` | `src/api/personalization.test.ts`、`CopilotPreferencesPage.test.tsx`、`AgentMemorySettingsSection.test.tsx`、`ConversationMemoryControlsButton.test.tsx` |
| `cross-stage-exact-history-and-workspaces` | `test_interaction_history_service.py`、`test_history_api.py`、`test_tool_registry.py` | `src/api/history.test.ts`、`HistorySearchPage.test.tsx`、`CopilotStatusSummary.test.tsx` |

测试文件均以 `backend/tests/...` 或 `frontend/src/...` 为根；完整绝对列表由 manifest validator 输出，避免本文和 manifest 分叉。

## 13. §18 仍开放的选择

以下内容当前代码可以有安全默认值，但不得写成已确认产品事实：

1. 四工作空间最终页面/抽屉/批量交互、Client Action catalog、执行动态/卡片/Tool 详情/队列的视觉密度、数量/保留、文案、键盘与窄屏 UX。
2. 首份简历候选的批量接受、冲突突出和修正 UX。
3. CareerProfile/AbilitySignal/Artifact/Interview/Offer 的进一步最小物理字段和迁移顺序。
4. 首批真实岗位 Provider 能提供并需要持久化的 identity 线索。
5. current_step/结束步骤/等待时长/注意信号是否因查询性能持久化。
6. pending_application 提醒阈值与用户删除/归档方式。
7. NextAction 最小关闭原因/来源/完成证明和页面聚合。
8. 批量 NextAction 是多对多还是只读聚合。
9. 材料效果分析的样本下限、统计与混杂因素呈现。
10. Attachment 最终格式/限制、进度、warning、preview/source card、孤儿回收/软删期限和 parser 选择。
11. 邮箱 Provider 顺序、高置信规则、同步频率、通知与最小保留。
12. 下一个云 OAuth Connector 的具体 grant/secret/refresh/revoke/retention contract。
13. PersistentTask trigger/cursor/card/retry/notification 的进一步精确体验。
14. History/Memory retention、Memory 默认控制值/UX、producer 价值阈值/遗忘体验；producer 当前仍 gated。
15. 首批 Tool 覆盖和按 typed contract/effect/provider 差异的拆分。
16. Tool payload budget、Artifact 化、错误/extension、用户摘要、脱敏与审计保留细则。
17. Skill catalog metadata、filter/search/cache/update/incompatibility UX。
18. Profile 的精确 Context Contract、Chat planner budget/metrics、Chat/Agent toggle UX、scope 优先级、cache/compaction threshold tests。
19. Connection/scope/ask 的账号选择、升级、拒绝和恢复文案。
20. 场景 gold/source labels、成本、修正数据与隐私数据集构建方式。
21. 未来是否引入隔离只读 worker；当前明确不实现通用子 Agent。

这些 open 项不得重开已经冻结的 owner、五种 TurnOutcome、单 active Turn、FIFO admission、explicit interrupt、Attachment/Debrief scope、单 Memory owner、Tool pipeline、参数级 Policy、receipt/read-back 和用户保留决定。

## 14. §19 验收不变量覆盖

| 不变量范围 | 生产 owner/主要证据 | 状态 |
|---|---|---|
| 1～11 产品与领域状态 | CareerProfile/AbilitySignal/Artifact/Opportunity/Event/Action/Offer services；Stage 2/3 scenarios | `code_complete`，含 JD snapshot/freeze/Career-read |
| 12～19 Context、Memory、RAG | Context pipeline/provider projection/shared source/history/canonical Memory；Stage 0/1/5 scenarios | `code_complete`，含 explicit-ref/URL-overflow；automatic producer `gated` |
| 20～31 Attachment/Debrief | FileAsset/Draft/Ref/InterviewSourceRef、coverage、vision、promotion/deletion；Stage 1 scenarios | `code_complete`，含 visual local/full；live storage/vision `deployment_required` |
| 32～44 Turn/Submission/Task/Recovery | PendingSubmission/ConversationTurn/AgentInteraction/AgentTask/ModelDispatch/Kernel；Stage 0 scenarios | `code_complete`，含 resource reconcile latch |
| 45～50 PersistentTask | PersistentTask/Trigger + Dedicated Conversation + shared admission/deletion receipt；Stage 4 scenarios | `code_complete`；multi-process scheduler smoke `deployment_required` |
| 51～62 Tool/Skill/Policy/result | Registry/catalog/executor/policy/redaction/audit/model order/Skill runtime；Stage 0/4 scenarios | `code_complete`，含 cross-Conversation resource latch；live provider receipts `deployment_required` |
| 63～74 架构与演进 | shared Application Services, AppShell Client Action, closed object refs, single Agent, no generative UI; cross-stage scenarios | `code_complete`，含 CopilotStatusSummary只读 projection |

“代码完成”只表示当前 frozen contract 在仓库内闭环并进入 mandatory scenario matrix。任何 external gate 未通过、mandatory test skip、migration report 未保存或 Memory producer 被手工开启，都会阻止“生产发布符合整份蓝图”的结论。

## 15. 生产发布前仍必须完成的外部门禁

1. **Postgres**：为 `TEST_PG_ADMIN_URL` 提供隔离实例，执行包含 0039 JobDescriptionSnapshot、0040 Tool resource identities 与 0041 Canva/Notion OAuth account/state 的 fresh upgrade、现存数据 upgrade、downgrade/restore、单 head、index/constraint/cascade；生产执行前备份，并保存 0029 legacy Resume、legacy Memory/Attachment dry-run/apply 报告。静态/Alembic tests 已通过；单元测试或 SQLite 仍不能代替真实 Postgres。
2. **Gmail**：配置真实 HTTPS redirect/product return、Google client、目标域 consent、Community 独立 broker recovery key/绝对路径或 Cloud managed broker；用非提交凭据验证 connect、browser binding、refresh、scope loss、revoke、reconnect、cursor。HTTP fake 不代替。
3. **Canva/Notion**：分别在 provider developer console 注册公开 OAuth integration 和精确 callback；配置独立 credential-store recovery key/路径。用真实测试账号验证 Canva PKCE、Notion page picker、refresh/revoke 与只读 Tool；HTTP fake 不代替。
3. **模型/Prompt Cache/Vision**：配置真实 provider/model，验证 Tool schema、streaming、cache read/create/miss telemetry、image transport、partial/cancel/retry；不支持能力时必须保持 typed unavailable。
4. **云基础设施**：验证 Redis/SSE replay、Celery scheduler/maintenance、对象存储、RAG 索引重建、多 worker restart、unknown receipt reconciliation、备份/恢复。测试进程必须保持 CPU-only；不要为验证重复启动 GPU model workers。
5. **浏览器与多客户端**：在真实部署做 refresh、multi-tab FIFO/CAS、initiating-client affinity/takeover、unsaved guard、Mock device readiness 和 AppShell route-switch handoff。React unit test不代替真实浏览器。
6. **Memory release**：使用版本化、人工审阅的代表性跨任务数据集，逐项达到 Stage 5 的 owner routing 100%、敏感内容 100% 排除、无高严重无关 recall、无 stale fact、无 cross-user/scoped store、disabled 零影响、forget/source-delete 零复活、promotion 零重复、单 producer/Recall 路径等全部门禁；报告 denominator/numerator、dataset/model/provider/code revision。此前 `AGENT_MEMORY_PRODUCER_ENABLED` 必须保持 false。
7. **真实性边界**：没有实现的 Outlook/Calendar/招聘平台/发送邮件/Offer 接受拒绝签署等能力不得通过 UI、Prompt 或 Tool catalog宣称可执行。以后新增时先冻结对应 Provider contract、scope、Policy、receipt/read-back 和场景测试。
