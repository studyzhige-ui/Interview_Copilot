# Web / Docker 验收记录（2026-10-12）

范围：当前工作树的 Interview Copilot 主线。不制作 Windows 安装包，不上传模型权重，不发布 GitHub release。模型由部署者下载。验收使用独立的 PostgreSQL、Redis、文件卷及合成资料，不使用业务数据库。

检查点：`checkpoint/before-web-release-acceptance-20261011`。收尾优化前另保存完整 Git 文件检查点：`D:\Projects\Python\_checkpoints\Interview_Copilot-before-final-simplification-20261012-163108.zip`（包含 tracked／nonignored untracked 文件、HEAD 和 diff；未将本地密钥与模型纳入源码归档）。检查点之后的修改尚未发布。

后续事务一致性修复、文档校正及最新测试结果见 [10 月 13 日工程收尾记录](engineering-closure-2026-10-13.md)。以下保留本次验收当时的范围。

## 本轮发现与修复

1. **真实简历解析失败**：抽取端手写字段说明与档案的 Pydantic 契约不一致，DeepSeek 将 `seniority` 返回为字符串、将 `salary_currency` 返回为空字符串，保存时被拒绝。改为从现有数据模型生成 JSON Schema，保留严格保存校验、一次抽取和原文分段。原失败简历及另一份具有明确求职目标的合成简历均重新解析成功。
2. **容器缺少本地推理入口**：镜像未打包现有 broker 配置／启动脚本，Compose 也没有 broker 服务。补入原有脚本、容器目录解析和 `local` 部署 profile；Unix socket 使用 Linux Docker volume，健康检查使用与 broker 相同的应用 UID。没有增加第二套推理实现。隔离栈运行、BGE 入库／检索／删除和 WhisperX 完整录音回归已执行。
3. **邮件配置失效**：原 SMTP 连接能建立 TLS，但认证阶段断开。用户更新账号后，应用发出注册与重置邮件；注册、重置、旧令牌失效和新密码登录通过。用户已确认两封邮件到达。凭据仅存在被 Git 忽略的环境文件。
4. **联网构建受网络限制**：`raw.githubusercontent.com` 被解析到 Fake-IP 地址，NLTK 的下载安全检查拒绝访问。未关闭检查。使用本机既有分词资源进行独立的离线镜像验收；不能将它记作从零联网构建通过。

5. **BGE 完整模型被误判不完整**：SentenceTransformer 的 Normalize 是不读写文件的无状态模块。资源检查器此前要求它也有目录。现在按真实模块契约检查，仍验证路径归属、Pooling 等有状态模块的文件；没有跳过所有资源检查。
6. **重建后登录出现 502**：nginx 固定解析旧 backend 地址；容器 IP 变化后代理失效。改为 Docker DNS 动态解析。重新构建前端、重建 API 后，登录及页面验收通过。
7. **本地异常被误报为远端调用不确定**：用量层对本地／远端执行使用相同异常包装，掩盖本地根因。保留本地异常对象，不改变未确认用量的预留结算规则；转写结果组装移到模型计量范围外。
8. **长录音说话人身份与片段归属错误**：固定锚点及人工余弦阈值无法可靠关联各窗声纹。删除旧 `speaker_identity.py`，通过既有 Pyannote broker 收集窗口观察、全录音聚类、逐窗重建时间轨；没有恢复 Qwen。上下文仍有界，ASR 只执行一遍。
9. **问答提取设计错误**：旧三段 LLM 链只准返回 ID，程序按声学角色拼正文，并用自己的分类计算覆盖率。它可在错误归属下仍报告 100%。现在一次完整上下文语义提取 question／answer 与回听引用，删除角色修补、utterance／episode 中间层、隐藏词、标点补丁和循环论证式指标；原始转写不改写。声学标签是提示，不是语义判决。来源存在／有序、音频完整性、权限和模型协议校验仍保留。
10. **追问关系在存取时丢失**：提取的 parent_index 没有转换成 parent_qa_id，恢复又将追问写死为 false。落库解析实际父题、保存深度，恢复从持久化关系还原；有独立回归用例。

## 已有执行证据

| 范围 | 结果与边界 |
| --- | --- |
| 干净轻量镜像、迁移、Web 服务 | 构建成功；独立 PostgreSQL、Redis、API、四类 worker、Beat 和前端启动成功 |
| 后端契约 | 81 项通过、3 项按外部配置跳过；另运行 2 项真实 PostgreSQL/pgvector 测试通过，覆盖迁移、HNSW／精确检索的归属和删除约束 |
| 对象存储 | 独立 S3 兼容服务上的真实 HTTP 测试通过：不可覆盖写入、范围读取、删除；不是实际 AWS 账户验收 |
| 前端 | 类型检查、lint、生产构建、13 项测试通过；最终 Web／浏览器 10 项通过、1 项真实模型用例未启用（此前有限真实模型验收另有证据）；Chromium 登录及 19 个页面导航无脚本异常、无服务端 5xx；不等于每个页面的全部交互已覆盖 |
| 账号 | 注册邮件、重置邮件、注册、登录、重置、刷新令牌轮换、退出失效、旧令牌拒绝通过 |
| 简历与档案 | 真实 DeepSeek 解析、原文全覆盖分段、候选生成、确认、版本冲突拒绝通过 |
| 聊天与 Agent | 真实 DeepSeek 回答持久化；Agent 事件确认实际调用 `read_resume`；已完成事件可重放，取消返回 `cancelled` 终态 |
| 模拟面试 | 真实模型首问、提交一轮回答、继续提问、提前结束、后台复盘达到 `review_ready`；不是完整 15 题质量评估 |
| 持续任务 | 创建、一次手动触发、执行完成、暂停通过；没有进行长期定时稳定性测试 |
| 求职过程 | 岗位与事件写入、待办完成、基于已上传证据的 Offer 录入／幂等读取、邀请确认／重放／冲突及 handoff 读取通过 |
| 材料、文件、Skills | 材料不可变版本与归档、上传确认、完整／范围下载、Skill 创建／停用／删除通过 |
| 用量 | 真实模型调用生成已结算的资源用量收据；存在 `unpriced` 条目，不承诺供应商账单金额准确 |
| BGE RAG | 实际模型入库成功，查询命中合成标记 MAPLE-619，删除后不可检索；真实 PG 的 HNSW／精确查询约束已分别验证 |
| MCP | 两个真实 stdio server 子进程完成 discovery／call，验证 schema、租户隔离和环境变量过滤；不代表远程 OAuth MCP 已验证 |
| 原 121.617375 秒录音 | 真实 WhisperX／Community-1：393 个实质字符，无插入／删除，1 处同音替换；边界关键句、时间范围和单说话人连续性通过。13 次 broker 操作完成，无 rejected／unknown／pending，耗时约 160 秒 |
| 双人 122.5687 秒录音 | 原音频完成转写及声学全局重建，重新提取走当前 DeepSeek 主线并持久化报告。两轮问题、第二轮答案与参考全文去标点后一致；第一轮答案仅有“元→原”一处差异，无漏句／串话。严格术语断言失败，未改断言或重复抽取直到碰巧通过 |
| 复盘 UI | Chromium 实看新版 QA：整理说明、疑点、完整正文、来源详情均正常；无 JS 异常。旧覆盖率和逐字拼接宣称已移除 |

## 剩余限制／外部条件

- 语义提取没有达到逐字全部正确：真实双人录音中“元数据”仍为“原数据”。LLM 已纠正另一处“向梁”为“向量”，但不能据此承诺自动纠正所有识别错误。未添加样本专用词替换或提示补丁。
- 真实 Gmail／Canva／Notion OAuth：验收环境未配置 OAuth 应用及用户连接。SMTP 收发成功不等于 Gmail Connector 成功。
- 实时语音传输和真实麦克风／扬声器未完成端到端验收；当前实时媒体配置关闭。上传文件链路通过不能替代实时语音验收。
- 超出内部模型上下文／输出容量的录音提取会失败，不静默截断；尚未进行数小时、嘈杂重叠多人录音的质量评估。
- 修复网络 DNS 配置后，从零联网构建仍需重新验证。

## 复现入口

`backend/tests/release/` 仅在显式提供 `IC_ACCEPTANCE_BASE_URL`、`IC_ACCEPTANCE_USERNAME`、`IC_ACCEPTANCE_PASSWORD` 时连接真实测试环境。`IC_ACCEPTANCE_OPENAPI` 可指定从 API 容器导出的 OpenAPI 文件（前端 nginx 不公开根路径 `/openapi.json`）。

`IC_RUN_BROWSER=1` 启用浏览器验收；`IC_ACCEPTANCE_LIVE_MODELS=1` 启用会产生模型用量的简历回归。只对可丢弃测试账号运行，不能指向有真实资料的账户。模型权重、凭据、运行日志、截图及合成测试数据均不提交 Git。

本机证据位于被忽略的 `data/release-acceptance/` 和 `output/playwright/release/`。关键证据：`final-contracts.log`、`final-web-browser.log`、`final-complete-recording.log`、`semantic-interview-result.json` 以及 `output/playwright/release/final-qa.png`。本记录不宣称所有外部集成或所有语音样本均已正确。
