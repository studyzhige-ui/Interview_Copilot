# 转向召回能力：BGE-M3 官方稀疏检索

## 原因与边界

此前90%重排+10%原检索排名的全量nDCG收益只有约0.005，属于小幅回归改善，不作为主要优化成果。停止继续调整这一权重。

当前BGE-M3适配器明确只使用CLS稠密向量；原模型目录没有sparse_linear.pt。稠密推理不需要这个头，因此这不说明旧稠密向量无效。官方模型另外提供学习词项权重的稀疏功能，可以作为尚未测试的召回通道。

来源：[BAAI官方模型说明](https://huggingface.co/BAAI/bge-m3)，[官方稀疏计算源码](https://github.com/FlagOpen/FlagEmbedding/blob/fd1a2bdf69488ffebe0327999d4400d8c8058a0b/FlagEmbedding/finetune/embedder/encoder_only/m3/modeling.py)。这只是测试依据，不保证在MTRAG上提升。

## 已完成验证

- 官方模型版本：5617a9f61b028005a4858fdac845db406aefb181。
- 主权重与分词器SHA256匹配该版本。
- 仅补充3516字节的sparse_linear.pt，SHA256校验通过；保存在独立实验目录，没有修改原模型目录或旧向量索引。
- 使用相同本地模型隐层输出，按官方线性层+ReLU计算词项权重，重复词取最大值，排除官方指定特殊词元。
- 小样本适配输出与固定版本官方函数逐元素相同；相关文本相似度检查通过。
- 四领域语料SHA256、1,109条原始v1改写身份通过核验；稀疏矩阵点积与空行测试通过。

## 单变量实验

旧基线：BM25前50 + M3稠密前50 → 等权RRF(60)保留50 → M3重排512 → 前10。

本轮：M3稀疏前50 + 同一M3稠密前50 → 同样融合和重排。

最初提示词及旧改写缓存不动；不启用新版提示词，不加原问题双重排，不叠加10%排序融合，不增加最终候选预算。保持官方片段ID与相关性标签。

固定一个方案，不跑权重网格。分别输出调参集、内部验证集和全量结果。实质收益门槛预设为：内部验证两套数据nDCG@10与Recall@10均不下降，且两套数据领域宏平均nDCG增量的平均值至少0.02。门槛是工程决策标准，不等于统计显著性；已有划分不是独立盲测。

## 自主运行

入口：`python -m evaluation.mtrag.sparse_m3 all`，GPU解释器为 `D:/WorkSoftware/anaconda3/envs/Interview_Copilot/python.exe`。

阶段：完整语料稀疏索引 → 稀疏查询与融合 → M3重排 → 自动报告。索引按1024条保存检查点，排名逐题保存，独立后台进程运行。

目录：`data/evaluation/mtrag/sparse-m3-v1/`。

- status.json：阶段/完成/失败状态。
- index-progress.json：当前领域的索引完成量。
- campaign.log / campaign-error.log：运行日志。
- manifest.json / upstream.json / smoke.json：冻结输入、官方来源与检查结果。
- index/：新的稀疏索引，未替换旧索引。
- runs/：逐题召回与重排。为复用原runner，内部融合文件名仍为bm25_bge_m3，但其中actual_retriever明确标为m3_sparse_plus_dense；此次融合没有使用BM25。
- results.json / README.md：全量完成后自动生成。

本轮没有付费LLM请求，但索引重编码需要本地GPU计算。当前稀疏单独前向，稠密检索复用旧结果；报告会明确区分新测时间与历史稠密时间，不能声称新增能力没有延迟。只有效果值得保留后，才有理由把稠密与稀疏合并到同次前向做在线工程优化。
