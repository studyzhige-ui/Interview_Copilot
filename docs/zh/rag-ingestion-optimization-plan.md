# RAG 建库优化执行文档

> 状态: 已确认
> 范围: 只覆盖 RAG 建库链路，即 解析 -> 清洗 -> 切分 -> 标注 -> 向量化 -> 建索引。
> 用途: 本文沉淀当前源码基线、最终优化决策和可执行规格，作为后续交给 Claude/其他 Agent 执行的依据。

## 1. 背景

当前知识库主链路已经形成:

1. 用户上传知识文档，生成 `KnowledgeDocument`。
2. Celery `process_document_ingestion` 下载对象存储文件。
3. `app.rag.ingestion.ingest_document()` 使用 LlamaParse / PyMuPDF / LlamaIndex reader 解析。
4. `get_optimal_nodes()` 根据文件类型选择 Markdown / HTML / JSON / Code / Table / Sentence 切分器。
5. 写入 Milvus 2.6 hybrid collection: dense vector + server-side BM25 text。
6. 同步写入 Postgres `document_chunks`，作为 chunk 文本事实源。

这条链路已经具备可运行基础，但离“高质量、可诊断、可增量、可溯源”的生产级建库还有差距。

## 2. 当前源码基线

关键文件:

- `backend/app/rag/ingestion.py`: 文档解析、切分、embedding、写 Milvus、写 `document_chunks`。
- `backend/app/rag/milvus_hybrid.py`: Milvus 2.6 hybrid collection schema 与查询。
- `backend/app/services/knowledge/document_chunk_service.py`: Postgres chunk 事实表写入和读取。
- `backend/app/models/document_chunk.py`: `document_chunks` ORM。
- `backend/app/worker/tasks.py`: Celery ingestion task。
- `backend/scripts/reingest_hybrid.py`: 从 Postgres 事实源重建 Milvus hybrid collection。
- `backend/scripts/consistency_scan.py`: 只读一致性巡检。

当前优点:

- 已将 Postgres `document_chunks.text` 明确为事实源，Milvus 是索引副本。
- 已使用 Milvus 2.6 原生 dense + BM25 hybrid，并通过 `user_id` 做租户隔离。
- 已有 Markdown / HTML / JSON / Code / 表格 / 普通文本多种切分策略。
- 文档导入走 Celery，长任务不会阻塞 API。
- 文档重试时按 `document_id` 删除旧 Milvus rows，再重新插入，具备基本幂等性。
- 已有通用 outbox 基础设施: `OutboxJob`、`outbox_service.enqueue_job()`、`run_due_outbox_jobs()`、Celery beat `tasks.drain_outbox_jobs`、handler registry 和指数退避重试。
- 有重建 hybrid collection 脚本和一致性扫描脚本雏形。

当前主要问题:

- 清洗层几乎缺失，乱码、页眉页脚、广告、重复段落、OCR 噪声没有统一处理。
- chunk metadata 不足，缺少 page、section、heading_path、parser profile、splitter profile 等可溯源/可诊断信息。
- `document_chunks.text_hash` 只写入，尚未用于去重或一致性校验。
- `document_chunks` 已有 `node_id`、`chunk_index`、`text_hash`、`index_status`、`deleted_at`、`(document_id, chunk_index)`、`(user_id, source_kind)`，不能重复新增这些字段。
- Milvus knowledge schema 当前保存 `user_id`、`source_kind`、`document_id`、`text`、`dense`、`sparse`。本轮不为了溯源展示新增 Milvus scalar，溯源字段通过 Postgres hydrate 获取。
- 切分仍偏通用，缺少真实 token 统计和最基础的 QA 结构保护。
- 文档更新策略是整文档删除重建，不是真正的 chunk 级增量。
- 解析质量缺少指标，没有记录 parser、耗时、页数、失败原因分类、空文本率、chunk 长度分布。

## 3. 目标分级

为了避免一上来追求“论文级 RAG”，这里先定义四档成熟度。讨论时每一环节都选择目标档位。

| 等级 | 名称 | 标准 |
| --- | --- | --- |
| L0 | 可用 | 文档能解析、能切块、能检索；失败时有错误信息。 |
| L1 | 稳定 | 常见 PDF/DOCX/Markdown/HTML/CSV 可稳定入库；明显噪声被清掉；metadata 足够定位来源。 |
| L2 | 高质量 | chunk 结构适合检索；支持 category 管理和 page/section 溯源；支持去重和相邻上下文回填；可重建、可诊断。 |
| L3 | 生产增强 | chunk 级增量索引；解析质量指标和 bad case 闭环；多 parser fallback；索引一致性自动修复。 |

目标原则:

- 本轮讨论以 L3 为目标上限逐项评估，不预先把方案锁死在 L2。
- 每个环节单独决定做到 L2 还是 L3: 需要、收益高、复杂度可控的 L3 能力直接纳入；成本高但当前收益不明显的能力不做预留字段，后续需要时再扩展。
- 最终交付文档必须明确哪些能力本轮执行、哪些能力延后、哪些能力明确不做。

## 4. 六个环节执行规格

### 4.1 解析

当前源码基线:

- 配置 LlamaCloud 时，PDF/PPTX/DOCX 使用 LlamaParse 输出 Markdown。
- 未配置 LlamaCloud 时，PDF 使用 PyMuPDFReader。
- 其他文件由 LlamaIndex `SimpleDirectoryReader` 默认处理。
- 当前项目未引入 Docling 依赖；`requirements.txt` 中有 `llama-parse`、`pymupdf`、`pypdf`、`python-docx` 和 LlamaIndex file readers。

需要优化的事实:

- DOCX/PPTX 在无 LlamaCloud 时依赖默认 reader，解析质量和失败行为不明确。
- PDF fallback 只做文本抽取，不处理扫描 PDF / OCR。
- 解析结果没有记录 parser 名称、页数、文本长度、解析耗时、失败原因。
- 网页类内容只在本地 HTML 文件维度处理，没有 URL 抓取/正文抽取链路。

最终优化内容:

- LlamaParse 与 Docling 是目标上的平行一等解析器，但当前源码未引入 Docling；实现时必须先补依赖、配置、初始化错误处理和部署说明，再启用 Docling。
- 解析模块先抽象 `DocumentParser` 和 orchestration，包装现有 LlamaParse / PyMuPDF / LlamaIndex reader；Docling、OCR、LibreOffice 旧 Office 转换作为独立执行包接入，不把 11 种格式一次性硬塞进 ingest 主流程。
- 业务层上传格式白名单当前并不存在，必须新增前后端双层校验: 前端上传入口 `accept` 仅用于体验，后端 `POST /knowledge/documents` 或 worker ingest 前的格式校验才是安全边界。
- 默认输出 Markdown；结构化元数据只保留当前下游会消费的 `page_map`、parser profile 和 warnings，不设计无消费方的 tables/images 大对象。
- OCR 按需触发，不默认全量 OCR；图片 OCR 和扫描 PDF OCR 依赖 Docling/OCR 执行包落地后启用。
- 必须增加解析观测。

#### 4.1.1 `DocumentParser` 抽象

解析模块需要抽象成可替换接口，避免 ingest 主流程直接绑定某一个解析库。

目标接口:

```text
DocumentParser
  id: "llamaparse" | "docling" | "pymupdf" | ...
  supported_formats: set[str]
  parse(file_path, options) -> ParseResult

ParseResult
  markdown: str
  page_map: list[PageSpan]
  warnings: list[str]
  parser_profile: dict
```

关键原则:

- ingest 主流程只消费 `ParseResult`，不直接依赖 LlamaParse / Docling 的对象模型。
- 主解析器和 fallback 解析器都输出同一种 `ParseResult`。
- 解析器选择、fallback、OCR 触发、错误翻译都放在 parser orchestration 层。
- 不在 `ParseResult` 中预留 tables/images 结构，除非后续已有切分或前端展示消费方；本轮下游消费 Markdown 文本、页码映射、warnings 和 profile。

#### 4.1.2 业务允许格式白名单

当前源码事实:

- `backend/app/services/uploads/file_validation.py` 没有知识库文档 purpose。
- `POST /knowledge/documents` 创建知识文档时没有强制校验文档扩展名/content_type。
- 前端知识库上传入口没有稳定的 `accept` 白名单约束。

第一版白名单:

| 类别 | 扩展名 | 说明 |
| --- | --- | --- |
| PDF | `.pdf` | 支持文本型 PDF；扫描 PDF 按需 OCR。 |
| Office Open XML | `.docx`, `.pptx`, `.xlsx` | 不含旧版 `.doc`, `.ppt`, `.xls`。 |
| Web / 标记文本 | `.html`, `.htm`, `.md`, `.markdown`, `.txt` | HTML 需要清理导航、脚本、样式噪声。 |
| 表格文本 | `.csv`, `.tsv` | 保留表头和行组结构。 |
| 图片文档 | `.png`, `.jpg`, `.jpeg`, `.tiff`, `.bmp`, `.webp` | 仅用于 OCR 入库，默认走 Docling。 |
| 旧 Office 兼容格式 | `.doc`, `.ppt`, `.xls` | 常见但本地支持复杂。可条件开放: LlamaParse 可直接解析；本地路径建议先用 LibreOffice 转为 `.docx/.pptx/.xlsx` 后再交给 Docling。 |

明确不开放:

- 音视频: 即使 Docling CLI 可能支持部分 audio/vtt，也不属于知识库文档入库范围。
- 邮件、LaTeX、专利 XML 等专业格式: 后续按业务需求扩展。

实现要求:

- 后端必须新增知识库文档格式校验，校验点放在 `POST /knowledge/documents` 创建文档时，必要时 worker ingest 前再次防御性校验。
- 前端上传入口增加 `accept`，但 `accept` 只作为体验提示，不作为安全边界。
- 格式不允许、扩展名未知、content_type 与扩展名明显冲突时返回友好错误，不进入 worker。
- 前端知识库文档状态映射需要覆盖后端真实状态 `processing/ready/failed/deleting/delete_failed`；当前 `ready` 不应显示为灰色未知状态，应显示为绿色“就绪”。

#### 4.1.3 Parser 与 fallback 矩阵

这里的 fallback 是“主流文档级 fallback”，不是只针对 PDF。

| 格式 | 可选主解析器 | 文档级 fallback | 最后轻量兜底 | OCR 策略 | 失败提示 |
| --- | --- | --- | --- | --- | --- |
| PDF | LlamaParse / Docling | 另一个可用的一等解析器 | PyMuPDF 文本抽取 | 文本质量低或疑似扫描件时触发 Docling OCR | “PDF 解析失败；如果是扫描件，请开启 OCR 或更换解析器。” |
| DOCX | LlamaParse / Docling | 另一个可用的一等解析器 | python-docx 纯段落抽取 | 关闭 | “Word 文档解析失败；请确认文件内容完整，或尝试重新上传/切换解析器。” |
| PPTX | LlamaParse / Docling | 另一个可用的一等解析器 | python-pptx 文本抽取 | 关闭 | “PPT 文档解析失败；请确认文件内容完整，或尝试重新上传/切换解析器。” |
| XLSX | LlamaParse / Docling | 另一个可用的一等解析器 | openpyxl 表格抽取 | 关闭 | “Excel 文档解析失败；请确认文件内容完整，或尝试重新上传/切换解析器。” |
| HTML/HTM | LlamaParse / Docling | 另一个可用的一等解析器 | BeautifulSoup/readability 正文抽取 | 关闭 | “HTML 解析失败；请确认文件内容完整且编码正确。” |
| Markdown | LlamaParse / Docling / 纯文本 parser | 另一个可用解析器或纯文本 parser | 纯文本读取 | 关闭 | “Markdown 文件读取失败；请确认文件为 UTF-8 文本。” |
| TXT | LlamaParse / Docling / 纯文本 parser | 另一个可用解析器或纯文本 parser | 编码检测后读取 | 关闭 | “文本文件读取失败；请确认编码为 UTF-8 或常见文本编码。” |
| CSV/TSV | LlamaParse / Docling / 表格 parser | 另一个可用解析器或表格 parser | csv 模块 / openpyxl 类表格抽取 | 关闭 | “表格文本解析失败；请确认分隔符和编码正确。” |
| 图片 | LlamaParse / Docling | 另一个可用的一等解析器 | 无 | 默认 OCR | “图片 OCR 失败；请上传清晰图片或转换为 PDF 后重试。” |
| DOC | LlamaParse | LibreOffice 转 DOCX 后交给 Docling | 暂无 | 关闭 | “旧版 Word 解析失败；请转为 .docx 后重试，或切换到 LlamaParse。” |
| PPT | LlamaParse | LibreOffice 转 PPTX 后交给 Docling | 暂无 | 关闭 | “旧版 PPT 解析失败；请转为 .pptx 后重试，或切换到 LlamaParse。” |
| XLS | LlamaParse | LibreOffice 转 XLSX 后交给 Docling | 暂无 | 关闭 | “旧版 Excel 解析失败；请转为 .xlsx 后重试，或切换到 LlamaParse。” |

已确认:

- PPTX 轻量兜底使用 `python-pptx`。
- XLSX 轻量兜底使用 `openpyxl`。
- HTML 轻量兜底使用 BeautifulSoup。
- 旧 Office `.doc/.ppt/.xls` 支持: LlamaParse 可直接解析；本地路径使用 LibreOffice/headless soffice 预转换为 `.docx/.pptx/.xlsx` 后交给 Docling 或轻量 parser。
- TXT 可增加 `charset-normalizer` 做编码检测，但最终入库文本必须统一为 UTF-8。

依赖清单:

- 当前已存在: `llama-parse`、`pymupdf`、`pypdf`、`python-docx`。
- 本轮轻量兜底需要新增或确认: `python-pptx`、`openpyxl`、`beautifulsoup4`、`charset-normalizer`。
- Docling/OCR 需要新增 `docling` 及其 OCR 相关依赖，必须单独验证安装体积、启动耗时、平台兼容性和 worker 镜像构建。
- 旧 Office 本地路径依赖 LibreOffice/headless `soffice` 可执行文件；未安装时不能静默失败，必须给出友好错误并提示改传现代 OOXML 或切换 LlamaParse。
- `.xlsx` 当前解析行为需实现前验证；如果 LlamaIndex 默认 reader 未稳定支持，应优先走 `openpyxl` 轻量兜底。

#### 4.1.4 解析阶段最终方案

目标架构:

```text
业务上传白名单
  -> parser orchestration
      primary_parser = 部署配置选择的 LlamaParse 或 Docling
      fallback_parser = 另一个已配置的一等解析器
      lightweight_fallback = 格式专用轻量解析器
      legacy_office_converter = LibreOffice/headless soffice
  -> ParseResult(markdown + page_map + parser_profile + warnings)
  -> 清洗
  -> 切分
```

最终规则:

1. 建立 `DocumentParser` 抽象，ingest 主流程只消费统一 `ParseResult`。
2. LlamaParse 与 Docling 是平行一等解析器，由部署配置选择主解析器；普通用户不在运行时切换 parser。
3. fallback 是主流文档级 fallback。主解析器失败后，只对业务允许且备用解析器已安装、已配置、声明支持的格式尝试备用解析器。
4. 轻量兜底只用于最大化保留可读文本，不要求结构质量等同一等解析器。
5. 旧 Office 支持进入业务白名单；本地路径依赖 LibreOffice/headless soffice，未安装时友好提示用户改传现代 OOXML 或切换 LlamaParse。
6. OCR 按需触发: 扫描 PDF、图片文档、或文本抽取质量过低时启用，不做全量 OCR。
7. 输出优先 Markdown，同时保留 `page_map`、parser profile 和 warnings。
8. 必须记录解析观测: `primary_parser`、`actual_parser`、`fallback_used`、`legacy_conversion_used`、`ocr_used`、`page_count`、`char_count`、`duration_ms`、`warnings`、`error_code`。
9. 未知格式、业务不允许格式、解析器不支持格式、解析失败都必须转成用户友好的错误信息。
10. 页码溯源是 best-effort: 只有 parser 能提供页码映射且切分后能保持映射时写入 `page_start/page_end`；Markdown/HTML/TXT 等无页概念内容保持为空。

### 4.2 清洗

当前源码基线:

- 基本没有独立清洗层。
- 只在表格切分时去掉空行。

需要优化的事实:

- 无乱码检测和 mojibake 修复。
- 无页眉页脚检测。
- 无重复段落/重复页内容去重。
- 无广告、站点导航、版权尾巴清理。
- 无最小文本质量检查。

最终优化内容:

- 默认只启用 S0 清洗。
- 不做 LLM 清洗。
- 不做激进广告/页眉页脚/版权尾巴删除。
- 不做近似去重。
- 清洗目标是保证文本可安全入库、格式基本稳定，而不是让文档“变漂亮”。

S0 清洗范围:

| 项 | 处理 |
| --- | --- |
| 编码统一 | 所有入库文本统一为 UTF-8 字符串。 |
| Unicode 规范化 | 统一常见兼容字符，例如全角/半角可按后续策略决定；默认只做安全规范化。 |
| 控制字符 | 删除 NUL、不可见控制字符、非法 surrogate。 |
| 换行规范 | 统一 CRLF/CR 为 LF。 |
| 空白规范 | 去除行尾空白，压缩超长连续空行。 |
| 空文本保护 | 清洗后为空或极短时返回友好错误。 |
| 质量 warning | 记录 replacement char、异常符号比例、过短行比例等 warning，但默认不修改语义。 |

不做范围:

- 不删除页眉页脚。
- 不删除广告/版权/导航文本，除非解析器自身已经结构化过滤。
- 不做段落级近似去重。
- 不自动修正 OCR 错字。
- 不使用 LLM 改写、润色、总结原文。

### 4.3 切分

当前源码基线:

- Markdown/HTML/JSON/Code/表格使用结构化切分。
- 普通文档使用 `SentenceSplitter(chunk_size=512, chunk_overlap=64)`。
- 超长 chunk 二次切分。
- 当前代码入口是 `backend/app/rag/ingestion.py::get_optimal_nodes()`。
- 表格文件 `.csv/.tsv/.xlsx/.xls` 走 `_table_aware_nodes()`，按行组切分，并在每个 chunk 重复表头。
- `is_markdown_parsed=True`、`.md/.markdown`、`source_kind == "improved_qa"` 走 `MarkdownNodeParser()`。
- `.html/.htm` 走 `HTMLNodeParser()`。
- `.json` 走 `JSONNodeParser()`。
- `.py/.java/.cpp/.c` 走 `CodeSplitter()`，固定 `chunk_lines=40`、`chunk_lines_overlap=5`。
- 其他文件走 `SentenceSplitter(chunk_size=512, chunk_overlap=64)`。
- 一次切分后，如果 chunk 文本长度 `len(text) > CHUNK_SIZE * 2`，再用同一个 `SentenceSplitter(512/64)` 二次切分。
- `chunk_index` 只在写入 `document_chunks` 时按最终 node 顺序生成；当前没有 parent/child、prev/next、page_start/page_end、heading_path 字段。
- 检索上下文组装只使用 rerank 后的 `knowledge_chunks`，没有相邻 chunk 回填或 parent chunk 回填。

需要优化的事实:

- chunk_size 用字符估算，不是真 token 级控制。
- 缺少 heading path、section boundary、page span。
- 没有 parent chunk / child chunk 结构。
- 缺少 chunk overlap 的业务化策略，例如问答题库、官方文档、表格应该不同。
- 不记录 chunk 长度分布，无法知道是否产生大量过短/过长 chunk。
- 当前表格切分依赖“第一行是表头”的假设；多 sheet、复杂表头、合并单元格、空列/空行结构还没有元数据表达。
- 当前 Markdown/HTML parser 可能产生结构节点，但 `document_chunks` 没有把 heading/path/page 等结构化信息落成可过滤字段。
- 当前二次切分会把结构化 parser 产出的长节点重新切散，但不保留原 parent 信息。

最终优化内容:

- 保持当前主流策略: 结构化切分优先，递归/句子切分兜底。
- 不引入 LLM 参与切分判断。
- 不做父子切分。
- 按内容类型调整只做最保守、确定性规则；识别不到结构就回到基础切分。
- 补齐真实 token 计数和 chunk 长度分布观测。
- chunk `token_count`、超长 chunk 判定、embedding 前长度保护统一使用 embedding 模型 tokenizer；不要和 L1 chat 的 `cl100k` 估算混用。
- chunk metadata 的落库和检索字段放到下一节“标注”处理。
- Markdown / HTML / JSON / Code / Table 等结构化切分继续保留。
- LlamaParse / Docling 输出 Markdown 后，继续走 Markdown-aware 切分。
- 普通文本继续使用递归/句子切分兜底。
- 当前 `512/64` 可继续作为普通文本和超长结构块的兜底参数。
- 超长判断从 `len(text)` 改为 embedding 模型 tokenizer 统计。
- 不做复杂 QA 识别，不使用 LLM 判断内容类型。
- 只加入最基础有效的 QA 正则；正则识别不到时不猜。

最保守 QA 正则:

| 结构 | 示例 | 动作 |
| --- | --- | --- |
| Markdown 题目标题 | `## 什么是 Redis 缓存击穿？` | 由 Markdown parser 自然按 heading 切，不额外处理。 |
| 显式 Q/A 前缀 | `Q: ...` / `A: ...`，`问题：...` / `答案：...` | 仅当成对出现且间距合理时，优先把一组 Q/A 保持在同一 chunk。 |
| 编号题目 | `1. 什么是 JVM？`，`题目 1：...` | 只作为段落边界提示，不强制切分。 |

不做范围:

- 不用 LLM 判断某段是不是题目。
- 不做父子 chunk。
- 不做复杂题目抽取。
- 不为了正则命中牺牲结构化 parser 结果。

### 4.4 标注

当前源码基线:

- 文档 metadata 写入 `source_kind`、`user_id`、`document_id`、`upload_id`、`category`。
- `category` 已是 `knowledge_documents.category` 文档级字段，并已有 `(user_id, category)` 索引；不要在 `document_chunks` 里重复保存。
- Milvus knowledge collection 当前保存 `user_id`、`source_kind`、`document_id`、`text`、`dense`、`sparse`；本轮不新增 `category` 或 `chunk_index` scalar。
- Postgres chunk 表保存 `metadata_json`，但当前传入内容很少。

需要优化的事实:

- chunk 级 metadata 不完整，无法稳定支撑页面引用展示和 bad case 诊断。
- `category` 属于知识库管理 tag，已在 `knowledge_documents` 中稳定可查；普通 RAG 检索不使用 category 做 Milvus 过滤。
- `metadata_json` 是文本 JSON，不利于高频过滤和索引。
- 当前溯源字段应避免重复保存 document/file 已有信息，优先通过 `document_id` hydrate。

最终优化内容:

标注分为三类: 检索安全/快速过滤、溯源展示、诊断运维。只把当前确定会使用的字段做成显式列或 Milvus scalar；长尾结构和诊断信息保留在 `metadata_json`。向量化只向量化 chunk 原始文本，不向量化 metadata。

#### 4.4.1 检索安全与快速过滤字段

这些字段用于服务端过滤和安全边界，必须稳定、低基数或可控。

| 字段 | Postgres | Milvus scalar | 说明 |
| --- | --- | --- | --- |
| `user_id` | 已有，必须 | 已有，必须 | 租户隔离主键，使用稳定 `users.id`。 |
| `document_id` | 已有，必须 | 已有，必须 | 文档级删除、重建、引用挂载的主键。 |
| `source_kind` | 已有，必须 | 已有，必须 | 系统来源类型，如 `user_upload` / `improved_qa` / `manual_text`。 |
| `category` | `knowledge_documents` 已有，必须 | 不需要 | 用户分类，用于知识库列表和 UI 分类；普通 RAG 检索不按 category 过滤，chunk 表不重复保存。 |
| `chunk_index` | `document_chunks` 已有，必须 | 不需要 | 文档内顺序，用于引用展示和诊断；Milvus 命中后通过 Postgres hydrate 获取。 |
| `index_status` | 已有，必须 | 不需要 | Postgres 事实表索引生命周期状态: pending/indexed/failed/deleted。hydrate live check 只排除 `deleted`；`failed` 是索引副本状态，Postgres 事实文本仍然正确，不参与 hydrate 内容过滤。 |
| `deleted_at` | 已有，必须 | 不需要 | Postgres 事实表软删除控制。 |

规则:

- 检索时 Milvus 必须过滤 `user_id`。本轮普通 RAG 不按 `source_kind` 或 `category` 过滤。
- Milvus 返回结果后，必须用 Postgres hydrate 一次，确认 chunk 仍存在、`index_status != deleted`、`deleted_at is null`。
- 不加入 `permission`、`document_version` 等未实现字段；后续真正做共享权限或版本并行时再加。

#### 4.4.2 溯源展示字段

这些字段用于回答页面挂载引用来源，让用户能看到“来自哪个文档、哪一页、哪一节、哪个 chunk”。

| 字段 | Postgres | Milvus scalar/output | 说明 |
| --- | --- | --- | --- |
| `chunk_id` / `id` | `document_chunks.id` 已有，必须 | 不需要 | 前端引用、调试、反馈 bad case 的最小定位单元。 |
| `node_id` | 已有，必须 | Milvus primary key | Milvus row id 和 hydrate join key；Milvus 命中后用 `node_id` 查 `document_chunks`。 |
| `chunk_index` | 已有，必须 | 不需要 | 文档内顺序，用于引用展示和排序，通过 hydrate 获取。 |
| `page_start` | 新增 nullable 列 | 不需要 | 来源起始页；没有页概念时为空。 |
| `page_end` | 新增 nullable 列 | 不需要 | 来源结束页；没有页概念时为空。 |
| `section_title` | `metadata_json` | 不需要 | 当前 chunk 所属最近标题或 slide/table 名称，展示时读取即可。 |
| `heading_path` | `metadata_json` | 不需要 | 标题路径，例如 `缓存 > Redis > 缓存击穿`。 |
| `chunk_type` | `metadata_json` | 不需要 | `text` / `table` / `code` / `slide` / `image_ocr` 等。 |
| `text_preview` | 可运行时生成 | 不需要 | 前端 source 卡片展示用，从 chunk text 截断生成。 |
| `document_title` | 来自 `knowledge_documents` | 不进 Milvus | 展示时通过 `document_id` hydrate，避免标题修改后 Milvus 陈旧。 |
| `file_name` | 来自 `file_assets.original_filename` | 不进 Milvus | 展示时通过 `document_id -> file_asset_id` hydrate。 |
| `content_type` / `size_bytes` | 来自 `file_assets` | 不进 Milvus | 文件类型和大小已有事实来源，不在 chunk 里重复。 |

规则:

- 回答 API 最终返回 sources 前必须做 Postgres hydrate，补齐 `document_title`、`file_name/original_filename`、`content_type`、`size_bytes`，并过滤已删 chunk。
- 页码是 best-effort 溯源字段，不是所有格式都能得到；只有 parser 和切分阶段能保留映射时才写 `page_start/page_end`，否则为空。
- 标题路径、section、chunk type 是展示增强和诊断信息，先放 `metadata_json`，不做显式列。

#### 4.4.3 诊断运维字段

这些字段用于开发者排查解析质量、切分质量、索引质量，不作为主要检索过滤条件。

| 字段 | Postgres | Milvus | 说明 |
| --- | --- | --- | --- |
| `text_hash` | 已有，必须 | 不需要 | chunk 内容 hash，用于增量、幂等、漂移排查。 |
| `token_count` | 新增列，必须 | 不需要 | 使用 embedding 模型 tokenizer 统计，替代 `len(text)` 估算，用于切分超长判定、embedding 输入保护和统计诊断；不作为 LLM prompt context 预算。 |
| `char_count` | 运行时/统计时计算 | 不需要 | 可由 `text` 长度计算，不单独落列。 |
| `parser_id` | `metadata_json` | 不需要 | `llamaparse` / `docling` / `pymupdf` / lightweight parser。 |
| `parser_profile_json` | `metadata_json` | 不需要 | parser 版本、fallback、OCR、warnings、耗时等。 |
| `ocr_used` | `metadata_json` | 不需要 | 是否经过 OCR。 |
| `cleaning_profile_json` | `metadata_json` | 不需要 | S0 清洗统计。 |
| `splitter_id` | `metadata_json` | 不需要 | `markdown` / `html` / `json` / `code` / `table` / `sentence`。 |
| `splitter_profile_json` | `metadata_json` | 不需要 | chunk_size、overlap、tokenizer、正则命中等。 |
| `embedding_profile_json` | 后续向量化阶段决定 | 不需要 | embedding provider/model/dim/version。 |

规则:

- `metadata_json` 不再只放少量 category，而是作为长尾诊断信息容器。
- 高频事实字段不能只放 `metadata_json`；但本轮 Milvus 不为溯源新增 scalar，普通 RAG 检索只依赖 Milvus `user_id` pre-filter。
- 诊断字段要能支撑 bad case: 给一个 answer source，开发者能查到它怎么解析、怎么清洗、怎么切分、怎么索引。
- 不把 parser/cleaner/splitter 的 profile 提前拆成多列；这些字段不是检索过滤条件。

#### 4.4.4 标注阶段落库要求

`document_chunks` 最小新增字段:

```text
page_start
page_end
token_count
```

`document_chunks.metadata_json` 保存:

```text
section_title
heading_path
chunk_type
parser_profile
cleaning_profile
splitter_profile
warnings
```

Milvus knowledge collection 最小 scalar/output 字段:

```text
user_id
source_kind
document_id
```

source schema 权威位置:

- source schema 以 `docs/zh/rag-retrieval-optimization-plan.md` 的“source 返回结构”为唯一权威。
- 建库阶段只保证 hydrate 所需事实字段可取: `document_chunks.id/node_id/chunk_index/page_start/page_end/metadata_json/token_count/text_hash`、`knowledge_documents.title/category/source_kind/status/deleted_at/file_asset_id`、`file_assets.original_filename/content_type/size_bytes`。
- `ref=K#`、`score`、`score_source`、最终 sources 数组只在检索/上下文组装阶段生成，不在建库阶段生成。

### 4.5 向量化

当前源码基线:

- 使用全局 `Settings.embed_model`。
- `backend/app/rag/embedding_registry.py` 已提供 provider registry。
- `EMBEDDING_PROVIDER` 支持 `local`、`openai`、`siliconflow`、`jina`、`dashscope`、`zhipu`。
- `EMBEDDING_MODEL` 默认 `BAAI/bge-m3`。
- `EMBEDDING_DIM` 默认 `1024`。
- ingest 时在 `_write_to_milvus_hybrid()` 中批量调用 `get_text_embedding_batch()`。
- query 侧使用同一个 `Settings.embed_model.get_query_embedding()`。
- Milvus dense vector 维度由 `settings.EMBEDDING_DIM` 决定。
- sparse/BM25 由 Milvus server-side BM25 function 生成，不在向量化阶段手工生成。

需要优化的事实:

- 当前没有在写入 Milvus 前校验 embedding 实际维度是否等于 `EMBEDDING_DIM`。
- 当前 embedding provider/model/dim 主要存在配置和日志里，chunk/source 诊断时不够直接。
- 当前 embedding 失败会导致整文档失败，这个行为可以保留，但需要更清晰的错误分类。
- 当前批量大小、超时、重试、限流不够显式。
- 当前没有 embedding cache；本轮不作为必须项。
- 当前配置注释强调“不同维度要重建”，但实际任何 embedding model/provider 变化都应该触发全量重建；即使维度相同，也不能混用不同模型生成的 document/query 向量。

最终优化内容:

向量化阶段保持轻量，不把复杂度前移。核心目标是: 选定模型与维度、保证文档向量和查询向量一致、失败可诊断、后续可安全重建。

#### 4.5.1 模型与维度

| 项 | 决策 |
| --- | --- |
| 默认模型 | 继续使用当前默认 `BAAI/bge-m3`。 |
| 默认维度 | 继续使用当前默认 `1024`。 |
| provider 选择 | 当前后端已有 embedding provider registry，支持 `local`、`openai`、`siliconflow`、`jina`、`dashscope`、`zhipu`。 |
| 默认 provider | 继续使用当前默认 `local`，部署可按环境切换到 OpenAI-compatible provider。 |
| 配置层级 | embedding 属于系统基础模型，由开发者/维护者在部署配置中选择，不开放给普通用户运行时切换。 |
| query/document 一致性 | ingest 和 query 必须使用同一套 embedding provider/model/dim。 |
| metadata 是否向量化 | 不向量化 metadata，只向量化 chunk 原始文本。 |
| reranker | reranker 是检索精排阶段能力，不属于向量化阶段。 |

规则:

- `EMBEDDING_PROVIDER + EMBEDDING_MODEL + EMBEDDING_DIM` 组成当前知识库索引的 embedding identity。
- 任意一项变化后，都必须重建相关 Milvus collection 或至少重建受影响文档的全部向量。
- 当前 knowledge/resume/ability 三个 Milvus collection 共享同一套 embedding identity；系统级 embedding 变更时，重建范围必须覆盖全部使用 dense vector 的 collection，不只包含 knowledge collection。
- 启动或初始化 RAG 时必须校验已存在 Milvus collection 的 dense vector dim 是否等于 `EMBEDDING_DIM`；`ensure_collection` 不能只在建表时使用 dim，已有 collection 维度不一致必须 fail loud 并提示重建。
- 不允许同一个 Milvus collection 中长期混用不同 embedding identity 的向量。
- embedding 不像聊天模型一样适合用户运行时切换；它属于系统级基础模型，变更必须由开发者/维护者执行，并配套重建/迁移索引。
- 同类系统级基础模型还包括 reranker、ASR/Whisper、parser/OCR 等；普通用户只在产品层选择自己使用的 LLM。

#### 4.5.2 向量化输入保护

必须补齐:

- embedding 前过滤空字符串和纯空白 chunk，并记录 warning。
- embedding 前使用真实 `token_count` 观测过长 chunk；过长 chunk 应该回到切分阶段处理，而不是直接送 embedding。
- embedding tokenizer 不可用时，允许退回保守估算并记录 warning；不能因为 tokenizer 下载失败而静默写入缺少诊断信息的 chunks。
- embedding 返回后校验每条向量长度等于 `EMBEDDING_DIM`。
- embedding 数量必须等于输入 chunk 数量；不一致时整文档失败，不写入部分索引。

#### 4.5.3 失败策略

本轮采用文档级原子策略:

- embedding 成功后才进入 Milvus 写入。
- embedding 失败时整文档入库失败，`KnowledgeDocument.status = failed`。
- 不做“部分 chunk 成功、部分 chunk 失败”的半入库。
- 用户侧错误信息应区分: provider 未配置、provider 调用失败、维度不匹配、文本为空/过长。

#### 4.5.4 观测与记录

记录到导入 profile / chunk `metadata_json` 的最小信息:

```text
embedding_provider
embedding_model
embedding_dim
embedding_batch_size
embedding_duration_ms
embedding_chunk_count
embedding_error_code
```

这些字段用于诊断和重建判断，不进入 Milvus scalar，也不参与向量化。

#### 4.5.5 明确不做

- 不做 embedding cache 表。
- 不做 Redis/disk embedding cache。
- 不做 chunk 级增量复用向量。
- 不做多 embedding 模型并行索引。
- 不做用户级 embedding provider/model 切换 UI。
- 不把 embedding profile 拆成 Postgres 显式列。

### 4.6 建索引

当前源码基线:

- Milvus collection schema: `id`、`user_id`、`source_kind`、`document_id`、`text`、`dense`、`sparse`。
- `dense` 使用 HNSW，当前参数来自 `MILVUS_DENSE_INDEX_TYPE=HNSW`、`MILVUS_HNSW_M=16`、`MILVUS_HNSW_EF_CONSTRUCTION=200`、`MILVUS_HNSW_EF_SEARCH=64`。
- `sparse` 使用 Milvus server-side BM25 function + `SPARSE_INVERTED_INDEX`。
- metadata filter 通过 Milvus scalar expr 完成，当前强制 `user_id == users.id`，可额外过滤 `source_kind`。
- 重建脚本 `backend/scripts/reingest_hybrid.py` 可从 Postgres facts 重建 knowledge/resume/ability 三个 collection。
- 当前知识库重导入是文档级 replacement: 按 `document_id` 删除旧 Milvus rows，再插入新 rows；Postgres `document_chunks` 也按 `document_id` 删除旧 chunks 后写入新 chunks。

索引类型:

| 类型 | 当前实现 | 作用 | 本轮优化 |
| --- | --- | --- | --- |
| 向量索引 | Milvus `dense` HNSW | 加速语义相似度搜索 | 保持 HNSW；补维度校验和重建策略。 |
| 文本索引 | Milvus `sparse` BM25 inverted index | 支持关键词/BM25 召回 | 保持 Milvus server-side BM25。 |
| 元数据索引 | Milvus scalar expr + Postgres B-tree | 加速租户隔离、文档删除/重建、文档管理查询 | Milvus schema 保持不变；Postgres 增加必要字段和索引。 |

需要优化的事实:

- Milvus knowledge collection 不需要为溯源新增 `chunk_index` 或 `category`；这两个字段分别来自 `document_chunks` 和 `knowledge_documents` hydrate。
- 当前 `document_chunks` 缺少 `page_start/page_end/token_count`，无法支撑页码溯源、embedding 侧 token 统计和评测诊断。
- 当前写入顺序是先写 Milvus，再写 Postgres chunk facts；如果 Postgres 写失败，可能出现 Milvus 和事实表不一致。
- 删除文档时先删除 Postgres chunks 再删 Milvus；Milvus 删除失败会产生索引残留，虽然文档 `deleted_at` 可以在 hydrate/live-doc 阶段过滤，但残留 rows 仍会浪费索引空间并干扰诊断。
- consistency scan 只看数量 drift，不做 node_id/chunk_id 级校验。
- reingest 脚本没有按用户、文档、category 分批重建能力。
- 当前已有通用 outbox，但尚未注册 Milvus upsert/delete/reindex handler 自动修复索引残留或漏写。

已确认:

1. Milvus knowledge schema 保持不变，不加入 `category`、`chunk_index`、`permission`、`document_version`、`page_start/page_end`。
2. 当前采用文档级删除重导，不引入 `document_version` 字段。
3. `document_version` 主要用于异步/增量/零停机索引切换；本项目本轮不需要。
4. Postgres `document_chunks` 是事实源，Milvus 是可重建索引副本。
5. 索引写入顺序改为 Postgres pending -> Milvus -> Postgres indexed。
6. 删除文档时先让读路径不可见，再清理 chunks 和 Milvus rows。
7. 复用现有 outbox 基础设施，新增 Milvus 写入、删除和文档级 reindex job type 与 handler。
8. consistency scan 升级为 node_id/chunk 级校验。

#### 4.6.0 建索引核心判断

本轮建索引目标不是追求复杂增量，而是让索引做到一致、可删、可重建、可诊断。

1. 不需要 `document_version`。
2. 需要文档级 reindex，不做 chunk 级增量。
3. Milvus metadata 字段保持克制，只保留当前安全过滤和索引定位必要字段。
4. 最大风险是写入一致性，必须避免 Milvus 已写但 Postgres facts 未写。
5. 删除必须先让读路径不可见，即先标记 document/chunk 删除状态，再清理索引副本。
6. outbox 必须做，用于自动重试 Milvus 写入、删除和 reindex。
7. consistency scan 必须从数量检查升级为 node_id/chunk 级检查。

#### 4.6.1 为什么本轮不加 document_version

当前项目的更新语义是“一个文档更新后，旧 chunks 整体失效，新 chunks 整体生效”。在这种语义下，`document_id` 已经足够表达删除和重导边界:

```text
document_id = kdoc_x
  -> 删除旧 document_id = kdoc_x 的 Milvus rows
  -> 删除旧 document_id = kdoc_x 的 Postgres chunks
  -> 写入新 chunks 和新 Milvus rows
```

因此:

- 不需要为了当前全量 replacement 增加 `document_version`。
- 不需要在 Milvus filter 中增加版本条件。
- 不需要把回答 source 绑定到某个版本。

别人说的“版本增量更新”通常是另一种架构:

```text
active_version = 3
新文档解析/切分 -> staging version = 4
  -> 对比 version 3 与 version 4 的 chunk hash
  -> unchanged: 复用旧 chunk/vector
  -> added/changed: 生成新 chunk/vector
  -> deleted: 标记旧 chunk/vector 待删除
  -> version 4 全部索引完成后，把 active_version 切到 4
  -> 后台清理 version 3 的废弃 rows
```

版本字段的价值是:

- 新旧索引可以短暂并存，查询只过滤 `active_version`。
- 异步索引没完成前，用户仍然查旧版本。
- 切换失败可以回滚到旧版本。
- 后台清理可以慢慢做，不影响线上查询。

代价是:

- schema 多一个版本维度。
- 每次查询都要带版本过滤或 active version hydrate。
- 清理任务、回滚、版本状态机都要实现。
- chunk 复用需要稳定 chunk id 或 hash diff。

本项目本轮不做这套复杂度。

#### 4.6.2 增量更新一般怎么做

如果未来要做 chunk 级增量，可以按这个流程实现:

```text
1. 解析新文档，得到 new_chunks。
2. 对每个 new_chunk 计算 text_hash。
3. 读取旧 chunks: old_chunks by document_id。
4. 用稳定规则匹配 chunk:
   - 优先 stable_chunk_key，例如 page + heading_path + local_index。
   - 其次 text_hash。
   - 最后 chunk_index 只能作为弱参考。
5. unchanged: 旧 chunk 保留，向量复用。
6. added/changed: 新 chunk embedding 后 upsert Milvus。
7. deleted: 旧 chunk 标记 deleted，并删除对应 Milvus row。
8. 全部成功后提交新的 document chunk set。
```

难点:

- chunk_index 不稳定，文档前面插入一段后，后续 index 都会变。
- 解析器输出可能变化，同一文件重跑也可能切分略有不同。
- hash 只能识别完全相同文本，不能识别“同一段落轻微修改”。
- 异步失败时需要恢复策略。

所以本轮只做文档级 rebuild，先把一致性做好。

#### 4.6.3 本轮建索引优化内容

Milvus knowledge collection:

```text
保持当前 schema，不新增 scalar/output 字段。
```

Postgres `document_chunks` 已有字段/索引事实:

```text
(document_id, chunk_index)
(user_id, source_kind)
node_id
text_hash
index_status
deleted_at
```

Postgres `document_chunks` 本轮新增字段:

```text
page_start
page_end
token_count
```

本轮不为 `text_hash/index_status/deleted_at` 额外新增索引；常规查询已由 `document_id`、`(document_id, chunk_index)`、`(user_id, source_kind)` 覆盖，consistency scan 可离线全扫或按文档范围扫描。

按分类批量重建不在 chunk 表冗余 `category`，而是通过 `knowledge_documents(user_id, category)` 先查出 `document_id`。

写入策略:

- Postgres `document_chunks` 是事实源，Milvus 是可重建索引副本。
- ingest 应避免“Milvus 已写、Postgres facts 未写”的不一致窗口。
- 当前 `document_chunk_service.write_chunks()` 硬编码 `index_status="indexed"`，且注释假设调用方先写 Milvus；实现新顺序时必须同步改为两阶段状态，不能只改 ingest 调用顺序。
- `ingest_document` 和 `ingest_text` 共用 Milvus/Postgres 写入语义，改写入顺序时必须同时覆盖两条路径；`ingest_text` 包含 improved QA 发布等知识入库路径。
- 写入顺序调整为:

```text
解析/清洗/切分/标注/向量化全部成功
  -> 在同一 DB 事务中 replacement 写入 document_chunks，index_status = pending
  -> 写入/替换 Milvus rows
  -> Milvus 成功后把对应 chunks 标记 index_status = indexed
  -> Milvus 失败则保留 facts + failed/pending 状态，允许重试 reindex
```

重试边界:

- Celery task retry 覆盖整条导入管线失败，例如解析、清洗、切分、embedding 失败。
- outbox 只负责 Postgres facts 已落库后的 Milvus 副本操作，例如 upsert/delete/reindex；不要让 Celery 和 outbox 对同一个 Milvus 操作做无限叠加重试。
- 新顺序下 replacement 可能出现短暂窗口: Postgres 旧 chunks 已不可见、Milvus 旧 rows 尚未清理或新 rows 尚未写入，此时该文档可能临时不可检索。这是可接受的一致性取舍，读路径以 Postgres facts 为准。

删除策略:

- 删除文档时先标记 `knowledge_documents.deleted_at/status=deleting`，让读路径立即不可见。
- 再删除或标记 `document_chunks.index_status=deleted/deleted_at`。
- 再删除 Milvus rows by `document_id`。
- Milvus 删除失败时写入 outbox job，后续自动重试；文档在读路径中保持不可见。

Outbox 策略:

- 复用现有 `OutboxJob` / `outbox_service` / `tasks.drain_outbox_jobs`，不要新建 outbox 表或重复实现重试框架。
- 新增 Milvus index outbox job 类型并注册 handler，至少覆盖:

```text
milvus_upsert_document
milvus_delete_document
milvus_reindex_document
```

- outbox 约定:

```text
aggregate_id = document_id
payload_json = {"source_kind": "..."}
```

- `user_id`、`attempts`、`last_error`、`status`、`next_run_at` 使用现有 `OutboxJob` 列，不放进 payload_json 重复保存。
- worker 从 Postgres facts 读取 live chunks 后重建 Milvus rows，不从旧 Milvus rows 反推事实。
- outbox job 必须幂等: 同一个 `document_id` 重试时，先删除该文档旧 Milvus rows，再按 facts 写入当前 rows。
- outbox 失败不应让已删除文档重新可见；可见性由 Postgres document/chunk 状态决定。

重建策略:

- 支持按 `document_id` 重建单文档 Milvus rows。
- 支持按 `user_id` / `category` 分批重建；`category` 从 Postgres facts 查询，不依赖 Milvus scalar。
- 保留全 collection drop + reingest 作为灾难恢复手段。

一致性扫描:

- 从 Postgres live chunks 出发，检查 Milvus 是否存在对应 `node_id`。
- 从 Milvus rows 抽样或全量检查，确认 `document_id` 仍是 live document。
- 输出 missing_in_milvus、stale_in_milvus、metadata_mismatch、dimension_mismatch。

#### 4.6.4 明确不做

- 不做 `document_version`。
- 不做 chunk 级增量复用向量。
- 不做多版本并存查询。
- 不做用户级不同 embedding collection。

已确认执行:

- 本轮复用现有 outbox，新增 Milvus job type 和 handler 自动重试 Milvus 写入/删除/reindex。
- 文档 replacement 写入改为 Postgres pending -> Milvus -> Postgres indexed。
- consistency scan 先提供脚本/管理命令能力，至少支持 node_id/chunk 级检查；本轮不接入定时任务，后续由生产运维阶段单独评估。

## 5. 执行包划分

可以拆成以下 Claude/其他 Agent 执行包:

### INGEST-OBSERVABILITY

目标:

- 为解析、清洗、切分、embedding、写索引增加统计字段和日志。
- 输出 chunk 长度分布、parser、embedding identity、耗时、失败原因。

验收:

- 每个导入完成的 `KnowledgeDocument` 能看到 parser、chunk_count、embedding provider/model/dim、warning/error summary。
- 日志中能定位导入慢在哪一步。

### INGEST-METADATA

目标:

- 扩展 `document_chunks` metadata。
- 不扩展 Milvus knowledge schema。
- 让 context/source 返回可引用字段。

验收:

- 每个 chunk 行必须包含 `document_id`、`chunk_index`、`token_count`、`text_hash`；`page_start/page_end` 列必须存在，值允许为 NULL，无页概念格式保持为空。
- `category` 从 `knowledge_documents` hydrate，不写入 `document_chunks`。
- `heading_path`、`section_title`、`chunk_type`、parser/cleaner/splitter profile 进入 `metadata_json`。
- 检索结果能返回足够来源信息。

### INGEST-CLEANING

目标:

- 增加保守清洗管线。
- 只做 S0 清洗: 编码/Unicode/控制字符/换行/空白/空文本保护和质量 warning。

验收:

- 清洗步骤可开关。
- 每次清洗记录基础统计和 warning。
- 不改写原文语义。

### INGEST-CHUNKING

目标:

- 保持结构化切分优先，递归/句子切分兜底。
- 增加真实 tokenizer 统计。
- 增加最保守的 QA 结构正则保护。

验收:

- Markdown/HTML 尽量把 heading_path 写入 `metadata_json`。
- 解析器提供页码时写入 `page_start/page_end`。
- 表格 chunk 保留表头。
- 不引入父子 chunk。

### INGEST-EMBEDDING

目标:

- 保持当前 embedding provider registry 和默认 BGE-M3/1024。
- embedding 前做空文本保护，embedding 后做维度和数量校验。
- 记录 embedding provider/model/dim/batch/duration/error。

验收:

- 任意 embedding provider/model/dim 变化都会被视为需要重建索引。
- 向量维度不匹配时不写入 Milvus，并给出明确错误。
- embedding 失败时整文档失败，不产生部分 chunk 索引。
- 不实现 embedding cache。

### INGEST-INDEXING

目标:

- 保持 Milvus knowledge schema 不变。
- 调整写入顺序，降低 Milvus 与 Postgres facts 不一致窗口。
- 复用现有 outbox，新增 Milvus 写入、删除和文档级 reindex job type 与 handler。
- 支持文档级 reindex 和更细的一致性扫描。
- 明确不引入 `document_version` 和 chunk 级增量。

验收:

- 文档 replacement 写入遵循 Postgres pending -> Milvus -> Postgres indexed。
- Milvus 写入/删除失败会生成可重试 outbox job，复用现有 `OutboxJob` 的 `attempts/last_error/status/next_run_at`。
- 可按 `document_id` 重建单文档 Milvus rows。
- 可按 `user_id` / `category` 分批重建，category 查询来自 Postgres。
- consistency scan 能输出 missing_in_milvus、stale_in_milvus、metadata_mismatch。
- 文档删除后，即使 Milvus 删除失败，读路径也不会返回已删除文档内容。

### INGEST-CLEANUP

目标:

- 删除或替换与新建库设计冲突的旧逻辑，避免新旧路径并存。

清单:

- `document_chunk_service.write_chunks()` 不再硬编码 `index_status="indexed"`，改为支持 pending -> indexed 两阶段。
- 删除 ingest 时把 `{"category": ...}` 写入 chunk `metadata_json` 的逻辑；category 通过 `knowledge_documents` hydrate，避免 PATCH 修改分类后 chunk metadata 陈旧。
- 超长 chunk 判定从 `len(text)` 改为 embedding tokenizer 计数；tokenizer 不可用时使用保守估算并记录 warning。
- `reingest_hybrid.py` 在原脚本上扩展 document/user/category 维度，不另写第二套 reingest 脚本。
- consistency scan 从数量级 drift 检查升级为 node_id 级检查，避免两套扫描语义长期并存。

## 6. 当前建库结论

已完成讨论并确认: 解析、清洗、切分、标注、向量化、建索引。

后续链路见:

1. `docs/zh/rag-retrieval-optimization-plan.md`
2. `docs/zh/rag-generation-optimization-plan.md`
3. `docs/zh/rag-production-optimization-plan.md`
4. `docs/zh/rag-evaluation-optimization-plan.md`

## 7. 决策记录

| 日期 | 环节 | 决策 | 理由 | 状态 |
| --- | --- | --- | --- | --- |
| 2026-06-09 | 解析 | LlamaParse 与 Docling 作为目标上的平行一等解析器；部署配置选择主解析器；当前源码需先补 `DocumentParser` 抽象和 Docling 依赖/配置后再启用 Docling fallback。 | LlamaParse 可能有额度/费用限制，Docling 提供本地解析和 OCR 能力；但当前项目未引入 Docling，不能假定已可用。 | 已确认 |
| 2026-06-09 | 解析 | 新增知识库上传格式白名单；前端 `accept` 只做体验提示，后端 `POST /knowledge/documents` 或 worker ingest 前校验才是安全边界。 | 当前知识库上传缺少专门格式校验，解析器能力不等于业务允许范围。 | 已确认 |
| 2026-06-09 | 解析 | 解析输出优先 Markdown，同时保留 `page_map`、parser profile 和 warnings；OCR 只在扫描 PDF、图片文档或文本抽取质量过低时触发。 | Markdown 适合后续切分与检索；页码映射和 profile 支撑 best-effort 溯源和诊断；按需 OCR 避免全量解析变慢。 | 已确认 |
| 2026-06-09 | 解析 | PPTX 轻量兜底使用 `python-pptx`；XLSX 轻量兜底使用 `openpyxl`；HTML 轻量兜底使用 BeautifulSoup。 | 三者依赖相对可控，适合在一等解析器失败后尽量保留可读文本和基础结构。 | 已确认 |
| 2026-06-09 | 解析 | Markdown、TXT、CSV/TSV、图片也纳入 LlamaParse 可选主解析器范围；但简单文本/表格格式可优先使用轻量 parser 以节省额度和降低延迟。 | LlamaParse 官方支持这些类型；业务上仍可按成本和速度选择更经济的默认策略。 | 已确认 |
| 2026-06-09 | 解析 | 支持旧 Office `.doc/.ppt/.xls`。LlamaParse 可直接解析；本地路径使用 LibreOffice/headless soffice 预转换为 `.docx/.pptx/.xlsx` 后交给 Docling 或轻量 parser。 | 旧 Office 仍常见；本地直接解析复杂，预转换为现代 OOXML 后处理更可控。 | 已确认 |
| 2026-06-09 | 清洗 | 清洗阶段只做最保守 S0: 编码统一、控制字符清理、换行/空白规范、空文本保护和质量 warning；不做页眉页脚/广告删除、近似去重、OCR 错字修正或 LLM 改写。 | 文档噪声高度个性化，激进清洗容易误删有效面试题/笔记内容；建库质量主要交给解析、切分、标注和检索阶段处理。 | 已确认 |
| 2026-06-09 | 切分 | 保持结构化切分优先 + 递归/句子切分兜底；不引入 LLM、不做父子切分；补真实 token 计数、chunk 长度分布观测和最保守 QA 正则。 | 当前源码已有 Markdown/HTML/JSON/Code/Table/Sentence 分流，现实改造应补细节而不是重写复杂层级系统；复杂内容分类成本高且收益不确定。 | 已确认 |
| 2026-06-09 | 标注 | Milvus knowledge schema 保持当前 `user_id/source_kind/document_id/text/dense/sparse`；`category` 只保留在 `knowledge_documents`；`document_chunks` 本轮只新增 `page_start/page_end/token_count`；溯源和诊断长尾进入 `metadata_json`。 | 避免为了未实现功能预留 Milvus schema；`chunk_index/text_hash/index_status/deleted_at/node_id` 已存在；document title、file name、content type、size 等通过 hydrate 获取。 | 已确认 |
| 2026-06-09 | 向量化 | 保持当前 provider/model/dim 配置体系，默认 BGE-M3/1024；不做 embedding cache；补空文本保护、维度校验、数量校验、文档级失败和 embedding profile 记录。 | 向量化阶段核心是确保 document/query 向量来自同一 embedding identity；复杂一致性和重建策略放到建索引阶段处理。 | 已确认 |
| 2026-06-09 | 建索引 | 保持 Milvus hybrid: dense HNSW + BM25 sparse inverted index + scalar filter；不新增 Milvus scalar；不做 `document_version` 和 chunk 级增量；复用现有 outbox 自动重试 Milvus 写入/删除/reindex；支持文档级 reindex 和 node_id/chunk 级 consistency scan。 | 本轮目标是一致、可删、可重建、可诊断；Postgres 是事实源，Milvus 是索引副本，复杂版本增量会显著增加状态机和清理成本。 | 已确认 |
| 2026-06-10 | 标注 | hydrate live check 统一为: 文档 live + chunk `deleted_at is null` + `index_status != deleted`；`failed` 不参与 hydrate 内容过滤。 | Postgres 文本是事实源，`failed` 只说明 Milvus 副本写入失败；排除 `failed` 会在罕见中间态下无谓隐藏正确内容，且与 `read_document_text` 现行为一致。 | 已确认 |

## 8. Claude 执行提示草稿

下面内容可作为交给 Claude/其他 Agent 的执行提示基础。

```text
请基于 docs/zh/rag-ingestion-optimization-plan.md 中已经确认的决策，改造 Interview Copilot 的 RAG 建库链路。

执行原则:
1. Postgres document_chunks 是 chunk 事实源，Milvus 只是索引副本。
2. 不要引入 LlamaIndex PostgresDocumentStore 作为长期存储。
3. 不要改变检索阶段“按 users.id 做租户隔离”的安全边界。
4. 每个改动必须有测试或脚本级验证。
5. 保持 UTF-8，不要破坏中文文本。

优先顺序:
1. 先修 metadata、观测、上传白名单和解析错误处理。
2. 再做 S0 清洗、tokenizer 统计和基础切分细节。
3. 再改写入顺序为 Postgres pending -> Milvus -> indexed。
4. 最后复用现有 outbox 增加 Milvus upsert/delete/reindex handler，并升级 consistency scan。
5. 明确不做 chunk 级增量和 `document_version`。
```
