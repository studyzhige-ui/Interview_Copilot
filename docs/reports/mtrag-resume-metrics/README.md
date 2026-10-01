# 简历主指标选择与数据边界

核查日期：2026-09-28。

## 推荐 nDCG@10，辅助 Recall@10

没有行业唯一指标。Top-1/Hit@1有用途，但只看第一条，不充分衡量多片段RAG的证据列表。nDCG@10考虑前十片段的相关性和排名位置，更适合描述混合检索结合重排的最终排序质量。Recall@k衡量正例覆盖，MRR@k衡量首个相关结果的位置；它们不能替代多意图覆盖和答案侧指标。

官方依据：

- [BGE 的 MTEB 评测说明](https://bge-model.com/tutorial/4_Evaluation/4.2.2.html)：检索使用nDCG@k作为主指标。此页面是经典MTEB教程，不用于宣称当前榜单数据集数量。
- [BGE 的 BEIR 评测入口](https://bge-model.com/API/evaluation/beir.html)：示例配置ndcg_at_10与recall_at_100。
- [Elasticsearch Ranking Evaluation](https://www.elastic.co/docs/reference/elasticsearch/rest-apis/search-rank-eval)：提供Precision、Recall、MRR和可归一化DCG等指标。
- [Microsoft Foundry RAG Evaluators](https://learn.microsoft.com/en-us/azure/foundry/concepts/evaluation-evaluators/rag-evaluators)：有qrels时使用Document Retrieval评测NDCG等检索指标，将其与生成侧评测区分。

## 原始v1改写、纯稠密对照混合+重排

聚合方式是按题平均；此前实验主表常用领域宏平均，二者不能混用。复算结果同时保存两种聚合，便于核对。只使用公开正例子集，Human/UN分别报告，不合并重叠数据。未采用后续10%排名融合优化或稀疏替换方案。

| 数据集 | 题数 | 纯稠密 nDCG@10 | 混合+重排 nDCG@10 | 相对提升 | Recall@10 旧→新 |
|---|---:|---:|---:|---:|---:|
| MTRAG Human | 777 | 0.4616 | 0.4931 | 6.84% | 57.00%→59.54% |
| MTRAG-UN 公开正例子集 | 332 | 0.5281 | 0.6100 | 15.50% | 64.49%→72.15% |

相对提升=(新值/旧值-1)×100%，用未舍入数计算。Human绝对增加0.03156，不是增加6.84个百分点。独立从原始排名和qrels重算nDCG/Recall，并与已存指标逐题比对；qrels全为二元正例，线性与指数增益一致。

## 可直接使用的表述

在PostgreSQL单库内实现pgvector（HNSW）稠密检索与SQL BM25评分，结合jieba中文分词、Cross-Encoder重排、分数过滤及多意图结果合并，减少跨检索存储同步环节；在MTRAG Human公开正例子集（777题）的离线对照中，混合检索结合重排相较纯向量检索使nDCG@10由0.4616提升至0.4931，相对提升6.84%。

数字属于离线算法对照，不属于整条生产链路的实测增益。英文评测使用精确向量检索及ASCII BM25，未经过PostgreSQL HNSW，未启用分数过滤和多意图拆分。中文分词在Python中进行，BM25评分在SQL中执行。不存在“消除语义偏斜”或已验证置信度校准的证据。

## 如需完整生产链路归因，必须补测

固定同一批原始文档、问题、金标、用户权限范围、模型和候选预算，在隔离评测库运行四组：HNSW纯向量；HNSW+SQL BM25；再加Cross-Encoder；最后启用分数过滤与多意图合并。

主指标预先固定nDCG@10，辅助Recall@10、实际返回数、按意图证据覆盖率、无答案误检率及P50/P95。拒答/过滤造成的空结果不能从分母删除。过滤评测需要无答案题，多意图覆盖需要意图级证据标注，中文能力需要中文测试集。该补测尚未执行；不能用现有离线结果替代。

已有排名足以复算当前两个检索指标，无需重新调用模型或LLM。数据被多次用于诊断，不称为独立盲测、线上A/B或统计显著。

复算脚本：evaluation/mtrag/resume_metrics.py。输出：results.json、per-query.jsonl。
