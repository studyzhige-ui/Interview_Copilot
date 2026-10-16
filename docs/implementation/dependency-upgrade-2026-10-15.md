# 最高兼容稳定版本升级与功能验收（2026-10-15）

本轮的目标是：保留全部现有功能，在项目依赖约束和实际运行验证下选择最高兼容稳定版本，并在此前提下尽量减少安全公告。例如上游最新为 8.10、当前组合最高兼容为 7.8，则目标版本为 7.8。兼容上限不属于漏升；未修复的上游公告也不单独判定升级失败。此前将“全局最新版、公告清零”当作验收目标的表述已纠正。

已更新可升级的直接依赖、npm 间接依赖和锁文件，并移除旧 PostgreSQL 驱动。保留受 WhisperX、LlamaIndex、Ragas 和编译工具实际约束的最高兼容版本；没有为了清零删除功能、更换语音主线、使用预发布版或忽略依赖约束。

开始前保存 `refs/checkpoints/dependency-upgrade-20261015`（`87e1be8152c1042917f3fe5eb136eb010ebd56b1`），本次重新核对前保存 `refs/checkpoints/compatible-upgrade-20261015`（`39e39885573b745e7a12fc7cfac94bd2d32cfc73`）。保留此前未提交工作和真实 Git 暂存区。本轮未发布、推送或生成安装包。已将最高兼容版本组合组装成新的 QA 镜像，用于 `copilot-release-check` 的 API、四类 Worker、Beat、本地模型服务和前端联动验收；不是线上部署。

## 已升级的主要组合

完整直接依赖版本以 `pyproject.toml`、`requirements/` 和三个 npm manifest/lockfile 为准；下表列出主要变化。

| 范围 | 已验证版本 |
| --- | --- |
| API 与配置 | FastAPI 0.143.1、Starlette 1.8.0、Uvicorn 0.54.0、Gunicorn 26.2.0、Pydantic 2.14.1、pydantic-settings 2.16.0 |
| 数据库 | SQLAlchemy 2.1.4、psycopg[binary] 3.3.6、Alembic 1.20.0、pgvector 0.5.1 |
| 安全与工具 | PyJWT 2.15.1、cryptography 50.0.2、filelock 4.2.0、pwdlib 0.3.1、Ruff 0.17.0；CI Ruff 版本同步 |
| LLM 与协议 | OpenAI 2.54.0、Anthropic 1.14.0、MCP 2.3.0、LangSmith 0.14.8、tiktoken 0.14.0；LlamaIndex Core 0.14.25 与相应最新兼容适配器 |
| 文档与音频 | Docling 2.139.0、RapidOCR 3.10.0、pypdf 6.20.1、CTranslate2 4.8.3、Pyannote Pipeline 4.1.0、edge-tts 7.3.1 |
| 可选实时媒体 | aiortc 1.15.0、ONNX Runtime 1.31.0；共同安装时 PyAV 为 17.1.0，符合 aiortc 的 `av<18` 约束 |
| 前端 | React/React DOM 19.3.1、TanStack Query 5.104.3、Virtual 3.14.19、Supabase JS 2.117.3、Router 7.18.4、Zustand 5.0.15、Lucide 1.57.0 |
| 前端开发 | Vite 8.3.4、Vitest 5.0.4、jsdom 30.1.2、ESLint 10.12.0、typescript-eslint 8.71.2；Node 24 类型更新为 24.19.2 |
| 桌面 | Electron 44.7.2，electron-builder 最新稳定版仍为 26.15.3；保留此前验证的下载器 global-agent 安全覆盖 |

Docling 新版改用 RapidOCR 的 `list_supported_langs` 接口，已解除此前 3.9.2 固定；隔离解析器两端的版本身份检查与独立 requirements 同步更新。

SQLAlchemy 2.1 默认 `postgresql://` 改用 psycopg 3，[官方说明](https://docs.sqlalchemy.org/en/21/dialects/postgresql.html#module-sqlalchemy.dialects.postgresql.psycopg)。因此将 psycopg2-binary 替换为 psycopg[binary]，没有并行保留两套驱动。明确配置过 `postgresql+psycopg2://` 的部署需要改为文档中的 `postgresql://`；不涉及数据库 schema 或数据迁移。

实际 PostgreSQL 回归发现：旧刷新令牌抢占使用 `INSERT ... ON CONFLICT DO NOTHING` 的 `rowcount` 判断胜者，新驱动下会误判。现在通过 `RETURNING jti` 的实际返回值确认插入。数据库唯一约束仍仲裁并发，调用方仍控制事务；并发刷新、模型调用许可、过期清理、登录/刷新/重放拒绝/退出均有实际数据库回归。

## 兼容版本上限与选择依据

所有候选均从当前官方 PyPI/npm 元数据核对，排除 prerelease、dev release 与 yanked 版本。

| 依赖 | 上游最新稳定版（未必兼容当前组合） | 最高兼容版本与原因 |
| --- | --- | --- |
| WhisperX | 3.8.6 | 已是最新稳定版，3.8.7rc1 未采用 |
| Transformers / Hub | 5.19.0 / 2.2.0 | 4.57.6 / 0.36.2；WhisperX 要求 Hub `<1`，Transformers 5.19 要求 `>=1.31`。实际 pip dry-run 返回 `ResolutionImpossible` |
| Sentence Transformers | 6.1.0 | 5.7.0；6.1 要求 Transformers `>=5`、Hub `>=1.3`，与上述组合冲突 |
| Torch / Audio / Vision / Codec | 2.14.1 / 2.11.0 / 0.29.1 / 0.17.0 | 2.8.0 / 2.8.0 / 0.23.0 / 0.7.0；WhisperX 显式限定这些版本线，Codec 还涉及原生 ABI，不能把各自全局最新版任意拼接 |
| NLTK | 3.10.3 | 已是最新稳定版，但仍存在未修复公告 |
| OpenAI SDK | 3.31.0 | 2.54.0；LlamaIndex 的最新 OpenAI LLM 适配器仍要求 `openai<3` |
| LlamaIndex OpenAI Embeddings | 0.7.0 | 0.6.0；最新 OpenAI-like embeddings 0.4.0 仍要求 `<0.7`，当前确有业务调用 |
| LangChain Community / OpenAI | 0.4.2 / 1.7.2 | 0.3.31 / 0.3.35；Ragas 最新稳定版 0.4.3 仍导入已被新版 Community 删除的 `chat_models.vertexai`。独立安装最新版后实际复现 import 失败；旧组合导入通过 |
| TypeScript | 7.0.2 | 前端 6.0.3，协议工具 5.9.3；最新版 typescript-eslint 要求 `<6.1`，openapi-typescript 要求 `^5.x` |
| Node 类型 | 26.6.5 | 24.19.2，匹配项目 Node 24 LTS 工具环境；已同步最低工具环境说明 |

[WhisperX 稳定版约束](https://github.com/m-bain/whisperX/blob/v3.8.6/pyproject.toml)、[Transformers 发布信息](https://pypi.org/project/transformers/)、[NLTK 发布信息](https://pypi.org/project/nltk/)。没有修改第三方库元数据来伪造兼容性。

## 安全公告登记

| 环境 | 审计结果 |
| --- | --- |
| 前端、桌面、协议工具 | 各自 npm audit 0 |
| 已安装 API/local/dev + 可选实时媒体组合 | pip-audit 10 条记录，归并为 7 个唯一公告，涉及 NLTK 与 Transformers |
| 加装可选 Ragas 离线评测组合 | pip-audit 23 条记录、8 个受影响包，归并为 14 个唯一公告；比运行组合额外 7 个唯一公告 |

Python 扫描覆盖环境中全部已安装 distribution 的精确版本，不仅直接依赖。`--no-deps --disable-pip` 表示对已枚举的完整集合扫描，不重新解析或安装环境；没有排除受影响包或忽略公告。项目自身不是公开 PyPI 包，扫描器将其标为不可公开审计，不将其当作无漏洞第三方包。

核心 7 项为 CVE-2026-81726、CVE-2025-14929、CVE-2026-1839、CVE-2026-4372、CVE-2026-5241、CVE-2026-9856、CVE-2026-80047。[NLTK 公告](https://github.com/advisories/GHSA-8mgp-746c-j5xp) 暂无修复版本；Transformers 部分修复位于当前 WhisperX 无法共同解析的 5.x 版本线。

可选评测额外涉及 diskcache、Ragas、LangChain、LangChain Core、LangChain OpenAI、LangChain Text Splitters。已核对：diskcache 和 Ragas 的当前最新稳定版也有无修复版本的公告，其余部分修复位于 Ragas 当前不能导入的新版依赖线。评测仍是独立可选能力，要求独立环境，不能装进发行 API/worker。完整扫描结果保留，不能因其可选而宣称项目所有依赖无公告。

既有本地资源白名单、离线加载、`trust_remote_code=False`、隔离子进程及网络拒绝保持生效。当前公告未导致本轮已验证功能失败；这些入口限制也不等于第三方漏洞已修复。按用户明确要求，无法在兼容稳定版本内消除的公告如实登记，不为其强制更换正常运行的功能或阻塞本次兼容升级验收。

## 验证与边界

### 本次重新核对与运行闭环

- 逐项核对已安装的 64 条直接依赖及实时媒体约束，全部满足；新版运行 API 的实际安装清单再次对照同一组约束，0 项不符，`pip check` 无冲突。此前已证明的兼容版本上限继续沿用，没有为重新处理而无依据更换版本。
- `http://127.0.0.1:18080` 已使用新版前端；API、四类 Worker、Beat 和本地模型服务使用 `copilot-release-acceptance:compatible-20261015`。四类 Worker 的实际 Celery ping 均返回 pong。
- 新版服务真实 HTTP 验收 **15 passed、3 skipped**：岗位、进展、行动、Offer、材料发布/投递/归档、附件解析与下载、面试安排、任务及本地 RAG 入库→检索→删除均通过；三项未启用的真实远程回答模型检查仍跳过。
- 新版 Chromium 验收 **3 passed**：20 个页面、设置刷新持久化、日程筛选保持、面试保存成功但响应丢失后的恢复。没有页面脚本错误或服务端 5xx。
- 通过界面新建并编辑中文简历，实际 PDF 分页预览和下载成功；90 项内容导出为 **5 页**，中文可检索，页码为 1/5 至 5/5。实看首尾页，文字和版式正常；未为了本次依赖验证修改简历排版。
- 各后台角色的 **517 个 Python 源文件**逐文件 SHA-256 与工作区一致，前端 **69 个生产产物**逐文件哈希与当前 dist 一致，避免误用旧镜像或旧产物得出验收结论。
- 初次混合 campaign 的两个失败为验收配置问题：公开 OpenAPI 在生产模式关闭、短时重复登录触发原有 5/minute 限流。改为读取当前服务内部 schema，并分批运行 HTTP 与浏览器 campaign 后通过；没有修改产品限流、关闭认证或放宽业务断言。
- 新建测试账号已停用、token_version 已递增，服务器及主机临时明文凭据已删除；没有修改其他账号。

QA 镜像基于此前已验证的兼容解释器与当前源码/前端产物组装。本次完成真实运行更新与功能联动验收；从零在线构建的独立发行验收仍未在这里宣称完成。QA Compose 使用 `data/release-acceptance/compose.yml` 加 `data/compatible-upgrade-20261015/compose.override.yml`，恢复旧 QA 镜像可去掉该 override；数据卷没有替换或删除。

本次证据位于 `data/compatible-upgrade-20261015/`：`manifest-parity.json`、`running-packages.json`、`http.xml`、`browser.xml`、`pdf-acceptance.json`、`runtime-parity.json` 与 `cleanup.json`。以下是此前依赖升级阶段的补充证据，保持原数量及边界，不冒充本次重跑。

| 验证 | 结果 |
| --- | --- |
| Linux 后端主回归 + 实际 PostgreSQL | 200 passed、1 skipped；含全量迁移/schema check、pgvector exact/HNSW 隔离和删除栅栏、队列提交竞态与新增数据库驱动回归 |
| 实际模型录音 | 2 passed；121.617 秒单说话人合成录音、122.569 秒双说话人录音；既有文字完整性、词级边界、跨窗口同人聚类断言未放宽 |
| BGE 本地 broker | 1024 维、归一化、相关文本相似度较高、重排次序正确；3 次真实隔离调用，无 unknown/rejected |
| Docling + RapidOCR | 隔离 CPU 解析成功，OCR 开启，保留合成 PDF 标记 |
| MCP | 实际 stdio 和 Streamable HTTP discovery/call 通过；HTTP 测试设置不可达代理，验证仍经已校验的直连源执行 |
| LLM SDK | 2 项合成 HTTP/SSE 回归通过；实际 OpenAI/Anthropic SDK 解码后，经现行 adapter 保留文本、用量和停止原因；不代表真实远程模型验收 |
| 前端 | 35 passed；lint、TypeScript 和生产构建通过；既有 PDF chunk 体积提示保留 |
| 桌面 | 4 passed；官方 Electron 44.7.2 Windows 二进制下载并核对版本；没有生成或验收安装包 |
| 协议与静态检查 | Pydantic snapshot 未变化，两份 TypeScript 协议检查通过，Ruff lint/format、compileall 与 diff whitespace 检查通过；主回归唯一跳过项需要明确提供可丢弃 S3 fixture |
| 环境一致性 | `pip check` 无冲突；可选实时媒体导入通过，兼容评测组合导入通过 |

本轮没有调用真实远程 LLM、云端账号、邮件、Gmail 或第三方 MCP。真实录音测试使用已有可追溯合成 WAV，不是重新采集麦克风；未验证 GPU/CUDA 或所有语言。当前 Linux 验证为 Python 3.13，未声称重跑完整 Python 3.11 矩阵。完整在线镜像构建与外部能力验收仍是另两项任务。

原始日志、候选元数据、完整扫描和精确安装清单位于忽略目录 `data/dependency-upgrade-20261015/`；录音复制件和模型不进入 Git。恢复检查点是源码保存点，不是正式提交或发行标签。
