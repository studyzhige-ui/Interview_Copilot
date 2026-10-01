# 项目 BGE-M3 与 Qwen 检索对比

状态：全量补测及指标复算完成。

- 主比较使用项目内 bge-m3、bge-reranker-v2-m3，以及原 Qwen 两个模型；旧 BGE 放在历史附表。
- Human 777 题、UN 公开正例任务 332 题，四领域语料 366,479 个片段，排除 41 个空片段。
- 每套数据主比较 18 个配置；另保留旧模型的 10 个历史配置。
- BF16、batch 8、512 tokens、每通道50、融合50、重排50、输出10；不设分数门槛。
- BGE-M3 采用 CLS + L2 归一化，查询不添加指令；本次仅测试 dense，不测试 M3 sparse/ColBERT。
- M3 从项目目录加载；D:/Models/BAAI 下副本已逐文件 SHA256 校验。
- 复用全部 DeepSeek 改写缓存及原 BM25/Qwen 结果，补测新增付费 LLM 调用为0。
- nDCG/Recall 为四领域宏平均，P50/P95 为各阶段耗时相加，排除模型加载、DeepSeek 和答案生成。
- 历史结果复用意味着测量时间不同；延迟用于本机单请求比较，不代表线上并发 SLA。

## 项目 M3 与 Qwen 主比较

### mtrag-human

| 配置 | 查询 | nDCG@10 | Recall@10 | Recall@50 | P50 ms | P95 ms |
|---|---|---:|---:|---:|---:|---:|
| BM25 + BGE-M3 → bge-reranker-v2-m3 | deepseek_rewrite | 0.4900 | 0.5920 | 0.7680 | 450.4 | 585.6 |
| BM25 + Qwen → bge-reranker-v2-m3 | deepseek_rewrite | 0.4881 | 0.5894 | 0.7390 | 436.0 | 604.8 |
| BM25 + BGE-M3 → Qwen3-Reranker-0.6B | deepseek_rewrite | 0.4797 | 0.5946 | 0.7680 | 1147.2 | 2094.8 |
| BM25 + Qwen → Qwen3-Reranker-0.6B | deepseek_rewrite | 0.4715 | 0.5767 | 0.7390 | 1138.7 | 1946.6 |
| BGE-M3 dense | deepseek_rewrite | 0.4582 | 0.5663 | 0.7789 | 14.4 | 26.8 |
| BM25 + Qwen → bge-reranker-v2-m3 | last_turn | 0.4351 | 0.5190 | 0.6397 | 459.1 | 601.7 |
| Qwen3-Embedding-0.6B dense | deepseek_rewrite | 0.4322 | 0.5283 | 0.7380 | 40.3 | 55.4 |
| BM25 + BGE-M3 → bge-reranker-v2-m3 | last_turn | 0.4291 | 0.5150 | 0.6392 | 454.4 | 577.3 |
| BM25 + BGE-M3 → Qwen3-Reranker-0.6B | last_turn | 0.4268 | 0.5189 | 0.6392 | 1140.6 | 2026.4 |
| BM25 + Qwen → Qwen3-Reranker-0.6B | last_turn | 0.4235 | 0.5124 | 0.6397 | 1127.4 | 1917.3 |
| BM25 + BGE-M3 | deepseek_rewrite | 0.4032 | 0.5091 | 0.7680 | 19.0 | 41.4 |
| BM25 + Qwen | deepseek_rewrite | 0.3873 | 0.4856 | 0.7390 | 44.6 | 68.1 |
| BGE-M3 dense | last_turn | 0.3842 | 0.4659 | 0.6537 | 14.3 | 26.9 |
| Qwen3-Embedding-0.6B dense | last_turn | 0.3786 | 0.4549 | 0.6444 | 40.2 | 54.3 |
| BM25 + BGE-M3 | last_turn | 0.3392 | 0.4282 | 0.6392 | 18.3 | 40.8 |
| BM25 + Qwen | last_turn | 0.3356 | 0.4220 | 0.6397 | 43.7 | 67.8 |
| BM25 | deepseek_rewrite | 0.2605 | 0.3326 | 0.5496 | 4.3 | 15.2 |
| BM25 | last_turn | 0.2032 | 0.2603 | 0.4476 | 4.0 | 14.2 |

### mtragun-human

| 配置 | 查询 | nDCG@10 | Recall@10 | Recall@50 | P50 ms | P95 ms |
|---|---|---:|---:|---:|---:|---:|
| BM25 + Qwen → bge-reranker-v2-m3 | deepseek_rewrite | 0.5965 | 0.7112 | 0.8549 | 540.7 | 602.0 |
| BM25 + BGE-M3 → bge-reranker-v2-m3 | deepseek_rewrite | 0.5954 | 0.7064 | 0.8581 | 528.4 | 575.0 |
| BM25 + Qwen → Qwen3-Reranker-0.6B | deepseek_rewrite | 0.5618 | 0.6896 | 0.8549 | 1275.2 | 1954.7 |
| BM25 + BGE-M3 → Qwen3-Reranker-0.6B | deepseek_rewrite | 0.5611 | 0.6931 | 0.8581 | 1237.2 | 2129.7 |
| BM25 + BGE-M3 | deepseek_rewrite | 0.5225 | 0.6386 | 0.8581 | 19.0 | 44.0 |
| BGE-M3 dense | deepseek_rewrite | 0.5171 | 0.6282 | 0.8294 | 14.2 | 28.4 |
| BM25 + Qwen | deepseek_rewrite | 0.5068 | 0.6291 | 0.8549 | 45.0 | 69.3 |
| Qwen3-Embedding-0.6B dense | deepseek_rewrite | 0.4974 | 0.6079 | 0.8143 | 40.5 | 56.7 |
| BM25 + Qwen → bge-reranker-v2-m3 | last_turn | 0.4874 | 0.5724 | 0.7191 | 536.5 | 598.7 |
| BM25 + BGE-M3 → bge-reranker-v2-m3 | last_turn | 0.4865 | 0.5600 | 0.7129 | 520.7 | 577.2 |
| BM25 + Qwen → Qwen3-Reranker-0.6B | last_turn | 0.4808 | 0.5673 | 0.7191 | 1257.5 | 1952.1 |
| BM25 + BGE-M3 → Qwen3-Reranker-0.6B | last_turn | 0.4755 | 0.5679 | 0.7129 | 1230.4 | 2052.1 |
| BM25 + Qwen | last_turn | 0.4190 | 0.5153 | 0.7191 | 44.4 | 69.0 |
| BM25 + BGE-M3 | last_turn | 0.4132 | 0.5011 | 0.7129 | 18.5 | 41.1 |
| BM25 | deepseek_rewrite | 0.4076 | 0.5176 | 0.7321 | 4.7 | 15.4 |
| BGE-M3 dense | last_turn | 0.4030 | 0.4659 | 0.6709 | 14.1 | 27.9 |
| Qwen3-Embedding-0.6B dense | last_turn | 0.3853 | 0.4657 | 0.6797 | 40.7 | 56.1 |
| BM25 | last_turn | 0.3184 | 0.4048 | 0.5903 | 4.2 | 14.6 |

## 旧 BGE 历史对照

### mtrag-human

| 配置 | 查询 | nDCG@10 | Recall@10 | Recall@50 | P50 ms | P95 ms |
|---|---|---:|---:|---:|---:|---:|
| BM25 + Qwen → bge-reranker-base [旧对照] | deepseek_rewrite | 0.4166 | 0.5238 | 0.7390 | 219.1 | 278.0 |
| BM25 + bge-small-zh-v1.5 → Qwen [旧对照] | deepseek_rewrite | 0.3938 | 0.4626 | 0.5183 | 1026.4 | 1927.0 |
| BM25 + Qwen → bge-reranker-base [旧对照] | last_turn | 0.3759 | 0.4661 | 0.6397 | 214.2 | 277.7 |
| BM25 + bge-small-zh-v1.5 → bge-reranker-base [旧对照] | deepseek_rewrite | 0.3586 | 0.4283 | 0.5183 | 168.9 | 245.6 |
| BM25 + bge-small-zh-v1.5 → Qwen [旧对照] | last_turn | 0.3368 | 0.3888 | 0.4258 | 971.8 | 1890.3 |
| BM25 + bge-small-zh-v1.5 → bge-reranker-base [旧对照] | last_turn | 0.3093 | 0.3609 | 0.4258 | 167.9 | 243.2 |
| BM25 + bge-small-zh-v1.5 [旧对照] | deepseek_rewrite | 0.2108 | 0.2891 | 0.5183 | 14.6 | 38.5 |
| BM25 + bge-small-zh-v1.5 [旧对照] | last_turn | 0.1703 | 0.2350 | 0.4258 | 13.8 | 37.5 |
| bge-small-zh-v1.5 dense [旧对照] | deepseek_rewrite | 0.0734 | 0.1033 | 0.2174 | 10.2 | 24.3 |
| bge-small-zh-v1.5 dense [旧对照] | last_turn | 0.0644 | 0.0866 | 0.1849 | 10.3 | 24.2 |

### mtragun-human

| 配置 | 查询 | nDCG@10 | Recall@10 | Recall@50 | P50 ms | P95 ms |
|---|---|---:|---:|---:|---:|---:|
| BM25 + bge-small-zh-v1.5 → Qwen [旧对照] | deepseek_rewrite | 0.5341 | 0.6293 | 0.6949 | 1178.8 | 1969.7 |
| BM25 + Qwen → bge-reranker-base [旧对照] | deepseek_rewrite | 0.5024 | 0.6305 | 0.8549 | 241.1 | 280.1 |
| BM25 + bge-small-zh-v1.5 → bge-reranker-base [旧对照] | deepseek_rewrite | 0.4794 | 0.5778 | 0.6949 | 204.0 | 246.4 |
| BM25 + bge-small-zh-v1.5 → Qwen [旧对照] | last_turn | 0.4317 | 0.4941 | 0.5469 | 1163.7 | 1913.8 |
| BM25 + Qwen → bge-reranker-base [旧对照] | last_turn | 0.4196 | 0.5076 | 0.7191 | 240.5 | 282.8 |
| BM25 + bge-small-zh-v1.5 → bge-reranker-base [旧对照] | last_turn | 0.3836 | 0.4539 | 0.5469 | 202.1 | 243.4 |
| BM25 + bge-small-zh-v1.5 [旧对照] | deepseek_rewrite | 0.3161 | 0.4269 | 0.6949 | 14.0 | 38.5 |
| BM25 + bge-small-zh-v1.5 [旧对照] | last_turn | 0.2509 | 0.3313 | 0.5469 | 13.4 | 38.0 |
| bge-small-zh-v1.5 dense [旧对照] | deepseek_rewrite | 0.0980 | 0.1405 | 0.2378 | 9.2 | 23.7 |
| bge-small-zh-v1.5 dense [旧对照] | last_turn | 0.0763 | 0.1131 | 0.1856 | 9.1 | 24.1 |

## 解释范围

英文检索评测；无正例任务排除，不测拒答或最终回答正确率。统一512-token预算不代表完整长上下文能力。两套数据有15组相同对话输入，不能当作完全独立测试。qrels不是所有相关片段的穷举。未做显著性检验。
