# MTRAG 本地检索评测报告

状态：完整检索评测完成（不含最终答案生成）。

## 数据与实验设置

- Human：777 题；UN 当前公开且具有正例标注的部分：332 题。每题运行 18 个配置。
- 官方完整语料：366,479 个片段；qrels ID 校验无缺失。
- 官方文件中的实际领域数量与 README 表格存在差异，以下载文件的校验结果为准。
- 41 个官方空片段保留在语料存档，向量置零并排除检索；它们均不是 qrels 正例。实际可检索非空片段 366,438 个。
- 两套数据存在 15 组相同历史与问题；本轮没有基于测试结果调参。JSON 另给 UN 排除相同输入后的指标。
- CUDA、BF16、batch=8、512-token 共同输入预算；精确余弦召回；每通道50、融合50、重排50、输出10。
- BGE-small-zh 面向中文，本轮英文语料结果不代表整个 BGE 系列或中文场景。
- BM25：小写英文数字分词，无词干化、无停用词过滤；k1=1.2、b=0.75。RRF k=60，等权。
- 最低分、分差过滤、意图分解和文本去重均关闭；重复 ID 合并。
- 查询改写只使用截止当前问题的对话，不读取当前答案、相关片段或 qrels。

## 依赖环境

- 评测进程使用工作区内 Transformers 4.57.6、tokenizers 0.22.2、huggingface-hub 0.36.2、safetensors 0.6.2。
- 原应用 Python 环境未覆盖升级，原环境 `pip check` 通过。四个评测模型均已真实加载并通过推理冒烟检查。
- 激活评测依赖后检查 316 个已安装发行包：315 个库的默认依赖要求兼容；仅原应用 interview-copilot 声明的 Transformers/Hub 旧版本精确锁定与评测版本不同。评测不导入原应用。
- 因此新依赖仅对本评测进程生效；这不构成原应用已兼容新版本的证明。完整检查见 dependency_audit.json。

## 本轮观察

- mtrag-human：本轮 nDCG@10 最高为 `bm25_qwen_rerank_qwen` / `deepseek_rewrite`，得分 0.4715，Recall@10 0.5767。无重排配置中最高为 `qwen_dense` / `deepseek_rewrite`，nDCG@10 0.4322。
- mtragun-human：本轮 nDCG@10 最高为 `bm25_qwen_rerank_qwen` / `deepseek_rewrite`，得分 0.5618，Recall@10 0.6896。无重排配置中最高为 `bm25_qwen` / `deepseek_rewrite`，nDCG@10 0.5068。
- 以上是同一测试集上的描述性比较，未进行显著性检验；不要将很小的分差解读为可靠胜出。

## mtrag-human

质量指标是四领域等权宏平均；耗时为各阶段实测耗时相加，排除模型加载和 DeepSeek。

| 配置 | 查询方式 | nDCG@10 | Recall@10 | Recall@50 | Hit@10 | P50 ms | P95 ms |
|---|---|---:|---:|---:|---:|---:|---:|
| bm25_qwen_rerank_qwen | deepseek_rewrite | 0.4715 | 0.5767 | 0.7390 | 0.7746 | 1138.7 | 1946.6 |
| qwen_dense | deepseek_rewrite | 0.4322 | 0.5283 | 0.7380 | 0.7415 | 40.3 | 55.4 |
| bm25_qwen_rerank_qwen | last_turn | 0.4235 | 0.5124 | 0.6397 | 0.6899 | 1127.4 | 1917.3 |
| bm25_qwen_rerank_bge | deepseek_rewrite | 0.4166 | 0.5238 | 0.7390 | 0.7417 | 219.1 | 278.0 |
| bm25_bge_rerank_qwen | deepseek_rewrite | 0.3938 | 0.4626 | 0.5183 | 0.6690 | 1026.4 | 1927.0 |
| bm25_qwen | deepseek_rewrite | 0.3873 | 0.4856 | 0.7390 | 0.7090 | 44.6 | 68.1 |
| qwen_dense | last_turn | 0.3786 | 0.4549 | 0.6444 | 0.6378 | 40.2 | 54.3 |
| bm25_qwen_rerank_bge | last_turn | 0.3759 | 0.4661 | 0.6397 | 0.6553 | 214.2 | 277.7 |
| bm25_bge_rerank_bge | deepseek_rewrite | 0.3586 | 0.4283 | 0.5183 | 0.6321 | 168.9 | 245.6 |
| bm25_bge_rerank_qwen | last_turn | 0.3368 | 0.3888 | 0.4258 | 0.5647 | 971.8 | 1890.3 |
| bm25_qwen | last_turn | 0.3356 | 0.4220 | 0.6397 | 0.6205 | 43.7 | 67.8 |
| bm25_bge_rerank_bge | last_turn | 0.3093 | 0.3609 | 0.4258 | 0.5372 | 167.9 | 243.2 |
| bm25 | deepseek_rewrite | 0.2605 | 0.3326 | 0.5496 | 0.5188 | 4.3 | 15.2 |
| bm25_bge | deepseek_rewrite | 0.2108 | 0.2891 | 0.5183 | 0.4876 | 14.6 | 38.5 |
| bm25 | last_turn | 0.2032 | 0.2603 | 0.4476 | 0.4060 | 4.0 | 14.2 |
| bm25_bge | last_turn | 0.1703 | 0.2350 | 0.4258 | 0.3900 | 13.8 | 37.5 |
| bge_dense | deepseek_rewrite | 0.0734 | 0.1033 | 0.2174 | 0.2111 | 10.2 | 24.3 |
| bge_dense | last_turn | 0.0644 | 0.0866 | 0.1849 | 0.1706 | 10.3 | 24.2 |

## mtragun-human

质量指标是四领域等权宏平均；耗时为各阶段实测耗时相加，排除模型加载和 DeepSeek。

| 配置 | 查询方式 | nDCG@10 | Recall@10 | Recall@50 | Hit@10 | P50 ms | P95 ms |
|---|---|---:|---:|---:|---:|---:|---:|
| bm25_qwen_rerank_qwen | deepseek_rewrite | 0.5618 | 0.6896 | 0.8549 | 0.8628 | 1275.2 | 1954.7 |
| bm25_bge_rerank_qwen | deepseek_rewrite | 0.5341 | 0.6293 | 0.6949 | 0.8002 | 1178.8 | 1969.7 |
| bm25_qwen | deepseek_rewrite | 0.5068 | 0.6291 | 0.8549 | 0.8172 | 45.0 | 69.3 |
| bm25_qwen_rerank_bge | deepseek_rewrite | 0.5024 | 0.6305 | 0.8549 | 0.8436 | 241.1 | 280.1 |
| qwen_dense | deepseek_rewrite | 0.4974 | 0.6079 | 0.8143 | 0.8058 | 40.5 | 56.7 |
| bm25_qwen_rerank_qwen | last_turn | 0.4808 | 0.5673 | 0.7191 | 0.7427 | 1257.5 | 1952.1 |
| bm25_bge_rerank_bge | deepseek_rewrite | 0.4794 | 0.5778 | 0.6949 | 0.7727 | 204.0 | 246.4 |
| bm25_bge_rerank_qwen | last_turn | 0.4317 | 0.4941 | 0.5469 | 0.6568 | 1163.7 | 1913.8 |
| bm25_qwen_rerank_bge | last_turn | 0.4196 | 0.5076 | 0.7191 | 0.7086 | 240.5 | 282.8 |
| bm25_qwen | last_turn | 0.4190 | 0.5153 | 0.7191 | 0.6706 | 44.4 | 69.0 |
| bm25 | deepseek_rewrite | 0.4076 | 0.5176 | 0.7321 | 0.6926 | 4.7 | 15.4 |
| qwen_dense | last_turn | 0.3853 | 0.4657 | 0.6797 | 0.6617 | 40.7 | 56.1 |
| bm25_bge_rerank_bge | last_turn | 0.3836 | 0.4539 | 0.5469 | 0.6237 | 202.1 | 243.4 |
| bm25 | last_turn | 0.3184 | 0.4048 | 0.5903 | 0.5350 | 4.2 | 14.6 |
| bm25_bge | deepseek_rewrite | 0.3161 | 0.4269 | 0.6949 | 0.6430 | 14.0 | 38.5 |
| bm25_bge | last_turn | 0.2509 | 0.3313 | 0.5469 | 0.5006 | 13.4 | 38.0 |
| bge_dense | deepseek_rewrite | 0.0980 | 0.1405 | 0.2378 | 0.2453 | 9.2 | 23.7 |
| bge_dense | last_turn | 0.0763 | 0.1131 | 0.1856 | 0.2149 | 9.1 | 24.1 |

## 分阶段配对变化

每行使用相同问题比较，Δ 为四领域宏平均之差；改善/持平/退步按逐题 nDCG@10 计数。

| 数据集 | 对照 | Δ nDCG@10 | Δ Recall@10 | 改善 / 持平 / 退步 |
|---|---|---:|---:|---:|
| mtrag-human | bm25: last_turn → deepseek_rewrite | +0.0574 | +0.0724 | 183 / 517 / 77 |
| mtrag-human | bge_dense: last_turn → deepseek_rewrite | +0.0090 | +0.0167 | 77 / 648 / 52 |
| mtrag-human | bm25_bge: last_turn → deepseek_rewrite | +0.0405 | +0.0541 | 181 / 500 / 96 |
| mtrag-human | bm25_bge_rerank_bge: last_turn → deepseek_rewrite | +0.0493 | +0.0674 | 194 / 451 / 132 |
| mtrag-human | bm25_bge_rerank_qwen: last_turn → deepseek_rewrite | +0.0570 | +0.0738 | 209 / 439 / 129 |
| mtrag-human | qwen_dense: last_turn → deepseek_rewrite | +0.0536 | +0.0734 | 225 / 413 / 139 |
| mtrag-human | bm25_qwen: last_turn → deepseek_rewrite | +0.0517 | +0.0637 | 215 / 427 / 135 |
| mtrag-human | bm25_qwen_rerank_bge: last_turn → deepseek_rewrite | +0.0407 | +0.0577 | 218 / 389 / 170 |
| mtrag-human | bm25_qwen_rerank_qwen: last_turn → deepseek_rewrite | +0.0480 | +0.0643 | 236 / 389 / 152 |
| mtrag-human | last_turn: bm25 → bge_dense | -0.1388 | -0.1737 | 73 / 418 / 286 |
| mtrag-human | last_turn: bm25 → qwen_dense | +0.1754 | +0.1946 | 396 / 275 / 106 |
| mtrag-human | last_turn: bge_dense → bm25_bge | +0.1059 | +0.1484 | 269 / 468 / 40 |
| mtrag-human | last_turn: qwen_dense → bm25_qwen | -0.0429 | -0.0329 | 183 / 302 / 292 |
| mtrag-human | last_turn: bm25_bge → bm25_bge_rerank_bge | +0.1391 | +0.1259 | 335 / 380 / 62 |
| mtrag-human | last_turn: bm25_bge → bm25_bge_rerank_qwen | +0.1666 | +0.1537 | 368 / 368 / 41 |
| mtrag-human | last_turn: bm25_qwen → bm25_qwen_rerank_bge | +0.0403 | +0.0441 | 299 / 279 / 199 |
| mtrag-human | last_turn: bm25_qwen → bm25_qwen_rerank_qwen | +0.0879 | +0.0905 | 351 / 280 / 146 |
| mtrag-human | deepseek_rewrite: bm25 → bge_dense | -0.1872 | -0.2294 | 77 / 331 / 369 |
| mtrag-human | deepseek_rewrite: bm25 → qwen_dense | +0.1717 | +0.1956 | 447 / 193 / 137 |
| mtrag-human | deepseek_rewrite: bge_dense → bm25_bge | +0.1374 | +0.1858 | 339 / 398 / 40 |
| mtrag-human | deepseek_rewrite: qwen_dense → bm25_qwen | -0.0449 | -0.0427 | 223 / 242 / 312 |
| mtrag-human | deepseek_rewrite: bm25_bge → bm25_bge_rerank_bge | +0.1478 | +0.1392 | 392 / 291 / 94 |
| mtrag-human | deepseek_rewrite: bm25_bge → bm25_bge_rerank_qwen | +0.1830 | +0.1735 | 421 / 284 / 72 |
| mtrag-human | deepseek_rewrite: bm25_qwen → bm25_qwen_rerank_bge | +0.0293 | +0.0382 | 315 / 215 / 247 |
| mtrag-human | deepseek_rewrite: bm25_qwen → bm25_qwen_rerank_qwen | +0.0842 | +0.0911 | 384 / 211 / 182 |
| mtragun-human | bm25: last_turn → deepseek_rewrite | +0.0892 | +0.1128 | 111 / 188 / 33 |
| mtragun-human | bge_dense: last_turn → deepseek_rewrite | +0.0217 | +0.0274 | 36 / 280 / 16 |
| mtragun-human | bm25_bge: last_turn → deepseek_rewrite | +0.0652 | +0.0956 | 96 / 192 / 44 |
| mtragun-human | bm25_bge_rerank_bge: last_turn → deepseek_rewrite | +0.0958 | +0.1239 | 118 / 164 / 50 |
| mtragun-human | bm25_bge_rerank_qwen: last_turn → deepseek_rewrite | +0.1023 | +0.1352 | 114 / 163 / 55 |
| mtragun-human | qwen_dense: last_turn → deepseek_rewrite | +0.1121 | +0.1422 | 115 / 163 / 54 |
| mtragun-human | bm25_qwen: last_turn → deepseek_rewrite | +0.0878 | +0.1138 | 119 / 154 / 59 |
| mtragun-human | bm25_qwen_rerank_bge: last_turn → deepseek_rewrite | +0.0828 | +0.1229 | 120 / 149 / 63 |
| mtragun-human | bm25_qwen_rerank_qwen: last_turn → deepseek_rewrite | +0.0810 | +0.1222 | 110 / 154 / 68 |
| mtragun-human | last_turn: bm25 → bge_dense | -0.2421 | -0.2917 | 25 / 139 / 168 |
| mtragun-human | last_turn: bm25 → qwen_dense | +0.0669 | +0.0609 | 133 / 103 / 96 |
| mtragun-human | last_turn: bge_dense → bm25_bge | +0.1747 | +0.2182 | 155 / 167 / 10 |
| mtragun-human | last_turn: qwen_dense → bm25_qwen | +0.0337 | +0.0496 | 127 / 118 / 87 |
| mtragun-human | last_turn: bm25_bge → bm25_bge_rerank_bge | +0.1326 | +0.1226 | 163 / 132 / 37 |
| mtragun-human | last_turn: bm25_bge → bm25_bge_rerank_qwen | +0.1808 | +0.1628 | 174 / 125 / 33 |
| mtragun-human | last_turn: bm25_qwen → bm25_qwen_rerank_bge | +0.0006 | -0.0077 | 127 / 106 / 99 |
| mtragun-human | last_turn: bm25_qwen → bm25_qwen_rerank_qwen | +0.0618 | +0.0520 | 130 / 112 / 90 |
| mtragun-human | deepseek_rewrite: bm25 → bge_dense | -0.3096 | -0.3770 | 24 / 87 / 221 |
| mtragun-human | deepseek_rewrite: bm25 → qwen_dense | +0.0898 | +0.0903 | 159 / 71 / 102 |
| mtragun-human | deepseek_rewrite: bge_dense → bm25_bge | +0.2182 | +0.2863 | 205 / 117 / 10 |
| mtragun-human | deepseek_rewrite: qwen_dense → bm25_qwen | +0.0094 | +0.0212 | 138 / 86 / 108 |
| mtragun-human | deepseek_rewrite: bm25_bge → bm25_bge_rerank_bge | +0.1632 | +0.1509 | 197 / 88 / 47 |
| mtragun-human | deepseek_rewrite: bm25_bge → bm25_bge_rerank_qwen | +0.2179 | +0.2024 | 210 / 77 / 45 |
| mtragun-human | deepseek_rewrite: bm25_qwen → bm25_qwen_rerank_bge | -0.0044 | +0.0014 | 134 / 64 / 134 |
| mtragun-human | deepseek_rewrite: bm25_qwen → bm25_qwen_rerank_qwen | +0.0550 | +0.0605 | 141 / 79 / 112 |

逐配置 JSON 另含：Top50 完全漏召回、Top50 命中但 Top10 未命中、Top10 命中三类数量。这有助于区分召回问题和排序问题；Top50 完全没有标注正例时，重排无法补回。

## 改写调用与复用

- 本次唯一成功改写调用：1092 次；缓存目录 `data/evaluation/mtrag/rewrites/`。
- 输入 tokens：672,762；输出 tokens：19,265。不将 token 数冒充实际账单金额。
- 首次改写 P50/P95：598.0/892.3 ms。
- 后续相同查询与改写配置默认只读缓存，不重新发起 API 请求。

## 限制与解释

- UN 仅测已公开的四个领域，不包含尚未发布的 Banking/Telco。
- 两套数据的问题分布不同，不能用两个总分的高低直接断定哪套整体更难。
- 无正例的不可答/欠明确任务不计入普通 Recall/nDCG；本轮未评价拒答能力。
- 512 tokens 是统一预算实验，各 tokenizer 的实际可见文本不同；长文本能力不在此结论范围内。
- 多轮检索分数不能直接证明必须跨文档推理的能力；没有将多个相关片段自动当作必需证据链。
- 对话历史使用官方固定输入；本轮不测线上生成错误在后续对话中的累积效应。
- qrels 不保证穷举所有相关片段，未标注内容按标准做法记零分。
- 延迟是阶段组合估计，BM25 与向量召回采用相加；不能当作生产并行请求的端到端 SLA。
- 完全相同的领域、查询、候选列表和模型会复用重排结果；延迟沿用该相同输入首次实际推理耗时，而非缓存命中耗时。逐题文件标记 reused_identical_inference。
- 首次 API 耗时与本地检索耗时分开；缓存命中不会使首次调用耗时消失。
- 原始逐题排名保存在 data/evaluation/mtrag/runs；运行环境和模型文件哈希见 runtime_manifest.json；源文件哈希见 source_manifest.json。
