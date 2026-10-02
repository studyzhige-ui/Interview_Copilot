# MTRAG 检索评测统一配置

> 当前运行器（2026-10-02）只支持 BGE；Qwen 模型配置、执行阶段及适配均已删除。下文保留原实验协议和命令作为历史追溯，Qwen 命令已失效。当前默认配置身份为 `mtrag-bge-retrieval-v2`，比较矩阵为 8 个配置。BGE 基线报告写入 `docs/reports/mtrag-bge-only`，M3 报告写入 `docs/reports/mtrag-bge-m3-only`，不覆盖历史结果。

本目录保留历史 BGE/Qwen 对照实验，独立于产品 RAG 主线。主线模型为 BGE；此目录中的 Qwen 路径和实验适配器不表示主线支持或使用 Qwen 检索模型。

本目录独立于旧题库、生产环境 `.env` 的 RAG 设置和旧 release 评测脚本。
`defaults.json` 是本次实验唯一默认配置；只从环境或项目 `.env` 读取
`DEEPSEEK_API_KEY`，不在文件或报告中保存密钥。

## 固定参数

- 每个通道召回 50，RRF 融合后 50，重排 50，输出前 10。
- 不按最低分或与最高分的分差删除结果；负分也是有效排序分数。
- 只合并重复片段 ID，不按文本去重，以免删除独立 qrel ID。
- 向量归一化，精确余弦检索；RRF k=60，两通道等权。
- BM25 k1=1.2、b=0.75；同一语言分析器必须用于全部配置并记录版本。
- Embedding 输入上限 512 tokens；重排总输入上限 512，查询最多 96。
  特殊 token、Qwen 指令和模板均计入总预算。各 tokenizer 截断率分别报告；
  相同 token 上限不意味着相同可见文字量。本轮是统一预算对比。
- CUDA、batch=8、串行请求；阶段超时 120 秒。失败显式记录，不能按空召回计分。
- 官方片段原文和 ID 保持不变；按题目所属领域搜索完整语料，不只索引正例。
- 每种查询方式只提供一个查询；本轮不做意图拆分和覆盖配额选择。

## 模型与 LLM

本地保留 BGE/Qwen 的两个 Embedding 和两个 Reranker，路径及真实维度见 JSON。
不调用本地 Qwen 生成模型。查询改写统一用官方 DeepSeek API 的 `deepseek-flash`，
temperature=0、thinking=disabled、max_tokens=512、自动重试=0。
模型名以 https://api-docs.deepseek.com/api/create-chat-completion/ 为依据。
云端别名可能变化，缓存记录请求模型、响应模型及服务端 fingerprint（如提供）。
温度 0 不保证跨请求完全确定，因此各检索配置必须共用同一份改写缓存。

## 当前可运行的入口

```powershell
python -m evaluation.mtrag.profile
python -m evaluation.mtrag.rewrite --input data/evaluation/mtrag/queries.jsonl --output data/evaluation/mtrag/rewritten.jsonl --populate-cache
python -m evaluation.mtrag.rewrite --input data/evaluation/mtrag/queries.jsonl --output data/evaluation/mtrag/rewritten.jsonl
python -m unittest evaluation.mtrag.test_contract -v
```

查询输入是规范化 JSONL，每行仅有以下字段，历史截止到当前用户提问：

```json
{"query_id":"example","messages":[{"role":"user","content":"What is service X?"},{"role":"assistant","content":"Prior conversation answer."},{"role":"user","content":"How do I configure it?"}]}
```

不要放入当前参考答案、检索证据、qrels 或未来轮次。适配官方数据时必须核对时间边界；
结构校验无法识别被错误塞进历史文本的答案。

## 跨轮评测复用缓存

- 缓存永久保存在 `data/evaluation/mtrag/rewrites/`，不随报告、向量索引或评测重跑清空，
  没有过期时间。该目录是运行数据，不提交 Git；请随评测数据备份。
- 普通运行默认**只读缓存**，无需 API key；缺失时明确报错，绝不临时调用 LLM。
  首次准备或新增题目时显式使用 `--populate-cache`，只补齐未请求过的条目。
- 缓存键包括完整历史、当前问题、提示词、DeepSeek 模型、生成参数和接口地址。
  不包括题目 ID、数据集名、Embedding/Reranker、Top-k 或报告路径。
  因此 18 个配置以及之后重测共用同一改写，修改检索模型不会重新计费。
- 每个缓存键使用跨进程文件锁；并发进程只允许一个进程发起请求。
- 发送前写入请求记录，收到响应后先持久化原始响应，再解析并原子保存改写。
  如果中断发生在本地解析阶段，下次从已保存响应恢复，无需重发。
- 超时、连接中断或进程退出可能造成“已发起但未保存响应”的状态。此时下次运行停止，
  不会自动重发；需要核对服务商请求记录后人工处理。服务端与本地磁盘无法组成原子事务，
  因此不承诺任何故障情况下都能取得一次且仅一次的成功结果，但不会悄悄重复调用。
- 截断、非法 JSON 或 HTTP 错误也保存响应，不在重测时自动再请求。
- 输出 JSONL 可以使用相同文件名重建，全部成功后才替换旧文件，失败保留旧完整输出。
- 改写缓存命中时，`latency_ms` 为最初 API 调用耗时；不能当作本轮缓存读取耗时，
  在线改写延迟和缓存后检索延迟必须分开报告。

`profile` 校验本地文件并输出 18 个配置；`rewrite` 已实现 DeepSeek 调用和缓存；
`select_ranked_passages` 提供无分数门槛的 Top-k 选择。
完整检索入口已经实现，评测进度和原始结果写入 `data/evaluation/mtrag/`。
runner 显式读取本配置，不导入应用默认参数，记录配置/语料/模型指纹，
分别报告 Human 和 UN。现有生产聊天设置保持独立。

## 全量检索运行入口

本机 GPU Python：`D:/WorkSoftware/anaconda3/envs/Interview_Copilot/python.exe`。
`local_models.py` 为该进程加载工作区内独立的 Transformers 4.57.6 依赖，
不会改写共享 Python 环境。以下 GPU 命令必须使用该解释器。

```powershell
python -m evaluation.mtrag.download
python -m evaluation.mtrag.prepare
# 只有首次缺失改写时使用 --populate-cache；后续运行省略该参数。
python -m evaluation.mtrag.rewrite --input data/evaluation/mtrag/queries.jsonl --output data/evaluation/mtrag/rewritten.jsonl --populate-cache
& D:/WorkSoftware/anaconda3/envs/Interview_Copilot/python.exe -m evaluation.mtrag.freeze_runtime
& D:/WorkSoftware/anaconda3/envs/Interview_Copilot/python.exe -m evaluation.mtrag.run lexical
& D:/WorkSoftware/anaconda3/envs/Interview_Copilot/python.exe -m evaluation.mtrag.embed_corpus --family qwen
& D:/WorkSoftware/anaconda3/envs/Interview_Copilot/python.exe -m evaluation.mtrag.embed_corpus --family bge
& D:/WorkSoftware/anaconda3/envs/Interview_Copilot/python.exe -m evaluation.mtrag.run dense --family bge
& D:/WorkSoftware/anaconda3/envs/Interview_Copilot/python.exe -m evaluation.mtrag.run dense --family qwen
& D:/WorkSoftware/anaconda3/envs/Interview_Copilot/python.exe -m evaluation.mtrag.run rerank --family bge
& D:/WorkSoftware/anaconda3/envs/Interview_Copilot/python.exe -m evaluation.mtrag.run rerank --family qwen
& D:/WorkSoftware/anaconda3/envs/Interview_Copilot/python.exe -m evaluation.mtrag.report
```

编码按 tokenizer 长度分组、重排按候选文本长度分组，仅减少 padding；批量仍为 8，
片段 ID、原文、输入 token 预算和最终排名规则不变。向量按原始语料行号保存。
原始语料中的 41 个空片段保留存档、置零向量并排除检索，无对应正例标签。
运行期间不要清理缓存、替换模型文件或改写固定配置。
# 项目 BGE-M3 补测

项目缓存中的 `BAAI--bge-m3` 和 `BAAI--bge-reranker-v2-m3` 通过
`python -m evaluation.mtrag.m3_campaign prepare` 校验源文件与
`D:/Models/BAAI` 副本的 SHA256，并执行真实 GPU 冒烟检查。
补测使用与原测试相同的 GPU Python 环境。

`python -m evaluation.mtrag.m3_campaign all` 顺序完成 M3 全量建库、
纯向量/混合检索、M3 与 Qwen 交叉重排、覆盖校验和报告。
原 BM25/Qwen 结果和 DeepSeek 改写缓存复用；不调用付费 API。
中断后使用同一命令续跑。日志：`data/evaluation/mtrag/m3-campaign.log`。
完成报告：`docs/reports/mtrag-retrieval-m3/README.md`。
旧 `bge-small-zh-v1.5` / `bge-reranker-base` 结果保留为历史对照，
不得将其标注成项目 M3 模型的结果。M3 本轮仅测 dense，统一512-token预算。
