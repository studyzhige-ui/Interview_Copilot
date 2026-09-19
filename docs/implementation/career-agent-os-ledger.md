# Career Agent OS Implementation Ledger

> 状态：现行实施账本；工程实现与现行架构收口，按提交验收；不合并 main、不宣称生产发布
> 日期：2026-09-19
> 规范来源：[`Career Agent OS Blueprint`](../architecture/career-agent-os-blueprint.md)  
> 当前切片：[`VS-01 面试邀请接收、确认与准备交接生命周期`](../architecture/vertical-slices/vs-01-interview-invitation-intake-confirmation-handoff.md)



## 本地优先全量功能重构：首批实施（2026-09-19）

这是在 `f05555d7…` 已验收工程基础上的新一轮功能重构。**并非把下面P0–P9整体标成完成。**
维持原分支和Draft，不合并main；不读取用户本机文件或输出Secrets，不因评测预算充足而无限调用。
现有录音复盘的原文件身份、WhisperX对齐/说话人证据和权限合同保持不变。

| 工作包 | 当前范围与状态 | 验收/后续边界 |
|---|---|---|
| P0 评测可信性 | 已实现严格样本/裁判契约、空选中集拒绝、独立裁判配置、生产模型冻结、有限调用journal与原子报告 | 定向回归、全部后端和CI预检；本轮未跑付费模型，不声称模型质量变好 |
| P1 本地资产底座 | 已实现共享结构检查、模型根/缓存根分离、精确revision、下载校验后激活、只读doctor和非LLM本地策略 | GPU/WSL/真实模型加载未验收；这不是完整推理环境安装完成 |
| P2 推理调度 | 待实现：独立推理进程、统一GPU准入、实时优先 | 不将线程等待取消当作GPU任务结束 |
| P3 pgvector/RAG | 待实施迁移：保留BGE作为对照，先不改模型/切块/阈值 | 本次仍使用原Milvus路径；不得据文档删除现有索引 |
| P4 录音复盘 | 待功能重审：长录音转写、对齐、角色核对、修订与回听 | 现有证据化复盘不退化成纯文本总结 |
| P5 面试内核/反馈 | 待实现目的与通道分离、能力证据/量表、新题练习 | 当前四阶段生产流程尚未替换，关键词雷达仍待重构 |
| P6 实时语音 | 待接入本地WebRTC、VAD/结束判断、ASR/TTS与打断 | 尚未实现；严格本地模式明确阻止现有在线edge-tts |
| P7 简历/JD/准备 | 待完成逐项重审和业务切片 | 保留事实来源、版本与不虚构经历的约束 |
| P8 其余功能/Copilot/记忆 | 待逐项收敛 | 27项审查范围不因某一个切片通过而缩减 |
| P9 交付验收 | 持续进行 | 最终源码SHA、CI、真实GPU/语音与质量成绩分别登记 |

本批代码职责与官方依据见 `docs/architecture/codebase.md`；模型复用与非破坏性诊断见
`docs/deployment/local-first.md`；模型评测入口与报告含义见 `evaluation/README.md`。
本轮结果必须绑定新提交，不继承上一轮1831项通过数字。旧阶段的“已完成”仅指当时范围。

## 当前工程收尾与状态优先级（2026-09-19）

本轮完成的是用户指定的两类工作：**现有已启用产品能力的统一消耗治理，以及现行业务实现/入口/协议的架构迁移**。
不是用新服务替换旧服务后永久双轨运行，也不是把后续九个未启动产品切片预写成完成。
第 3、6、10 节和本节为当前状态；下方带日期的旧批次及 Gate A 资产表均为历史取证。
它们中的旧路径、当时失败/跳过数字、`partial` 和“仅主模型”不是当前代码结论。

| 收尾项 | 当前实现与保护 | 必须绑定的验收 |
|---|---|---|
| 0052 迁移 | JSON 构造不经过冒号绑定；修正旧用户夹具；不清空已有余额/原请求 | `test_unified_usage_postgres.py`：全部五种旧状态、两用户两日、无调用用户、同原收据后续对账、禁止破坏性回滚 |
| 统一用量 | 所有当前生产类别共用账户锁/窗口/余额；调用次数和分离 token 维度必须自洽；不能用完成反馈改写尝试次数 | `test_usage/`；Pg 跨类别争抢额度、业务锁隔离、对账 CAS 和同调用身份多连接竞争 |
| 结算不明 | 供应商返回后本地 COMMIT 失败或响应丢失，保留原收据并返回专门的不可自动重试状态 | 同步/异步 × COMMIT 前失败/提交后丢响应；供应商只调用一次；已结算和仍预留分别保持 |
| 外层结算与降级 | HTTP 流、MCP 与云解析的成功结算不重入网络失败处理；搜索、解析选择、Planner、候选融合及重排不吞掉未确认结算/额度错误；普通读超时与本地格式失败保留正常降级 | `test_settlement_boundaries.py`：四入口 × COMMIT 前失败/已提交后丢响应、五个工具处理器、三类解析停止错误、完成但截断的解析结果；另有 Planner/候选/重排的 12 项停止回归，保留原 Web/Parser/检索降级对照 |
| 业务 owner | 116 个旧实现迁入相应 owner；运行树无 `app.services`；HTTP/Agent/Worker 使用现行共享实现 | 真实非空导入图、无环检查、禁止越层写入和实际共享业务调用表达式检查；原行为全量回归 |
| Shared schemas | Pydantic 的输入/输出分别生成 OpenAPI 3.1 快照；固定 openapi-typescript 生成 TypeScript；手工 UI 投影由方向性兼容检查保护 | Python 快照与全部本地引用一致；生成文件 `--check`；tsc 兼容及负对照；未知版本仍由运行时拒绝 |
| 空值和来源忠实 | 候选 `null` 不变成用户事实；仅全新手动表单建议本机时区，候选缺失时区保持空值 | 前端 nullable/时区回归；既有确认、更正、拒绝和版本冲突测试 |
| 真实执行门禁 | 维持实际 PostgreSQL/Redis/Celery SIGKILL、浏览器 HTTP 和完整 VS01-S01…S15 gate | 两个 Python 环境、前端、浏览器、schema/迁移检查必须以**最终提交**结果为准，不继承旧绿灯 |

首次修复提交 `838ea20a…` 已通过真实升级、`alembic check`、浏览器和 VS-01 门禁，但后端旧数据夹具遗漏必填字段而失败。
该结果不记作全绿。当前夹具与扩展场景已修正，完整最终 CI/JUnit 的具体 SHA、计数和产物以 PR #2 收尾记录绑定。
中断恢复时核实 `5f5b6518…` 的 CI `35425298819` 已成功，而 PR 描述尚停留在旧版。
随后新增适配器组合回归，确认部分外层会在结算失败后尝试第二次结算或将专门错误吞入降级。
本轮将成功结算移出传输异常处理，保留原收据和明确的不可自动重试状态；最终代码与完整
服务检查仍以 PR 中的新提交/JUnit 记录为准，不把之前的成功外推到本轮修改。

代码在既有分支交付，合并/生产迁移未获本任务要求，也未执行。

官方依据及可重现命令在 `docs/architecture/codebase.md`。TypeScript 生成器使用独立开发依赖锁：
openapi-typescript 7.13.0 的 peer dependency 是 TypeScript 5.x，因此工具固定 5.9.3；应用仍保持 6.0.3，
不用 `--force` 或 `--legacy-peer-deps` 绕过声明，也不把生成器加入产品运行时。

## 历史批次：2026-09-19 工程能力与现行架构迁移实现

本批次基于 `701957c6…`，针对用户要求先完成的工程实现及架构迁移；不扩大到
真实模型效果、生产容量或未来全部 Blueprint 功能。下方旧路径和“仅主模型”是
历史阶段记录，当前实现以顶部收尾节及 `docs/architecture/codebase.md` 为准。

| 范围 | 实施状态 | 验收入口 |
|---|---|---|
| 统一资源/费用账本 | 现有主模型账本扩展为 `usage/` 唯一 owner；内部模型、压缩、视觉、Embedding、重排、ASR/说话人分离/TTS、云解析、外部资源/MCP 调用均接入；不是再建一份余额 | `test_usage/`、`test_db/test_unified_usage_postgres.py` |
| 费用依据/未知结果 | 冻结精确费率；实测/估算/未定价/供应商证据分开；unknown 保守占用，missing owner 阻止调用；金额用整数微单位和 JSON 字符串 | 跨类别、价格变更、未知、空价格、调用入口 SDK 回归 |
| 操作员对账 | 只读用户API、分页历史、CAS/幂等更正 journal、默认 dry-run CLI；不伪造实时供应商账单、不向模型开放额度修改 | 对账竞争、重复请求、跨用户读取、超额和配置收紧测试 |
| 增量迁移 | 0052 保留旧身份/余额，独立 UsageAccount 外键树避免业务 User 锁与记账互等；禁止破坏性回退新记录 | 真实 Pg 旧数据 up/down/up、跨类别抢最后额度、持业务锁记账 |
| 现行模块负责人 | 移除通用 `services/` 运行树；按职业、会话、面试、资料、身份、语音、集成、记忆、观测、目录、outbox 唯一实现迁移；API/Tools/任务不另建业务写入 | 全部导入/脚本同步；原路由/任务名保留；完整回归 |
| 真正的架构门禁 | 修复原扫描根目录空跑问题；实际应用、包初始化及延迟导入都扫描；消除循环引用；禁止旧 owner 回流和运行时导入维护迁移 | `test_architecture/test_import_boundaries.py` |
| 文档与安装 | 现行文档路径、两份 env、费用页面、包内模型目录/上下文模板、评测与维护归属同步 | 打包资产断言、前端和安装检查 |

实现时完整本地结果为 1743 passed / 36 skipped（后续最后 Worker owner 提取另有
28 项通过），前端 221 项通过。真实 Pg/Celery/浏览器不能以本地跳过代替：本批次
最终结果必须绑定新提交和 CI/JUnit，记录在 PR #2，不继承701957旧绿灯。

明确保留的边界：配置未填写真实费率/供应商证据时不能说账单完整；第三方 edge-tts
不是 Azure 官方产品；MCP 是外部调用定额而非可窥探远端内部消费；OAuth/目录控制
面和宿主运行费用不是资源调用计费。独立评测 generator/judge 使用独立账本和密钥，
通过正式产品入口的评测/运维操作仍须明确用户归属。不会因本次迁移开启长期记忆
生产，也不会宣称完整学习效果或生产压力验收已经完成。


## 历史批次：2026-09-19 全面续作：面试一致性、RAG容量和真实验收

当前实施基线 `2f2dddfc44c62c606a7d7da5f9d0f489482cb890`；仍只修改
`refactor/product-runtime-convergence`，不合并 main。本节优先于下方历史批次的
“待执行”描述；最终执行结果绑定 PR #2 的具体提交与 CI，不继承旧版本绿灯。

| 范围 | 本批次代码与验收入口 | 不能由此推出 |
|---|---|---|
| 恢复原CI | 历史0045 fixture使用反射表而非0050 ORM；浏览器正确识别201且总是结束拦截请求 | 不关闭原有迁移、SQL和浏览器断言 |
| 模拟面试 | 0051代次、问题领取/发布/清理fence；模型等待无隐式事务；不可替换已保存回答；GET恢复和明确重试按钮 | 远端请求可撤销、无计费、质量正确 |
| 生成质量合同 | 完整回答不截断；完整输入容量守卫；字符串/阶段/布尔值严格校验；一次格式修复与未知响应不自动重发 | 字段合法就代表语义正确 |
| RAG容量 | 独立有界storage/search/embedding/reranker池；真实线程结束才释放额度；退出清理和prefork重建 | 全集群限流、强杀线程、已完成规模压测 |
| RAG失败可见性 | 超载、不完整、canonical不可用分别返回；Agent收到degraded；不从不可用推断不存在 | 全渠道均查全、已取得更高检索质量分数 |
| 模型配置权威 | 数据库/解密失败停止调用而非改变供应商；每次读取当前密文验证解密缓存；rotation CAS | 已发送的请求可撤销、所有缓存/供应商均实测 |
| 真进程/浏览器 | 保留原6项真实Celery杀进程组合，加入用户直接陈述的verifying/committed组合；真实Chromium启动文字面试、模拟模型故障、刷新、明确重试 | 真实模型、Gmail OAuth或学习效果验收 |
| VS-01场景门禁 | S09/S14登记真实Worker/入站收据/原请求恢复测试；CI运行完整fresh-JUnit gate，任何必需跳过都不能通过 | 全产品发布或所有后续切片完成 |

本地完整后端一次运行得到 **1678 passed / 30 skipped**（新增知识工具状态传播等
最后小项随后定向验证）；Pg、Redis/Celery和浏览器条件缺失的跳过不计入通过。前端一次
全量 **218 passed**，随后面试页定向 **12 passed**、TypeScript、lint通过。最终源码
全量与真实环境验收结果以PR中后续固定提交的CI/JUnit为准，本段是实现过程记录。

**当前仍不能称全产品发布完成。** `covered`表示已登记可执行覆盖；只有完整gate运行
成功才算VS-01确定性验收通过。真实语义质量、长期记忆生产、全平台货币账单、所有业务
重复路径退出、全依赖容量曲线，以及未来准备/练习/复盘/新题效果仍需独立证据。
没有修改金标和模型质量分数，也没有调用真实付费模型、外部消息或生产数据库。


## 历史批次：2026-09-19 中断续作：额度、原请求恢复与 Gmail 事实确认

状态：本节记录 `refactor/product-runtime-convergence` 在 `562c4b1b…` 基线后的
续作实现；不是另一套 Blueprint，也不是完整产品发布。此前章节的数字是对应
提交的历史证据。本节 CI 结果必须绑定后续实际提交，不能继承旧绿灯。

| 工作项 | 实现与边界 | 验收状态 |
|---|---|---|
| 主回答模型账户额度 | UTC 日级调用/逻辑 token 预留与结算，与 dispatch 同事务；跨会话/刷新/删除不重置；同调用不重复获准；unknown 保守持有 | 本地合同回归通过；真实 PostgreSQL 争抢最后额度和同调用双 worker 测试已加入，待本次 CI |
| 流与用量 | 整体 deadline、累计响应容量、显式关闭原生流；Anthropic 分阶段 usage 按字段累计且不重复加 cache；不明付费结果不盲重试 | 本地慢滴流、容量、未知结果、关闭、分段 usage 回归通过 |
| 手动邀请刷新恢复 | 精确命令先持久入站，再与共享 Operation/verification 一起提交；浏览器仅保存账户内 opaque key；刷新只读收据；取消先到也能阻止迟到原 POST | 后端合同与前端刷新/取消/丢响应回归通过；不声称已跑真实浏览器 E2E |
| Gmail 邀请旧路径切换 | invitation 不论置信度/旧 auto-apply scopes 均进入同一 Source/Candidate/fact_confirmation；缺失时间/时区保持未知；旧 review 卡转交而不直接写业务 | 高置信/缺失字段/重复观察/终态回读/跨用户/旧 mutator 拒绝回归通过；其他事件类型保持既有逻辑 |
| 审批精确绑定 | confirm 不接受缺字段/冲突候选；correct_and_confirm 必须完整；事实和 Opportunity/Interview 选择必须匹配保存的用户决议 | 防审批借用、只提交 decision、终态重播回归通过 |
| Pg 崩溃验收 | 独立进程在 verification 前或 COMMIT 后 `os._exit`，分别走 UI 原请求与 fixture 的真实 thin-tool 恢复；检查原子性、无重复和已核实收据 | 4 个杀进程组合 + 2 个并发案例 + 1 个增量迁移保真案例，尚待本次 CI；不等于全部 Celery worker 故障组合 |

本地本轮全量结果（加最后一项异常 usage 回归之前）：后端 **1613 passed /
18 skipped / 3 warnings**；前端 **62 文件 / 216 passed**；TypeScript、ESLint、
生产构建与 Ruff 通过。18 项跳过来自 PostgreSQL 环境限制，不能计入通过。
CI 设置 `REQUIRE_TEST_POSTGRES=1`，数据库不可用必须失败而不是变成跳过，并
保存 JUnit 结果供追溯。最后的固定提交及 CI 数字在 PR 验收记录中补充。

### 剩余门禁（仍不能自动合并或称全方案完成）

- 本次只实现 primary Chat/Agent 的账户额度，不是全平台货币预算；internal
  models、compaction、embedding/reranking、语音和外部 Tools 的全链成本与容量仍需
  统一准入/真实负载验证。Models 页面明确显示排除范围。
- VS01-S09 / S14 仍为 partial：杀进程案例只验证上述两个入口和共享事务边界；
  全部真实 worker lease/recovery、Gmail 运行中丢响应、供应商核实仍须运行。
- 全产品旧 owner/重复实现清理尚未全部完成；本轮切换的是 Gmail invitation
  auto-apply 及其 legacy review 写入口，不删除历史记录或其他非邀请事件功能。
- 真实模型质量基准、供应商原生返回与实际写入回读、浏览器端到端、完整
  准备→练习→复盘→新题效果验证仍未运行。没有付费调用或真实外部消息。
- 长期记忆生产保持原质量开关关闭，不用单元测试替代生产质量门禁。


## 2026-09-19 审查分支：运行合同与产品接入收敛

基线 `f0ad4a2a3fd078beeff93d7f724946a52dae2c00`；工作分支 `refactor/product-runtime-convergence`。
本轮没有替换 Blueprint，也不把下列工程修复等同于全部产品切片发布。

| 范围 | 已实施变化 | 验证与剩余边界 |
|---|---|---|
| 数据迁移 | `0047` 对齐新增 JSONB 字段和索引；保留历史 memory cursor / dreamed 元数据，不删除用户数据 | 新增旧数据 up/down/up 保真测试；真实 PostgreSQL 结果以本分支 CI 为准 |
| Tool 副作用 | started mutation 在 timeout / cancel / transport exception 后保留 `unknown`；原执行状态保留在结果，继续资源 fence 与 same-call replay | 合成远端提交后断连、取消、异常与新 call 阻断测试；已返回的明确 provider rejection 不误标 unknown；供应商内部吞掉的错误仍须逐连接器核验 |
| 工具输入 | 区分 wire cap、普通默认预算、可信 built-in 预算；长 JD 或 exact owned JD snapshot 共用 UI/Tool 验证 | 流式参数→解析→计划→执行回归；快照 owner/version 校验；不允许外部 MCP 声明自行抬高限制 |
| RAG | canonical hydration 强制 principal、chunk/doc/asset owner、来源和显式附件范围；保持索引 generation/live checks | 伪造索引 metadata 与混合 scope 回归；不把合成污染实验称为线上泄露 |
| 模拟面试 | 默认文字；语音失败由用户选择降级；Agent 预填只确认原设置，不另发 HTTP start；同路径 enter-live 能切换 | 共用 MockPreparationRequest 及领域 start；HTTP 与 Tool 不复制业务创建逻辑 |
| 产品体验 | 全局页面内 Copilot 重用 GeneralChatPage/ChatPanel；`/interviews` 使用 Shared Operation；Today 投影 pending confirmations 与真实活动；`/activity` 区分业务/运行/页面状态 | 手动确认、response-loss 重试、fact confirm/correct/reject、版本冲突、收据核验、路由保留等组件测试 |
| 基线回归 | MCP 2.0 snake_case / notification / MCPServer 适配；更新已退休 prompt 的测试；修复拼接后 token 预算边界及现有格式问题 | 不跳过旧回归、不关闭 lint、不以静态 manifest 文件存在代替运行验收 |

本轮隔离环境已执行后端全套 **1581 passed / 11 skipped**（包括本地无 PostgreSQL 的测试），前端 **61 files / 205 tests passed**，类型检查、lint、生产构建通过。
最后提交及 Python 3.11/3.13 + PostgreSQL 的验证以 PR 检查为准；本段数字不代表真实模型、浏览器端到端或生产供应商验收。

### 当时未关闭的发布条件（历史）

VS01-S09（真实 worker-kill / verifying recovery）和 VS01-S14（全部 adapter 的 commit-ambiguity recovery）仍为 partial，`release_ready` 保持 false。
旧 Gmail invitation auto-apply 路径尚未切换，不能把手动/Agent/fixture 的共享操作写成全部外部入口已迁移。
账户级持久成本预留/结算/限额、全依赖容量压测、所有旧 owner 路径退出、真实准备→练习→复盘→新题质量基准仍需实施或验收。
长期记忆生产门禁未开启；本轮不修改质量分数、不伪造真实模型/客户使用数据，也不宣称所有知识模块已实现。
手动邀请网络丢响应后的原请求保留目前限当前挂载表单；跨刷新待核实请求的可靠恢复仍需补齐，不能当作已完成的全客户端 exactly-once。

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
| Product decisions | PDR-01/PDR-02 保持批准语义；PDR-03 是未来外部日程支线，不扩展到本次 |
| Current phase | 工程实现、入口切换及旧实现退出已落地；最终按提交运行 Gate F，不以本地 skip 代替服务验证 |
| Business code | 共享 Operation / fact confirmation / 同 Turn 恢复 / UI 与 Agent 及 Gmail 候选入口使用同一业务规则 |
| Database/migration | 当前 head 为 0052，数据与用量身份保留；升级及一致性检查必须通过最终 CI |
| Tests/evaluation | VS01-S01…S15 均登记可执行绑定；完整门禁要求 fresh JUnit，缺失/失败/跳过不可通过 |
| Experience | 页面内 Copilot、Today 待确认、唯一 CareerProcess board、真实 Interview handoff、独立 Activity 投影 |
| Entry gate for coding | 已于 2026-08-26 通过 Gate A |
| Product release | 本任务只交付分支；真实供应商/模型效果、生产数据审计及部署另行验收，不由工程测试认证 |

### 3.1 Gate D/E 首轮历史实施证据（2026-08-26，不是当前状态）

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

本节的 `gated` 表示实现/目标 owner/入口切换已具备确定性回归，最终以当前提交 CI 验收；
不代表已经执行生产部署、回滚观察窗口或真实模型语义质量验收。迁移起点列保留历史位置。
本轮不把外部发布条目改成 `done`，也不将未来全部产品能力纳入当前范围。

### 6.1 Schema、Owner 与 Domain

| ID | Target owner | Requirement / target change | Migration baseline (historical) | Dependencies | Acceptance gate | Migration / deletion condition | Status |
|---|---|---|---|---|---|---|---|
| VS01-SCH-01 | Shared Contract Schemas | 为 Operation/Event/Interaction/Verification/Client Action 建立可生成、版本化 schema | Pydantic → OpenAPI → 固定生成 TS；UI 投影由编译一致性门禁保护 | DOC-02…05 approved | schema snapshots；Python/TS compatibility；unknown version tests | 手工重复类型退出或由生成一致性 gate 保护 | `gated` |
| VS01-DAT-01 | Source/Candidate owner | provider-neutral Invitation Source/Observation/Candidate，字段 Evidence、version、dedupe、lifecycle | GmailObservation/Snapshot/ReviewCard | SCH-01 | immutable/dedupe/provenance/reject/supersede tests | Gmail adapter 只做 provider ingress；不再拥有邀请业务确认 | `gated` |
| VS01-DAT-02 | Interview owner | Interview 能表达已确认 schedule、original time/timezone、Opportunity link 与 version | InterviewRecord + migration 0022 | Product Spec；SCH-01 | create/update/CAS/source tests | 不保留第二份可独立漂移的 schedule owner | `gated` |
| VS01-OP-01 | Shared Operation runtime | Operation envelope、idempotency/fingerprint、actor/owner/policy、typed result | 分散 service/API/tool semantics | SCH-01 | generic Operation Contract tests | UI/API/Tool 不再各自实现幂等与领域写入 | `gated` |
| VS01-OP-02 | Domain Kernel Operation | 实现 intake/register/confirm/reject/query/handoff Operations | career/gmail/interview services | DAT-01/02；OP-01 | PDR-02 原子性；forbidden effects；owner/CAS/idempotency | 旧 approval/apply 邀请写路径汇入或封闭 | `gated` |
| VS01-DOM-01 | Domain Event/Outbox | 在 confirm 事务产生 Domain Events 与 projection invalidation identities | ProcessEvent/outbox patterns | OP-02；EVT-01 | transaction/outbox/replay/dedupe tests | 不允许 API/Tool 在事务外拼事件 | `gated` |

### 6.2 Harness、Policy、Context 与 Verification

| ID | Target owner | Requirement / target change | Migration baseline (historical) | Dependencies | Acceptance gate | Migration / deletion condition | Status |
|---|---|---|---|---|---|---|---|
| VS01-INT-01 | Interaction Runtime | 新增 `fact_confirmation@1` typed request/resolution 与 version migration | AgentInteraction + interaction_service | SCH-01；DAT-01 | one pending/Turn；CAS；confirm/correct/reject；ordinary-input no-resolve | Gmail review 与 Chat Interaction 不再形成两套用户确认协议 | `gated` |
| VS01-TURN-01 | Turn Runtime | resolution 记录 + same-Turn resume；decision 与业务执行分离 | turn_executor、PendingSubmission、ConversationTurn | INT-01；OP-02 | worker kill、disconnect、duplicate resolution、interrupt tests | 保留现有耐久核心，删除专用绕行恢复 | `gated` |
| VS01-POL-01 | Permission Runtime | 按 Operation effect/argument/resource/version 做 execution-time recheck | tool_policy | OP-01 | UI/Agent/Automation parity；hard deny；unknown fail-closed | Tool-only隐藏 policy traits 退出 | `gated` |
| VS01-EVT-01 | Event Runtime | 统一 Domain/Harness/Experience envelope、schema、cursor 和 replay | harness_events、SSE wire | SCH-01 | ordering、replay、version、reconnect tests | 前端不再靠字段猜事件；旧 event mapper 退出 | `gated` |
| VS01-CTX-01 | Context Compiler | VS-01 typed Package、authority/source manifest、不可压缩字段和最小 scope | context_assembly_pipeline、compactor、source acquisition | DAT-01；INT-01；OP-01 | injection、stale state、compact/reconnect、scope tests | 邀请 prompt 拼接路径汇入 Compiler | `gated` |
| VS01-VER-01 | Verification Runtime | durable-reference VerificationResult；local read-back；unknown/reconciliation | idempotency/audit/outbox patterns | OP-02；DOM-01；EVT-01 | postconditions、ambiguity、retry、no false success tests | service return/文案不再独立宣称完成 | `gated` |
| VS01-AGT-01 | Agent Adapter | 薄 Tool Adapter + 首个 Skill/recipe，调用 Shared Operations | agent loop、turn tool catalog、career/gmail tools | OP-02；CTX-01；POL-01；VER-01 | correct operation selection；no macro side effects；truthful final answer | 旧 career tool 中邀请写逻辑删除或改为 adapter | `gated` |

### 6.3 Experience 与 Automation

| ID | Target owner | Requirement / target change | Migration baseline (historical) | Dependencies | Acceptance gate | Migration / deletion condition | Status |
|---|---|---|---|---|---|---|---|
| VS01-UI-01 | Today Projection | “待我确认”读取真实 Interaction；动态读取真实 events；删除 seed/fallback | TodayPage、InteractionCard | INT-01；EVT-01 | empty account、CAS/multi-client、four-category tests | `SEED_TASKS`、fake companies、local confirm 删除 | `gated` |
| VS01-UI-02 | Career Projection | Opportunity timeline 读取 confirmed Interview/ProcessEvent，typed deep link | CareerPage + CareerProcessPage | OP-02；DOM-01 | same object/version；no duplicate business rule | 新浅层/旧深层双 board 收敛到一个 owner | `gated` |
| VS01-UI-03 | Interview Projection | 安排详情、Evidence、Opportunity 与 preparation entry | InterviewHubPage + existing interview pages | DAT-02；OP-02 | confirmed-only display；source/view tests | marketing shell 不再作为数据页；prompt query handoff 退出 | `gated` |
| VS01-UI-04 | Activity Projection | Turn/Interaction/Operation/Verification 状态摘要 | PersistentTasks/Activity alias | EVT-01；VER-01 | waiting/verifying/terminal/reconnect tests | 活动中心不复制任务状态 | `gated` |
| VS01-UI-05 | Copilot Experience | 当前 object context、Interaction、verified result 与 typed recovery | ChatPanel/useChatStream | EVT-01；CTX-01；AGT-01 | truthful state copy；no query-string prompt loss | 页面私有 chat hooks 逐步变共享边界 | `gated` |
| VS01-CA-01 | Client Action Runtime | 通用 `interview.preparation.open@1`，持久化、affinity、takeover、ack | mock client action service/bridge | SCH-01；DAT-02；EVT-01 | idempotent delivery；ack/fail；Domain independence | Mock-specific protocol 变 adapter，通用 runtime 单 owner | `gated` |
| VS01-AUTO-01 | Observation Adapter | fixture/manual ingress → candidate → fact confirmation；第一版 no auto-apply | Gmail observation sync/service/tool | DAT-01；INT-01；TURN-01 | dedupe、retraction、no canonical write before confirmation | Gmail-specific apply path 不再处理目标邀请语义 | `gated` |

### 6.4 Evaluation、Migration 与 Cutover

| ID | Target owner | Requirement / target change | Dependencies | Acceptance gate | Exit condition | Status |
|---|---|---|---|---|---|---|
| VS01-EVAL-01 | Career OS Evaluation | 新 manifest 登记 VS01-S01…S15，绑定 deterministic tests 与 scenario runner | 所有实现工作项 | 所有场景通过；无旧蓝图语义替代 | 新场景成为 VS-01 发布门禁 | `gated` |
| VS01-MIG-01 | Data Migration | 新/扩展 schema、backfill、downgrade、旧记录隔离和一致性扫描 | DAT-01/02；OP-02 | Alembic up/down；fixture；owner/source consistency | 所有活动用户数据可由新 owner 读取或明确 quarantine | `gated` |
| VS01-CUT-01 | Entry Cutover | UI/Agent/Automation 三入口逐一切到 Shared Operations | UI/AGT/AUTO；EVAL | shadow/read compare；write owner 单一；feature gate | 无旧独立邀请写入流量 | `gated` |
| VS01-DEL-01 | Legacy Exit | 删除 seed、mock-only branching、重复邀请 apply/write 路径与死代码 | CUT-01 | import/use scan；full test/eval；rollback window | 旧 owner 不再可达，文档同步 | `gated` |
| VS01-REL-01 | Slice Release | 生产发布另行确认；本任务保持 Draft 分支 | EVAL/MIG/CUT/DEL | deterministic + integration + experience + recovery gates | VS-01 标记 `done` | `planned` |

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

生产应用迁移前由部署负责人用只读审计确认；本轮没有访问生产资料。
实现回归使用隔离的多用户/多日期/多状态旧数据，不能冒称已经审计全部真实用户：

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
| EXP-01 | Copilot 常驻/抽屉/工作区具体形态 | 否 | 当前采用全局页面内面板并复用原聊天工作区；typed object handoff 与状态一致已有测试 |

### 10.1 已实现的原工程阻塞与验收入口

| 原阻塞 | 当前对应 |
|---|---|
| VS01-S09 Worker kill | 三类邀请来源、verifying/committed 等断点的实际 Celery SIGKILL/恢复；固定身份不重新生成写入参数 |
| VS01-S14 commit ambiguity | 持久入站命令、取消墓碑、原收据恢复；实际浏览器 COMMIT 后丢响应；未知外部结果保守保护 |
| PostgreSQL migration | 0001→0052、ORM check、旧状态余额保真与安全回退；CI REQUIRE_TEST_POSTGRES=1，不可因服务不可用跳过 |
| Cutover / legacy exit | Gmail 邀请转为候选和事实确认；不再独立 auto-apply；Career 只有现行 board；整个旧 services 实现树退出 |
| 协议、事件与上下文 | 权威 schemas 输入/输出快照及生成/兼容门禁；Domain/Harness/Experience 明确分类，已有 cursor/replay/reconnect 行为回归 |

以上入口仍须在每次最终变更上实际重跑；最新结果以 PR #2 的固定提交 CI/JUnit 为准。
本文件不会把有失败或跳过的回归版本称为验收通过。

### 10.2 两类实现工作之外保留的发布条件

真实模型选择/反馈/学习效果、真实 Milvus/Reranker 与供应商写入回读、全依赖长期压力/容量曲线、
生产数据只读审计/备份恢复及运维费率配置仍需部署和质量验收。长期记忆生产门禁保持关闭。
这些不由 schema 合法、目录清理或确定性测试替代；不要求为了关闭清单而调用真实账户、编造费率或合并 main。

## 11. 变更记录

| 日期 | 变更 |
|---|---|
| 2026-08-26 | 创建新 Career Agent OS 实施账本；登记 PDR-01/PDR-02 与 VS-01 文档冻结、当前资产、实施批次和门禁；未修改业务代码。 |
| 2026-08-26 | 用户批准 Gate A；四份 Contract 与 VS-01 Spec 升为 1.0.0，进入 Gate B 实施。 |
| 2026-08-26 | Gate B/C 主干落地：确定 InterviewRecord 为 schedule 物理 owner，OperationVerification 为独立耐久记录；新增 provider-neutral invitation owners、Shared Operations、Domain Events 与 migration 0043。 |
| 2026-08-26 | Gate D/E 首轮落地：fact confirmation、Context Package、Agent/UI/fixture adapters、通用 preparation Client Action、Today/Interview/Activity/Copilot handoff；删除 Today seed/fallback 与求职卡片虚构未来阶段。 |
| 2026-08-26 | 创建新蓝图 VS01-S01…S15 evaluation manifest；13 covered、S09/S14 partial，因此 Gate F 与 Slice Release 有意保持未通过。 |

| 2026-09-19 | 统一全部当前消耗类别与业务 owner 迁移；修复0052、结算提交不明和真实非空架构扫描；补输入/输出生成协议门禁与多状态旧数据回归。以最终固定提交CI验收，不自动合并或部署。 |
