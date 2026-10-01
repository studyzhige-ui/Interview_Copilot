# 原始改写下的候选与重排诊断

## 固定基线

使用最初 v1 提示词的完整旧缓存及 BGE-M3 / bge-reranker-v2-m3。未调用 API、未重新推理、未修改提示词或排名。

## 全量阶段定位

查询数：1109。零命中题首个阻断位置：`{"hit": 910, "reranking": 100, "fusion": 26, "retrieval": 73}`。

全部正例片段对分布：`{"retrieval": 505, "fusion": 149, "reranking": 551, "returned": 1774}`。这是官方标注正例的去向，未标注片段不等于不相关。

## 固定候选池的长度诊断

复用659道调参题已保存的512/1024分数，将两者限制在同一份原始融合前50候选中。

统计：`{"queries": 659, "query_truncated": 0, "candidate_pairs": 32950, "clipped_candidate_pairs": 6422, "positive_candidate_pairs": 1381, "clipped_positive_pairs": 321, "lost_positive_pairs": 332, "lost_positive_clipped": 84, "recovered_positive_pairs": 9, "recovered_positive_clipped": 9, "dropped_positive_pairs": 4, "dropped_positive_clipped": 1, "improved": 44, "regressed": 34, "unchanged": 581, "baseline_replay_metric_diff": 0}`。

八个数据集/领域单元等权 nDCG@10：512 = 0.529894；1024 = 0.531795。

## 解释边界

截断存在不代表答案证据必然被截断；长度增加后的排名变化也可能来自竞争片段获得更多文本。
baseline_replay_metric_diff 记录缓存分数在原池复算与历史基线的差异，不能隐去批次/padding数值影响。
这些数据已多次用于诊断，不能当成独立盲测；本轮不选新参数，不将金标用于实际检索。

详细文件：stage-audit.json、length-audit.json、cases.json。
