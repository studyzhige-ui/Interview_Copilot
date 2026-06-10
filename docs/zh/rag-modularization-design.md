# RAG 链路模块化设计（Phase E）

> 状态：设计稿，待用户评审批准后再实现。实现仍遵循"每个 part 两审（功能完整性 + 代码质量）过审才提交、逐 part 增量提交"的既有纪律。

## 0. 目标与原则

**目标**：把整条 RAG 链路彻底模块化——每个大阶段都是一个**清晰、可独立替换的模块**，由显式调用编排串起来。

**方案 A（已确认）**：模块化体现在**清晰的模块边界 + 可替换实现**，而**不是**引入一层通用 `Stage`/`Context`/`Pipeline` 框架。理由（已与用户对齐）：

- 流程稳定，只频繁改"模块内部内容"而非流程顺序 → 通用编排框架的核心价值（声明式增删/重排阶段）用不上。
- 成熟工程优先"边界优于框架"、YAGNI、不重写能用的代码；A 将来可廉价演进到框架，反之难退。
- 符合既有原则：抽象只在真替换点；不过度；不把简单函数包成多层接口；复用现有 registry 风格。

**已确认的执行决策**：
1. Chunk：`get_optimal_nodes` 的 if/elif → **按内容类型的切分策略注册表**（更彻底）。
2. 检索侧：**纳入本轮**（梳理 + 收口边界）。
3. 解析依赖：**新增** `python-pptx` / `openpyxl` / `beautifulsoup4` / `charset-normalizer` 四个轻量兜底依赖。
4. **Docling 是一等解析器，必须实现**（与 LlamaParse 平级，本地 vs 云端）。

---

## 1. 链路总览：现状 → 目标

| 阶段 | 现状 | 目标接口 | 改动级别 |
| --- | --- | --- | --- |
| **Parse** | 内联在 `ingest_document`（`SimpleDirectoryReader` + `extractor_map`） | `DocumentParser` 分层注册表 + `ParseResult` + 解析编排 | **大（新增 + Docling）** |
| **Clean** | `cleaning.py`（`clean_text` + `CleaningProfile`） | 已是模块，确认边界 | 无 |
| **Chunk** | `get_optimal_nodes` 大 if/elif | `Splitter` 策略注册表 | **中（重构）** |
| **Annotate** | `get_optimal_nodes` 末尾 stamp | 留在 chunk 编排里（标注是切分的产物） | 无 |
| **Embed** | `embedding_registry` + `_embed_texts` | 已是 provider 注册表 | 无 |
| **Index** | `_index_nodes` + `_insert_milvus_rows` + `milvus_hybrid` | 已模块化（B6/B7/C） | 无（不动） |
| **Retrieve（plan/recall/fuse）** | `query_planner` + `retriever` + `knowledge_retriever` | 已模块化，梳理边界 | 小 |
| **Rerank** | `reranker_registry` | 已是 provider 注册表 | 无 |
| **Hydrate** | `chunk_hydration` | 已是模块 | 无 |
| **Assemble** | `context_assembly_pipeline`（`AssembledContext` + `[K#]`） | 已是模块 | 无 |
| **Generate（prompt/citation）** | `chat_strategy` + `citation` | 已是模块 | 无 |

**结论**：链路大部分已经是干净模块（得益于 Phase A/B/C）。本轮真正新增/重构的只有 **Parse**（大）和 **Chunk**（中）；其余是**确认/收口边界**，不重写。

---

## 2. 摄取侧

### 2.1 Parse（本轮最大新增）

#### 分层模型（关键）

```
一等解析器（first-class，输出高质量 Markdown + 结构）
  ├─ LlamaParse（云端，需 LLAMA_CLOUD_API_KEY）
  └─ Docling（本地，需 docling 依赖）
        ↑ 部署配置 PARSER_PROVIDER 选其一为「主」，另一个作「文档级 fallback」

轻量兜底（lightweight，按格式，尽量保住可读文本，不要求结构等同一等）
  ├─ PDF        → PyMuPDF
  ├─ DOCX       → python-docx
  ├─ PPTX       → python-pptx
  ├─ XLSX       → openpyxl
  ├─ HTML       → BeautifulSoup
  └─ TXT/CSV/TSV→ charset-normalizer 编码探测 + csv
```

#### 接口

```python
class DocumentParser(Protocol):
    id: str                  # "llamaparse" | "docling" | "pymupdf" | "python_docx" | ...
    tier: Literal["first_class", "lightweight"]
    def supports(self, ext: str, content_type: str) -> bool
    def parse(self, file_path: str) -> ParseResult

@dataclass
class ParseResult:
    markdown: str
    page_map: list[PageSpan]   # best-effort；无页概念格式为空
    warnings: list[str]
    parser_profile: dict       # 见下「观测」
```

`page_map`（`PageSpan = {page, char_start, char_end}`）只在解析器能给出页码、且切分阶段能保持映射时落 `page_start/page_end`；Markdown/HTML/TXT 等保持空（对齐 ingestion 计划 §4.1.4 规则 10）。

#### 解析编排（parser orchestration 层，§4.1.1）

```
resolve_parsers(ext, content_type) -> 有序候选列表：
    [主一等(若可用且支持), 另一等(若已装/配置且支持), 该格式的轻量兜底]

parse_document(file_path):
    for parser in 候选:
        try: return parser.parse(...)（成功即停，记录 actual_parser / fallback_used）
        except: 记 warning，继续下一个
    raise 友好错误（对齐 §4.1.3 各格式失败提示）
```

- ingest 主流程只消费 `ParseResult`，不直接依赖 LlamaParse/Docling 对象模型（§4.1.1）。
- 解析器选择 / fallback / 错误翻译都在编排层，不散落到 ingest。

#### 配置

- `PARSER_PROVIDER = "docling" | "llamaparse"`：选主一等解析器。
- LlamaParse：沿用 `LLAMA_CLOUD_API_KEY`（未配置则该一等不可用，自动退另一等/轻量）。
- Docling：新增 `docling` 依赖 + 初始化错误处理 + 部署说明（镜像体积 / 启动耗时 / 平台兼容，§4.1.3）。

#### 观测（闭合 B4 遗留生产者）

`parser_profile` 落 `metadata_json`，**正好补上 B4 在 `_METADATA_JSON_KEYS` 预留但还没有生产者的 `parser_id`/`parser_profile`/`ocr_used`**：

```
parser_id / actual_parser / fallback_used / legacy_conversion_used
ocr_used / page_count / char_count / duration_ms / error_code
```

#### 实现清单

- `LlamaParseParser`（包现有 LlamaParse 用法）、`DoclingParser`（新）。
- `PyMuPDFParser` / `DocxParser` / `PptxParser` / `XlsxParser` / `HtmlParser` / `TextParser`（轻量兜底）。
- `app/rag/parsing/` 新包：`base.py`(接口+ParseResult) / `registry.py`(候选解析 + 编排) / `parsers/*.py`(各实现)。

#### 删除的旧逻辑

- `ingest_document` 内联的 `extractor_map` + `SimpleDirectoryReader` 解析段 → 改调 `parse_document()`，旧逻辑删除，不新旧并存。

### 2.2 Chunk（策略注册表）

`get_optimal_nodes` 的 if/elif → 按内容类型的 `Splitter` 策略：

```python
class Splitter(Protocol):
    id: str           # "markdown" | "html" | "json" | "code" | "table" | "sentence"
    chunk_type: str   # "text" | "table" | "code"
    def matches(self, file_name: str, source_kind: str, is_markdown_parsed: bool) -> bool
    def split(self, document) -> list[node]
```

- `SPLITTERS` 有序注册表；`select_splitter(doc)` 取第一个 `matches` 的。
- `get_optimal_nodes` 瘦身为编排：`select_splitter → split → 超长二次兜底(embedding tokenizer) → 标注 stamp`（标注/二次兜底逻辑不变，沿用 B4a/B4b/B4c）。
- 现有特例并入对应策略：表格表头重复 → `TableSplitter`；QA 前缀分组（B4d）→ `SentenceSplitter` 策略内部；code tree-sitter（da5437c）→ `CodeSplitter` 策略；heading 溯源 → markdown 策略产出。
- `splitter_id`/`chunk_type`/`splitter_profile` 由策略声明，标注阶段照旧落库。

### 2.3 其余摄取阶段（确认边界，不重写）

- **Clean**：`clean_text` + `CleaningProfile` 已是模块；确认 parse→clean 衔接（清洗作用在 `ParseResult.markdown` 上）。
- **Embed / Index**：`embedding_registry` + `_index_nodes` + `milvus_hybrid` 已模块化（B6/B7/C），**本轮不动**。

---

## 3. 检索侧（梳理 + 收口边界，不大改）

检索侧大部分已模块化，本轮目标是**确认每段是清晰可替换模块 + 收口边界**，而非重写：

| 子阶段 | 模块 | 现状 | 本轮 |
| --- | --- | --- | --- |
| Query plan | `query_planner` | 模块 + `QueryPlan`/`SubQuery` | 确认边界 |
| Recall + Fuse | `retriever`（dense/sparse split、RRF、dedup、fallback） | 模块 + `RetrievalState` | 确认边界 |
| Rerank | `reranker_registry` | provider 注册表 | 无 |
| Hydrate | `chunk_hydration` | 模块 | 无 |
| Assemble | `context_assembly_pipeline` | 模块 + `AssembledContext` + `[K#]` | 无 |
| 入口 facade | `knowledge_retriever` | 薄 facade | 确认边界 |

预期改动：小（可能仅补类型/契约注释、确认 facade 边界）。若发现某段边界不清再单独提。

---

## 4. 与现有 registry 的关系

新增的 `parsing` 与 `splitter` 注册表**沿用现有 provider/registry 风格**，保持一致：

- `embedding_registry`：`PROVIDERS` catalog → `resolve_embedding()` → `build_embedding()`。
- `reranker_registry`：同形 + `RerankerUnavailableError`。
- `milvus_hybrid`：config 驱动的 `HybridCollection`。
- → `parsing`：解析器 catalog → `resolve_parsers()` → 编排；`splitter`：`SPLITTERS` + `select_splitter()`。

---

## 5. 改动范围

**新增**：`app/rag/parsing/` 包；`Splitter` 策略；依赖 `docling` + `python-pptx`/`openpyxl`/`beautifulsoup4`/`charset-normalizer`。
**删除**：`ingest_document` 内联解析；`get_optimal_nodes` 的 if/elif（迁入注册表）。
**不动**：B6/B7/C 的 embed/index/outbox 编排；检索编排主体；所有已模块化的 registry。

---

## 6. 分 part 执行顺序（每 part 两审 + 增量提交）

- **E1 · Parse 抽象骨架**：`DocumentParser`/`ParseResult`/编排 + 把**现有** LlamaParse/PyMuPDF/reader 包进去（**等价替换、行为不变**）+ 闭合 `parser_profile`/`parser_id` 生产者 + 删内联解析。
- **E2 · Docling 一等解析器**：`docling` 依赖 + config（`PARSER_PROVIDER`）+ 初始化错误处理 + 部署说明；接入分层 fallback。
- **E3 · 轻量兜底矩阵**：`python-docx`/`python-pptx`/`openpyxl`/`beautifulsoup4`/`charset-normalizer` 四依赖 + 各 `*Parser`，接入候选链。
- **E4 · Chunk 策略注册表**：`get_optimal_nodes` 重构为 `Splitter` 策略 + 注册表（行为等价，特例并入策略）。
- **E5 · 检索侧边界梳理**：audit + 轻调（按需）。

E1 故意"行为不变"先立骨架与模式；E2/E3 才真正扩格式能力；E4 独立重构 chunk；E5 收口检索。

---

## 7. 评审决策（已确认）

1. **OCR：下一轮做。** 本轮 Docling 仅作 Markdown 解析器，`ocr_used` 恒 `False`。
2. **默认主解析器：`PARSER_PROVIDER` 默认 `docling`**（本地、开箱即用、无需云端 key）。本地项目因已配 LlamaParse key，在本地 `.env`（gitignored）设 `PARSER_PROVIDER=llamaparse` 继续走云端；提交进仓库的默认值是 `docling`。
3. **旧 Office（.doc/.ppt/.xls）+ 图片格式 + OCR：之后一并收尾**（独立后续轮次）。本轮轻量兜底只覆盖现代 OOXML + PDF/HTML/文本/表格。
4. **Docling：本轮（E2）实现。** 尽力完成集成；E2 一并补部署说明（依赖体积 / worker 镜像 / 启动耗时 / 平台兼容）+ 初始化失败的友好降级（Docling 不可用 → 退另一个一等 / 轻量）。

### 7.1 E1 的 ParseResult 契约说明（实现细节）

E1 把现有解析器包进 `ParseResult(markdown + page_map)` 这一目标契约。对**单 Document** 的格式（txt/md/docx/html/json/csv 经 `SimpleDirectoryReader`）行为等价。对**多页 PDF**（现 PyMuPDF 每页一个 Document），改为**合并为单 markdown + page_map**（对齐 §4.1.4 规则 10：页码靠 `page_map` 而非硬切每页）。`page_start/page_end` 的实际写入仍保持现状（暂为空，B1 列可空）——把 `page_map` → chunk 页码的映射留待后续轮次，本轮只是产出 `page_map` 供将来用。这是 E1 唯一的良性行为差异。
