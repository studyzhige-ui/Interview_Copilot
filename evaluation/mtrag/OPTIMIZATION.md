# 固定 M3 模型的检索优化

运行环境沿用本轮 GPU Python：
`D:/WorkSoftware/anaconda3/envs/Interview_Copilot/python.exe`。

首次执行 `python -m evaluation.mtrag.optimize_m3 prepare` 冻结实验。
然后执行 `python -m evaluation.mtrag.optimize_m3 all`，中断后同命令续跑。

- 原始语料、标注、改写与已有实验结果保持原样。
- 完整对话和跨数据集重复输入合并连通组，分为调参集659题、验证集450题。
- 24个参数组合加原基线和纯向量参考，共26个配置在调参集比较。
- 调参只使用已有改写，所有新增推理在本机，无付费 API 调用。
- 每通道最多100条，向量权重50%/75%/100%，重排20/30/50/100条，重排长度512/1024。
- 向量长度保持512，重排query预算保持96，batch8，BF16，不设置分数阈值。
- 同一候选对的调参打分缓存共享；验证阶段对冻结的候选列表真实推理计时。
- 仅在调参集选择效果配置和重排不超过30条、512 tokens的低延迟配置。
- 验证阶段比较原基线、冻结效果配置、冻结低延迟配置、纯向量快速参考。
- 验证后不自动重选参数；报告如实呈现退步，不能保证优化必然提升分数。
- 数据此前已经跑过，本轮是内部验证；不声称独立盲测或线上端到端性能。

数据与检查点：`data/evaluation/mtrag/optimization-m3-v1/`。
控制台日志：`data/evaluation/mtrag/optimization-m3-v1/campaign.log`。
完成报告：`docs/reports/mtrag-m3-optimization/README.md`。

PowerShell 查看进度：

```powershell
Get-Content "D:\Projects\Python\Interview_Copilot\data\evaluation\mtrag\optimization-m3-v1\campaign.log" -Tail 15 -Wait
```

`FINISHED optimize report` 表示实验完成。退出日志查看不会停止实验进程。
