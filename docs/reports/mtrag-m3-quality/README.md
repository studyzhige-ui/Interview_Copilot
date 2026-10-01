# 失败归因驱动的 M3 检索质量实验

状态：完成。仅检索侧，无答案生成。

## 预先定义的对照

- baseline：原等权融合保留50条，以改写问题重排。
- preserve_channels：保留两路各50条的去重并集（最多100条），取消融合前的候选淘汰；仍用改写问题重排。
- add_original_retrieval：进一步加入原问题两路各50条（最多200条）；仍用改写问题重排。
- add_original_rerank：相同候选分别用改写、原问题重排，按预定75%/25%的RRF融合两次排序。
- 仅调参集选择一个方案，随后与基线在原内部验证集比较；没有根据验证结果再选参数。
- 调参复用已有候选对分数；验证对实际候选列表重新推理。模型、512-token长度、batch8保持固定。
- 复用已有改写和召回，无新增付费调用。数据与内部验证集已多次使用，非全新盲测。

## 调参结果

| 对照 | 八个数据集/领域单元等权 nDCG@10 |
|---|---:|
| baseline | 0.5299 |
| preserve_channels | 0.5285 |
| add_original_retrieval | 0.5285 |
| add_original_rerank | 0.5334 |

冻结选择：add_original_rerank

## 验证结果

| 数据集 | 对照 | nDCG@10 | Recall@10 | P50 ms | P95 ms |
|---|---|---:|---:|---:|---:|
| mtrag-human | baseline | 0.5157 | 0.6172 | 447.8 | 557.8 |
| mtrag-human | add_original_rerank | 0.5133 | 0.6111 | 1574.4 | 3728.5 |
| mtragun-human | baseline | 0.6074 | 0.7081 | 525.1 | 555.1 |
| mtragun-human | add_original_rerank | 0.5952 | 0.7016 | 1870.4 | 3637.1 |

是否通过两套数据 nDCG/Recall 均不下降的质量门槛：False。
门槛通过也不等于统计显著；未通过则保留基线，不自动修改应用。
耗时为新测重排与此前召回耗时相加，不包括改写、加载、生成、并发排队；候选集合构造的CPU时间未单独计入。
问题到证据的逐阶段轨迹和案例见 ../mtrag-m3-diagnosis/。
