# 发布前全项目审计与收尾（2026-10-15）

后续最高兼容稳定版本升级、运行环境更新与可选评测环境的安全扫描见 [依赖升级验收](dependency-upgrade-2026-10-15.md)。本文下列版本与测试数量保留为最初审计记录。按用户澄清，兼容性和功能正常优先；无法兼容消除的公告继续登记，不以公告清零作为依赖升级验收条件。

## 发布判断

当前适合进入受控候选版验收，暂不建议直接对公众发布“全部功能均已验收”的版本。本轮修复了实际复现的业务断点、队列竞态、缓存失效遗漏和依赖问题；完整在线构建和外部能力验收仍需完成。模型依赖剩余公告按实际入口限制登记，不因无法清零否定已通过验证的最高兼容版本组合。

本轮没有推送、创建线上发布或生成 Windows 安装包。原工作树包含大量此前改动，开始前已保存 `refs/checkpoints/release-readiness-20261015`（`e17537c0996bf73b7d0e02b03c9dbf49634135a0`）。审查使用临时 Git index 同时纳入既有未跟踪源码，没有覆盖用户暂存区。

结果针对当前本地工作树；最终收尾快照保存为 `refs/checkpoints/release-readiness-verified-20261015`，尚未作为正式版本发布。

## 已修复的问题

| 问题与触发条件 | 最终行为与实现位置 |
| --- | --- |
| 快速 worker 在任务编号落库前启动，SourceSnapshot 随后变化，附件结果被当作过期丢弃，页面永久“处理中” | `document_commands.enqueue_ingestion` 先提交任务编号再发布；知识库创建、附件创建、附件重试和后台恢复共用。真实 PostgreSQL 的第二连接验证提交可见性；真实 HTTP 附件流程重新通过 |
| 后台恢复音频附件时直接 `.delay()`，绕过用途对应的队列 | 恢复也经统一派发边界，音频进入 transcription、文档进入 pipeline |
| 面试保存响应丢失后，表单无法辨认是否已保存，刷新可能重新创建安排 | 按账号与表单对象保存不含正文的本地恢复 key；使用已有服务端 receipt/resume/cancel；未收到的请求先建立取消墓碑，再允许新输入。刷新或重新打开浏览器后可继续核对；恢复要求同一账号会话身份 |
| 首页待办跳到旧统计页，第四项起的确认请求只能去历史记录寻找 | 直接跳转 `/career-calendar?view=actions#action-ID`；待确认列表可展开全部 |
| 已确认 Offer 回复期限处于 suggested 状态，被首页排除 | 日程与首页共享“已计划行动或确认的 Offer 期限”筛选，不把其他建议冒充计划 |
| 日程内部跳转改变 query 参数后仍留在日历视图 | 视图直接由 URL 参数驱动，支持内部链接、刷新和前进/后退 |
| 归档或合并后首页岗位数量漂移，合并来源上的面试可能丢失 | 首页与看板共享可见岗位查询；面试链接解析到 canonical opportunity，隐藏主岗位后首页也隐藏相关面试 |
| Agent、Gmail、复盘关联及部分表单写入后，新旧 query key 没有一起失效 | 共用 `invalidateCareerQueries`，覆盖旧关联选择器、Offer、材料、岗位、面试与确认请求。流结束或断连也重新读取业务事实；可见的岗位、日程投影每 30 秒刷新 |
| CI 格式/lint 门槛已经不通过；数据库测试仍断言历史迁移号 | 清理一个无用 import，并按既有 Ruff 配置格式化相关文件；迁移断言读取实际 Alembic head，当前为 0078 |
| 发布验收脚本仅支持旧本地登录，实际安装使用 Supabase 模式 | HTTP 与真实浏览器按 `/auth/config` 选择允许的登录方式；Supabase 模式验证独立本地解锁、不可刷新、退出失效与重新解锁，不注入浏览器 token，也不伪称已验证云端登录 |
| 文档库安全升级后，RapidOCR 3.10 删除语言注册表，旧资源包也缺少新版 OCR 权重 | 固定 Docling 2.132.0 + RapidOCR 3.9.2；同步隔离解释器版本门槛、独立 requirements 与初始化脚本，显式预取中文 PP-OCRv6 资源；真实隔离 CPU PDF 解析通过 |

队列发布与数据库提交仍不是同一事务。若进程在提交后、发布前退出，现有 stale sweeper 会重新派发；没有宣称即时或恰好一次外部执行。恢复保留源版本栅栏，不通过删除 task_id 的版本校验来掩盖竞态。

## 删除与保留

前端 TypeScript 引用分析覆盖 182 个产品模块，后端静态分析覆盖 517 个 Python 模块，并人工核对动态入口。

- 删除旧前端的 8 个无调用 API 包装：材料单条读取/关系列表/投递列表/旧版本写入/旧投递写入、旧岗位创建/事件列表、旧简历删除；同时删除对应孤立输入/投递类型与无用评分版本常量。材料发布和投递现在使用当前工作区命令，归档/恢复仍有入口。
- 保留后端 `/resumes`、原始 process API 和历史引用字段：既有工具、关联选择器、合并撤回及不可变历史仍需要它们，不能因旧页面被替换就删除公共合同或用户数据。
- 保留 `shared-protocol-compatibility.ts`：它由 tsc 编译执行类型约束，不需要运行时 import；保留默认导出的 `PdfPreview`，它由 lazy import 进入。
- 保留五个静态图的候选文件：`model_probe_child.py`、`schema_policy.py`、`local_inference/child.py`、`local_inference/pyannote_audio.py`、`docling_worker.py`。已查明分别由子进程、Alembic 或动态模型入口调用。
- 没有证据证明其他 Python 模块是死代码。本轮不以删除文件数量充当清理结果。

现行架构与页面责任已更新到 [codebase.md](../architecture/codebase.md)。HTTP/SSE 保持薄适配；业务对象仍由原 application service 所有，工作区负责组合查询；Worker 使用相同业务服务。没有新增第二套岗位、简历或面试状态机。

## 依赖审计

| 范围 | 当前结果 |
| --- | --- |
| frontend | npm audit 0；Axios 1.20.0、Vitest 4.1.11，以及受影响的间接依赖已更新 |
| desktop | npm audit 0；修复缓存依赖，并把 electron-builder 的旧下载器所用 global-agent 限定为 4.1.3；验证下载器代理初始化，桌面 4 项测试通过 |
| 协议生成工具 | npm audit 0 |
| 实际 Linux 运行环境 | pip-audit 从 44 条降至 10 条，剩余 7 个唯一公告，涉及 Transformers 4.57.6 与 NLTK 3.10.3；PyJWT 2.15.0、pypdf 6.19.0 和 Docling 升级已验证 |

模型依赖尚未清零。当前模型入口只接受操作员配置的本地资源，设置 `local_files_only=True`、`trust_remote_code=False`，没有向 HTTP 用户提供 Trainer、checkpoint conversion、模型持久化路径或 custom generation 入口。这降低部分已披露路径的可达性，是基于调用链的判断，不是漏洞已修复或完整攻击验证结论。

Transformers 的大版本升级牵涉 WhisperX/Hugging Face Hub 的兼容约束，不能强行更换并声称语音质量不受影响。后续已验证最高兼容稳定版本组合，具体版本、功能证据与剩余公告见依赖升级验收文档。没有通过 ignore 或改审计规则隐藏告警。公告示例：[NLTK 模型路径](https://github.com/advisories/GHSA-8mgp-746c-j5xp)、[Transformers 自定义生成代码](https://github.com/advisories/GHSA-x9r9-c232-4q39)、[Transformers 模板持久化](https://github.com/advisories/GHSA-xrqw-3rrv-vx5w)。

## 当前执行证据

各行有重叠，不能相加为独立测试总数。

| 检查 | 结果与边界 |
| --- | --- |
| 后端主回归 | 177 passed、20 skipped；Windows 环境，浏览器、真实模型与真实服务分别检查 |
| 真 PostgreSQL/pgvector | 8 passed；从零迁移、schema check、并发合同以及快速 worker 提交可见性；数据库均为自动创建并删除的临时库 |
| Linux 专项 | 29 passed；备份对象、mock audio、录音 QA 与恢复合同，不能替代实际麦克风或长录音质量验收 |
| 真实 HTTP + Chromium | 17 passed、3 skipped；20 个页面导航、设置刷新持久化、账号退出、材料不可变版本、岗位/Offer/行动、附件上传/解析/范围下载、Skills、持续任务等；真实本地 BGE 入库、检索命中及删除后不可检索也通过。三项远程回答模型（模拟面试、简历解析、聊天）未启用 |
| 独立生产 auth shell | 1 passed；本地表单校验及页面脚本错误检查 |
| 最后浏览器专项 | 3 passed；在真实服务端提交后主动丢弃响应，刷新页面再核对收据，最终只有一份面试记录；核对成功后进入该岗位的面试列表 |
| 前端 | 35 passed；lint、TypeScript、生产构建通过；恢复、断连后业务刷新、Offer 期限与确认入口均有新增回归 |
| 桌面 | 4 passed；未生成或验收最终 Windows 安装包 |
| 协议、Python 与迁移检查 | Pydantic snapshot、两份 TypeScript 生成合同、compileall、全量 Ruff 与 `alembic check` 通过 |
| 真实 Docling | 新版本 + 已预取 OCR 资源，隔离 CPU 子进程解析 PDF 成功并保留合成标记；不是复杂扫描件质量评估 |
| 备份恢复 | 实际 pg_dump/pg_restore 到新临时数据库；7 张代表性业务表行数一致；38 个对象恢复后哈希全部一致。该环境 retrieval_entries 为 0，不能据此声称验证了非空向量备份数据 |
| 数据一致性巡检 | 当前隔离测试环境 0 项问题；不是用户生产数据审计 |
| 运行源码 | API、四类 worker、Beat、local-inference 中各 517 个 Python 文件，与工作区逐文件 SHA-256 一致 |

PDF 渲染器仍为按需加载的约 1.20 MB chunk（gzip 444 KB），中文字体约 10.6 MB。生产构建保留体积警告，没有通过抬高阈值隐藏；首次 PDF 导出成本尚未进行设备覆盖测试。

截图实看了当前“今天”页面；浏览器导航及面试收据恢复截图保留在 `output/playwright/release/`。前端容器的 74 个产物文件与当前生产 dist 哈希一致。自动导航通过不代表每个页面的每项交互都已视觉或行为验收。

## 仍需满足的发行门槛

1. 模型依赖已按最高兼容稳定版本升级并验证；保留剩余公告登记与本地资源入口限制，不扩大为任意模型代码或路径执行，不将清零列为本次依赖升级阻塞项。
2. 在正常构建网络复验完整镜像。标准 Dockerfile 的 NLTK 下载在当前环境被 pathsec 拦截，解析到保留网段 `198.18.1.244`；后续 Docker Registry 鉴权也出现 DNS/连接失败。未关闭安全校验。当前 QA 镜像复用了已验证的依赖、tokenizer 与 nginx 资源，再安装升级包、复制当前源码与本地生产构建的前端；`pip check` 通过，但不等于从零在线构建通过。
3. 在实际发行环境复验在线 Supabase 登录/注册/找回密码及邮件送达。本次实际配置为 `custom_smtp`，不能因已配置就认为已送达。本轮浏览器使用新建的可丢弃、本地解锁测试账号。
4. 仅对要启用的外部能力补验真实 Gmail/远程 OAuth/MCP 等连接与授权流程；本轮不代发邮件或替用户建立连接。
5. 实时媒体当前关闭；真实麦克风/扬声器、完整语音质量、长时间定时任务稳定性和最终 Windows 安装包均不在本轮已验证声明内。

已有历史真实模型/录音证据见 [2026-10-12 验收记录](web-release-acceptance-2026-10-12.md)，只代表该记录的源码、模型和环境，不算作本轮重跑。

证据位于被 Git 忽略的 `data/release-readiness-20261015/`：`backend-complete.xml`、`pg-verified.log`、`acceptance.xml`、`linux-runtime.xml`、`browser-shell.xml`、`parser-verified.log`、`backup-drill.json`、三份 npm audit JSON、`backend-audit-verified.json`、`runtime-source-parity.json` 及构建日志。临时账号凭据在验收结束后删除，新增测试账号停用；不把凭据、模型权重、数据库备份或截图提交到源码。
