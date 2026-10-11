# 主线收敛（2026-10-11）

当前分支 `codex/mainline-convergence` 以集成版本 `c980b22` 为基础，保留 BGE、统一
`retrieval_entries`、HNSW 以及已迁入的上下文、工具执行、文件资产和自动化功能。
原目录成果迁入关系保存在 [集成记录](local-work-integration-20261001.json)。

## 恢复点

- 原目录第一轮清理：`codex/cleanup-round1` / `8d6ef1f`。
- 集成基线：`codex/checkpoint-integrated-base-20261011` / `c980b22`。
- 本次删除冗余前：`codex/checkpoint-before-design-cleanup-20261011` / `5c498a7`。
- 检查点保存 Git 源码；业务 `.env`、模型、语料和数据库保持原状。

## 保留的主线与删除的旁路

资料命令 → 共享入库 → 规范文档/分块 → `retrieval_entries`。
Chat、Agent、诊断和产品评测直接调用 `rag/application/service.py`，由它执行
BGE dense + BM25 → RRF → BGE 重排 → 证据筛选 → 原文补全与引用。
删除原服务转发层与第二个 pipeline 单例；规划失败状态在成功和失败结果中都保留。
精确/HNSW 共用数据、权限和流程；HNSW 只由运维脚本准备，不在请求中建索引。

聊天统一走原生模型适配器，删除旧 LlamaIndex 流式分支。事件定义归属
`conversation/events.py`，上下文序列化归属 `core/context_messages.py`，删除转导出层。
前轮误删的语音窗口拼接、说话人匹配在本轮接入 WhisperX，见下节。删除预算包装、私有辅助函数、
S3 预签名上传/下载函数和专用配置；文件上传继续使用文件资产 capability 与不可覆盖写入。
用量页面统一调用 `/usage`；复核后恢复 `/workspace/model-usage` 的原有 HTTP 与数值响应合同，
两个地址仍调用同一个用量服务。前端无调用者的旧别名不恢复。
移除未使用的知识文档轮询函数及旧类型；资料库保留现有查询刷新逻辑。

Agent 策略、工具批次、恢复状态以及回合持久状态、异步执行监督各有实际职责，保留其边界。
文档解析回退、模型提供者适配与离线 MTRAG 基准有独立用途，不作为旧实现删除。
本次不新建审计框架，移除上一轮重复的审计/验证 JSON，历史版本仍可从检查点读取。

复核更正：语音三个孤立模块源自 `c76dc7c` 的 Qwen 长录音实现，其调用入口在 `ae57d6f`
移除 Qwen 时已经删除；当时 WhisperX 整段解码并未承接其能力。没有调用者只能证明
代码退出执行链，不能证明历史功能已被替代。本次按下面的主线补回，不恢复 Qwen 分支。
聊天附件的等待由 `waitForAttachmentDraft`、服务端附件等待/恢复承接；资料库刷新由
现有查询轮询承接，删除 `waitForKnowledgeDocument` 没有删除解析等待功能。

## WhisperX 长录音补齐

恢复点：`codex/checkpoint-before-whisperx-longform-20261011` / `46f7139`。
面试录音仍走 `transcribe_interview_evidence` → 不可变源快照 → 用量准入 →
WhisperX collector → 统一证据校验与发布。collector 复用 `PCMStream`，每个模型输入
最多 30 秒，26 秒核心区两侧各保留至多 2 秒上下文；PCM 内存不随录音长度增长。
输出文字和轨道继续受既有容量上限约束。解码沿用 Linux/WSL2 worker 的现有执行边界。

WhisperX 转写和 forced alignment 按窗运行。拼接使用时间重叠的同词锚点，保留标点、
空白、置信度及未知对齐；边界两侧时间完全分离时原样接续，不丢弃任何词。
无法确定边界或丢弃区有未匹配词时拒绝完整发布。
Community-1 每窗的说话人向量映射到录音内固定身份；局部标签可交换，身份锚点不漂移，
歧义会报错。匹配阈值沿用原显式策略，尚无真实录音校准结论，不是身份识别概率。
每窗允许一位说话人，配置的最少人数在整段结果检查，最多人数同时约束窗口和整段。
不完整解码、模型变化、容量超限、取消都不发布部分成功；仍由原用量与源快照所有者收尾。

真实模型验证补齐了两个接口细节：WhisperX 的 NumPy 时间/置信度数值在提供者边界严格
校验后转为标准浮点数；对齐所需 NLTK `punkt_tab` 在本地模型镜像构建时准备，运行时
缺失会明确失败，不隐式下载。非容器环境需在启动 worker 前执行
`python -m nltk.downloader punkt_tab`。本机验证使用已缓存资源；未重建完整生产镜像。

类似遗漏复核：RAG、事件、上下文、文件上传、附件解析等待和用量读取均已找到当前承接路径；
旧用量 HTTP 合同已恢复。另确认本地 TTS/实时合成仍未被替代，`live_synthesis_unavailable`
是当前明确的能力缺口。本轮不更换其提供者。知识库普通音频和远程混合 ASR 的整段解码
不是原 Qwen 面试证据分窗的承接者；本轮修改的范围为面试录音证据入口。

## 验证

- 最终长录音定向回归：118 passed，包含真实 FFmpeg、进程清理、跨窗重词/标点、静音、
  重叠语音、说话人重返与换标签、取消、源快照、失败不发布及 unknown 用量状态。
  模型输出为确定性替身，不代表真实 WhisperX/Community-1 的识别质量。
- Linux 完整后端：2445 passed、5 skipped，584.70 秒；真实 PostgreSQL/pgvector、Redis、
  FFmpeg，按 CI 排除浏览器测试。随后最终的静音边界修正及资源测试隔离修改已包含在上述
  118 项定向回归中（新增 3 个边界案例），未把最终差异冒充为再次全量运行。
- Windows 纯逻辑及缺失分词资源回归：17 passed。最终 Ruff、919 个 Python 文件格式、
  编译、共享协议快照与 `git diff --check` 通过。本轮未修改前端。
- 真实本地模型（WhisperX 3.8.6、faster-whisper turbo、中文 wav2vec 对齐、Community-1，
  CPU int8，禁止网络）：60 秒中文合成录音经过 3 窗，得到 201 个词级记录和连续的
  `speaker_001`，源快照与统一证据校验通过，用时 51.3 秒。
- 121.6 秒同源样本在 104 秒边界出现冲突识别，正确拒绝发布；另观察到一窗有声内容
  被 ASR 漏识别。未通过改写时间或宽松去重掩盖问题。以上仅验证工程链路与失败边界，
  不代表逐字准确率或真实多人说话人质量；多人换标签/重返目前由确定性回归覆盖。
  本轮未验证 GPU，也未验证新镜像的在线资源下载。日志留在本地忽略目录
  `data/whisperx-longform/`，不将模型和合成音频加入源码。
- 本次功能承接复核：后端 145 passed、前端 16 passed；新增用量旧地址响应格式与跨用户
  隔离回归。事件/序列化定义语法树一致，RAG 类除规划失败标记合并外一致。以下为前轮记录。
- RAG、聊天、事件、存储与架构定向回归：233 passed、1 skipped。
- Linux 完整后端：2414 passed、5 skipped、0 failed，556 秒；按 CI 排除独立浏览器测试。
  使用一次性 PostgreSQL/pgvector、Redis 和 FFmpeg，覆盖真实迁移、HNSW 与音频解码。
- 全量快照后的最后几项旧别名/用量入口删除，在最终源码上补测用量、工作台、存储和架构：
  122 passed。前端最终源码：93 个文件、381 项测试通过，类型检查和 Lint 通过。
- Ruff 检查、914 个 Python 文件格式检查、编译、共享协议快照、Compose 配置与差异检查通过。
- 5 项跳过：下载语料、真实本地 embedding/reranker、可选 aiortc、2 项真实 S3 HTTP；
  未将离线回归当作真实模型质量或外部服务验收。业务数据库未迁移，远端未发布。
