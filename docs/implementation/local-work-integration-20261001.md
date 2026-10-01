# 本地成果迁入远端运行架构（2026-10-01）

## 基线与恢复

- 原本地 main：`f9bf80ae70e13b235da487ba7ca224a7b85bdfeb`。
- 完整本地检查点：`codex/checkpoint-local-20261001`，`a364152ac962df3e67baa9b807f5d8727139d915`。
- 远端基线：`integration/local-runtime-supabase-auth`，`34c4de6d3cd85262c7ef61bf98903a918519aac5`。
- 独立迁入分支：`codex/integrate-local-work-20261001`。

检查点用临时 Git index 保存全部非忽略文件（333 个变更文件），核对其内容与原工作区一致；原 main、index 和工作区保留。`.env`、模型权重、下载语料、缓存和业务数据库仍在原位置，不包含在代码检查点中。本次没有操作业务数据或发布远端分支。

## 主线范围

产品 RAG 主线模型保持 `BAAI/bge-m3` 和 `BAAI/bge-reranker-v2-m3`。本地检查点包含 BGE/Qwen 对比实验；此前把该实验的 Qwen 检索适配迁入产品运行模块，扩大了迁入范围。本次纠正撤回新增的 Qwen RAG 模块及其 config/child/代理绑定改动，独立评测和历史报告仍留档。`compare_local_models.py` 只接受 BGE profile。

## 设计层差异与处理

原本地工作区混合了已发布 main 的安全加固与独有的上下文、检索和评测工作。直接合并会同时恢复旧 service 路径、旧 outbox 任务名和旧检索表，造成模块所有权与迁移合同冲突。此次先以 `812bf76` 区分已发布的加固，再按远端的实际模块路径迁入独有行为。

| 模块 | 迁入结果 |
| --- | --- |
| 上下文 | 聚合工具结果预算、可恢复跨 Turn 引用、前缀摘要与近期完整交互、检查点幂等恢复迁入共享上下文层；Chat 服务调用转到 `conversation/application`。 |
| 模型 | 保持远端 BGE 的 broker 配置、推理、指令和绑定合同。本次新增的 Qwen 检索运行适配已撤回；实验保存在检查点和独立评测中。 |
| 中文词法检索 | 本地 jieba 0.42.1 search-mode 合同接入 `rag/index/lexical.py`，使用远端统一检索表、租户和可见性过滤。默认保留远端 CJK 分析器，选择 jieba 会生成独立代次。 |
| 评测 | MTRAG、职业资料/专业资料候选集、模型比较工具与历史报告保存；模型比较入口转到 `hybrid_index`，评测 lint/格式对齐远端 CI。独立实验模型适配器保留固定实验语义。 |
| 已发布加固、前端 | 原本地认证、内存生命周期、取消、outbox 租约和前端交互修复已经纳入远端历史，不重复恢复旧接口。 |
| 本地原检索实现与迁移 | 本地 `rag_vec_*` 表/HNSW 架构、`knowledge_index_*` 任务名、0047/0048 和 0049→0048 迁移连接保留在检查点；现分支采用远端的规范检索代次、`retrieval_*` 任务和已发布迁移历史。不能将旧迁移粘入当前链。 |

## 可审查提交与文件审计

- `9d7adbb`：上下文预算、可恢复结果引用和摘要/近期窗口。
- `2e78fb5`：jieba 可选合同；此提交中 Qwen 检索运行适配已由本次纠正撤回。
- `c4973a1`：全量回归发现的音频源字节校验与 scoped read 接口回归修复。
- 评测、历史证据和迁入审计作为最后一个模块提交。

[逐文件迁入审计](local-work-integration-20261001.json) 覆盖检查点的全部 333 项变更，记录原路径、当前模块路径、处理决策与原因。其“保留远端”包含已发布的加固、注释/路径重命名与被规范检索架构取代的旧接口，不能解释为丢弃整个本地模块。

评测比较脚本遵守当前 `reindex_document(document_id)` 自行管理短事务的合同；显式 `--user` 同时用于建库和评测行路由。运行 `compare_local_models.py` 前，需在隔离评测环境按选定 profile 准备并启动匹配的 broker：模型 ID、revision、维度、token 上限和有效指令必须与当前评测进程一致。

评测代码指纹包含 broker 推理模块，版本记录包含 jieba，避免旧评分实现的证据被当作新实现结果。

## 使用新增能力

上下文默认预算沿用本地已验证设置：`CONTEXT_TOOL_BATCH_TOKENS=16000`、`CONTEXT_TOOL_HISTORY_TOKENS=24000`、`CONTEXT_TOOL_PREVIEW_TOKENS=256`、`CONTEXT_RECENT_TOKENS=8000`。

选择本地中文分析器可设 `RAG_LEXICAL_ANALYZER=jieba_search`，并按正常代次重建流程验证。该选项改变词法合同，不承诺旧报告的召回率在新规范检索库中逐项复现。默认 `cjk_bigrams` 保留远端行为。

BGE 运行合同保持远端基线。音频源验证增加两次有容量上限的流式读取，其真实端到端 I/O 延迟未单独测量。

## HNSW 与精确检索

HNSW 是向量近邻搜索索引，与 BGE 模型分别属于检索和向量生成环节。本地检查点的 `PGVECTOR_DENSE_INDEX_TYPE` 默认 `hnsw`，在按代次创建的 `rag_vec_*` 表上支持 HNSW；远端基线使用共享规范表并将 dense index 合同固定为 `EXACT`。迁入工作树沿用的是远端精确检索路径。

此前“旧 HNSW”的表述只指本地原有表和索引实现，不表示 HNSW 算法过时。HNSW 用近似搜索换取速度；精确检索逐一比较符合范围的向量，向量规模较大时可能更慢。原实现与远端实现的实际延迟/召回差异没有在真实语料上验证，不能当作性能等价迁移。业务库和已有数据库索引没有被本次操作修改。[pgvector 官方索引说明](https://github.com/pgvector/pgvector#hnsw)。

## 数据库与历史证据边界

未读取或更改当前业务库 revision。若原本地库已经运行自定义 0047/0048 链，不属于远端文档描述的 published-main 或 exact PR2 基线；必须先核对真实 revision、表与 outbox 状态，再制定数据迁移。不得手工 stamp 或直接运行现分支 upgrade 来跳过差异。

`docs/reports/` 和 2026-09-23 的本地实施文档是检查点历史证据（说明文本末尾空行按 Git 规范化，报告数据未重新计算），其旧源码路径和结果属于原始代码/运行环境，不是现分支部署步骤，也不是新的验收结果。历史 HNSW、jieba、Qwen 对照结果没有因为源码迁入就变为新检索库的性能证明。下载语料和永久改写缓存位于原工作区的忽略数据目录，未自动复制或重算，不调用付费模型。

## 验证中确认的根因

临时 Linux 环境另有独立问题：基础镜像使用 `/opt/venv`，新建嵌套 venv 的 `--system-site-packages` 不会自动继承该路径；仅调整主进程 sys.path 也不能覆盖 worker/CLI 子进程。验证 venv 通过 `.pth` 读取基础依赖，固定的新依赖安装到自己的目录，并通过 `PYTHONPATH` 指向本工作树。所需 FFmpeg 只装入一次性容器。基础与 dev 依赖版本已逐项对照 pyproject，差异为空。

数据库/Redis 只在本次容器的共享网络命名空间内提供 loopback 服务，满足真实 Celery 故障恢复测试的测试库安全合同。数据、进程和依赖均与业务运行实例隔离，测试结束按专属标签清理。

全量首轮还暴露了远端音频快照实现的字节校验缺口：同长度写入可能保留同一 mtime/ctime 刻度，原实现只比较 stat 身份。现在在捕获后和结果返回前按原固定块大小、原容量上限复核 SHA-256，并在每次内容读取前后校验 inode/路径身份；快照不被修改，错误仍为 `audio_source_changed`。模拟同一时间戳刻度的对照实验确认远端基线漏检、当前实现拒绝。`read_file` 白名单测试加入新 `source_turn_id`，原用户、会话和确切 Tool Call 过滤继续生效。

## 验证

[此前迁入版本验收记录](../reports/local-work-integration-2026-10-01/validation.json) 对应源码提交 `633f66e`。该版本包含后来撤回的 Qwen 检索代码；其全量结果作为历史验证证据保留，不直接代表纠正后的源码版本。[BGE 范围纠正验收](../reports/local-work-integration-2026-10-01/bge-correction.json)：Linux 推理、RAG、架构、评测、脚本、配置和真实 PostgreSQL 合同定向回归 **532 passed、17 skipped、0 failed**；jieba/PostgreSQL **12 passed**。Ruff 0.16.2 lint 通过，922 文件格式检查通过；主线比较 CLI 拒绝 Qwen profile。本次纠正未重复完整后端套件。

- Linux 全量后端：**2506 passed、14 skipped、0 failed**（625.55s），使用独立 PostgreSQL/Redis，覆盖迁移、租户隔离、真实 worker 中断恢复和使用量记账。
- 修复后的 Linux 定向回归：**46 passed**。
- `RAG_LEXICAL_ANALYZER=jieba_search` 下真实 PostgreSQL 检索及词法合同：**12 passed**。
- MTRAG 离线 unittest：**21 passed**；模型比较 CLI `--help` 通过。
- 固定 Ruff 0.16.2：全范围 lint 通过、924 文件格式检查通过；Git 差异检查通过。
- 原 main/暂存区保留，全部非忽略工作文件再次核对与检查点一致。

Windows 阶段的上下文 161 passed、Qwen/词法与代次合同 12 passed 是补充证据。原远端的 Linux-only 配置、文件替换/symlink 测试不能作为 Windows 后端验收门，本次已使用 Linux 全量回归覆盖这些合同。

全量测试跳过的独立验收覆盖：9 个真实浏览器场景、1 个下载语料合同、1 个真实 embedding/reranker 场景、1 个可选 aiortc/WebRTC 场景、2 个 S3 HTTP 场景。GPU 质量、真实 Supabase 登录/邮件与本地业务数据迁移均未在本次代码迁入中验收。
