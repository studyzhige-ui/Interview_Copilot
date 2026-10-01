# 新版查询改写的 BGE-M3 检索重跑

本轮只检验查询改写变化。固定本地项目模型 BGE-M3 和 bge-reranker-v2-m3，读取已完成的 v2.1 改写；没有 LLM 请求、Qwen 推理或答案生成。

## 固定条件

- 数据：1,109 条有公开正例标注的题目，Human 777 条、UN 332 条；分别报告。
- 全量领域语料与官方片段 ID 不变；复用既有 BGE-M3 文档向量。
- BM25 与向量各召回 50；等权 RRF，常数 60；融合保留 50；M3 重排输出前 10。
- embedding/reranker 输入预算 512，reranker 查询预算 96，batch=8。
- 不启用此前未通过验证的全量扩候选和原问题双重排。
- 对照是旧版改写在相同原基线下的既有结果。本次重新运行全部新版查询，包括文字没有变化的查询，独立记录本轮检索延迟。

## 验证与运行

启动前 15 项输入、缓存和指标测试通过；逐文件校验两个本地 M3 模型与冻结模型清单一致。1,109 条新版改写通过完整覆盖和请求身份校验。各领域向量进入推理前还会验证维度、归一化以及抽样文本—向量对应关系。

原评测 runner 增加显式改写文件和结果目录参数，默认行为保持旧实验路径。新入口 `evaluation/mtrag/rewrite_retrieval.py` 显式使用新版路径、独立结果目录及冻结输入指纹，不覆盖旧排名和旧改写。

后台命令：

```powershell
& 'D:/WorkSoftware/anaconda3/envs/Interview_Copilot/python.exe' -X utf8 -u -m evaluation.mtrag.rewrite_retrieval all
```

阶段：输入与模型核验 → BM25 → BGE-M3 向量检索与融合 → M3 重排 → 自动报告。结果逐题保存，可用同一命令继续未完成阶段；输入变更会拒绝混入既有结果。

## 查看状态和结果

目录：`data/evaluation/mtrag/retrieval-rewrite-v2.1/`。

- `status.json`：执行阶段和最终状态；`complete` 才表示全部完成。
- `campaign.log` / `campaign-error.log`：进度与错误日志。
- `runs/`：BM25、向量、融合、重排的逐题排名、指标和耗时。
- `comparison.json`：完成后输出新旧分阶段、分数据集、分领域及内部划分对照。
- `per-query.json`：完成后输出重排阶段逐题 nDCG 变化及前十片段。
- `README.md`：完成后自动生成可读报告，包含 nDCG@10、Recall@10 和 P50/P95 延迟。

延迟统计排除改写 API、模型加载和索引构建；旧基线延迟来自此前运行，可能受机器负载差异影响。已有数据用于过诊断及提示词修订，结果属于回归对照，不是独立盲测。保持官方相关性标签不变，不因重复文本或疑似漏标而改写评分标准。
