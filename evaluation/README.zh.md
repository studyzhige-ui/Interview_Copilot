# RAG 评测

本目录验证实际生产链路：上传后的解析、清洗、分块、Embedding、Milvus
Dense/BM25 混合检索、RRF、CrossEncoder 重排、证据门、流式回答与引用。评测代码不会
把金标词或答案偷偷加入检索请求。

## 评测边界

- 语义语料由固定 SHA-256 的官方技术文档组成，覆盖 HTML、Markdown、PDF 和 TXT。
- PDF 是必须通过的输入格式之一，不是唯一格式。Community 对支持的结构化文档默认
  使用 Docling；完整转换失败时，PDF 整份回退到 PyMuPDF。LlamaParse 只在用户显式
  配置时启用。
- DOCX、PPTX、XLSX、CSV/TSV、JSON、代码、图片 OCR 和旧版 Office 转换由格式保真
  测试覆盖；这类测试验证内容不丢失，不冒充大规模语义检索分数。
- Community 运行时仍支持纯 CPU，但维护者的完整质量和性能验收统一使用 CUDA，避免
  用极慢的本地大模型 CPU 基准浪费时间。

## 数据集与金标

`corpus_manifest.json` 固定来源、许可证和文件哈希；`rag_dataset.jsonl` 保存中英文、
三档难度、可回答问题、困难负例、路由负例以及显式单意图/多意图样本。

每个可回答样本使用 `evidence_groups` 标注一个或多个原子证据单元：

```json
{
  "source_files": ["one.html", "two.pdf"],
  "evidence_groups": [
    {
      "source_file": "one.html",
      "alternatives": [
        {"all_of": ["原文短语 A", "原文短语 B"]},
        {"all_of": ["含义相同的另一段原文"]}
      ]
    },
    {
      "source_file": "two.pdf",
      "alternatives": [{"all_of": ["原文短语 C"]}]
    }
  ]
}
```

一个证据组表示必须覆盖的一个原子事实；组内 `all_of` 是 AND，同组多个
`alternatives` 是语义等价的 OR 表达。每个 alternative 的短语必须同时出现在同一个
chunk；不同证据组可以位于不同 chunk 或不同文档。系统重建索引后才把这些原文证据
映射到当前 chunk，因此金标不会固定或泄露 chunk id。
检索只看到用户问题和生产规划器输出，金标只在结果返回后判分。这属于标准 qrels，
不是作弊。

数据按语义组和来源文档隔离 calibration/test；中英文同义题、同一来源及多意图题组不
允许跨 split。数据集由独立 agent 构建，脚本只负责 schema、分布、原文证据和泄漏校验：

```powershell
python -m evaluation.download_corpus
python -m evaluation.validate_rag_dataset
```

运行语料位于 `data/evaluation/corpus/`。正式索引只使用隔离账号 `eval_user_a`，租户
隔离探针使用另一账号，不会访问普通用户知识库。

## 固定发布配置

本轮不再反复选择 chunk、overlap 或候选池。Community 发布配置固定为：

```dotenv
RAG_CHUNK_TOKENS=384
RAG_CHUNK_OVERLAP=64
RAG_CANDIDATE_COUNT=20
RAG_FINAL_COUNT=3
```

384 是 passage 的目标上限；重排器总输入上限为 512 token，并为 query 和特殊 token
保留空间。所有结构化解析结果最终都经过同一个 token 安全门，不存在“普通文档 512、
结构化文档 1024”的双重规则。

`RAG_MIN_SCORE` 和单意图的 `RAG_SCORE_MARGIN` 仍需在 calibration split 上校准，因为
CrossEncoder 分数不是概率，模型或检索文本改变后分布也会改变。只有 calibration 的
全部门禁通过，程序才会打开一次 test split；test 结果不会反向参与参数选择。

固定 GPU 发布验收会一次完成：校验语料哈希、冻结规划结果、重建 384/64 索引、预热、
校准证据门、验证租户隔离、运行一次留出检索，并写出不可混用的索引/代码/硬件指纹。

```powershell
python -m evaluation.rag_release
```

默认发布报告是 `data/evaluation/release/cuda.json`。失败报告不能作为生成或 RAGAS 的
`--profile`。更换 `--output` 也不能重新打开同一 held-out：程序在运行 test 前会按
代码、数据、模型与环境身份原子领取一次 campaign。只有先改进真实链路并准备新的
独立留出数据，才能开始下一轮发布验收。

## RAGAS：先 1 条兼容性检查，再正式 50 条

回答模型使用平台内部模型或维护者显式设置的 `EVAL_GENERATOR_*`，不读取普通用户
BYOK。裁判必须是不同模型；缺少独立配置时会在付费前失败。

```dotenv
EVAL_GENERATOR_API_KEY=
EVAL_GENERATOR_API_BASE=
EVAL_GENERATOR_MODEL=
EVAL_JUDGE_API_KEY=
EVAL_JUDGE_API_BASE=
EVAL_JUDGE_MODEL=
EVAL_JUDGE_CONCURRENCY=4
```

```powershell
# 先对固定首样本真实调用 generator 和 judge；失败不会解锁正式评测
python -m evaluation.eval_runner --layer generation --ragas-profile check `
  --profile data/evaluation/release/cuda.json --report

# 仅在同一契约的 check 成功后运行固定 50 条；首样本回答与 5 项指标强制复用
python -m evaluation.eval_runner --layer generation --ragas-profile formal `
  --profile data/evaluation/release/cuda.json --report
```

正式 50 指 50 个固定问题。每个问题计算 Faithfulness、Context Precision、Context
Recall、Answer Relevancy 和 Factual Correctness，因此供应商请求数通常大于 50。逐样本
回答和逐指标 checkpoint 只复用已成功持久化且契约完全一致的结果；请求已发出但本地
未确认的崩溃窗口会标为 unknown，默认停止，不会自动重复付费。

## 指标怎么读

- Candidate evidence-group recall：重排前的候选池找全了多少原子证据；低说明
  Embedding、BM25、RRF、规划 query 或候选池有问题。
- Hit@3：Top-3 是否至少含一个正确证据。
- MRR@3：第一个正确证据越靠前越高；排第 1/2/3 分别贡献 1、1/2、1/3。
- nDCG@3：同时评价多个证据是否被找全并排在前面。
- Evidence-group recall@3：Top-3 覆盖了多少原子证据组；多文档问题不会因只命中一边
  而被算作完整召回。
- Document recall@3：应命中的来源文档有多少出现在 Top-3。
- Context evidence precision：实际送给回答模型的 chunk 中，有效且不重复的证据占比。
- Hard-negative FPR：语料没有答案时仍放行上下文的比例。
- Faithfulness：答案中的事实能否由上下文支持。
- Context Precision / Recall：上下文是否少噪声，以及参考答案所需证据是否找全。
- Answer Relevancy / Factual Correctness：答案是否回应问题、事实是否正确。
- TTFT：回答请求到首个非空 token；端到端 TTFT 另含冻结的规划延迟和当前检索延迟。
- TPOT：首 token 之后每个输出 token 的平均耗时；吞吐量为每秒输出 token 数。

最终实测数字只写入本次发布报告和最新的 `docs/reports/rag-evaluation-*.md`，不在本
说明中长期复制，避免代码、数据和旧基线互相矛盾。
