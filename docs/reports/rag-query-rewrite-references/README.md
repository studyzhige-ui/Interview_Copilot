# RAG 查询改写参考资料核查

核查日期：2026-09-27。范围：官方文档、OpenAI Codex 指定模块，以及用户指定的本地 Claude Code 源码。此次仅研究，没有修改检索链路或调用付费改写 API。

## 结论

没有查到跨厂商统一的 RAG 查询改写标准或标准提示词。以下是各厂商、框架的官方实现与指导，不能混称为统一标准。

最贴合本项目的是多轮问题独立化：只补足理解当前问题所必需的历史信息。查询扩展、工具发现、历史检索、上下文压缩和文档块上下文化是不同环节。

## 官方资料

| 来源 | 已核实内容 | 对本项目的意义 |
|---|---|---|
| [OpenAI Retrieval](https://developers.openai.com/api/docs/guides/retrieval) | 搜索支持 `rewrite_query=true`，通过 `search_query` 返回改写结果；该章节未公开内部完整改写提示词 | 保留原问题和实际搜索问题，使改写可追踪；不能据此获得一套内部提示词 |
| [LangChain 官方示例源码](https://github.com/langchain-ai/langchain/blob/master/libs/langchain/langchain_classic/chains/conversational_retrieval/base.py) | 示例要求结合历史将最新问题独立化，不回答问题；需要才改写，否则原样返回 | 最直接的多轮查询改写参考。位置是 classic 模块示例，不代表建议采用旧链类作为新架构 |
| [LangChain history-aware retriever](https://github.com/langchain-ai/langchain/blob/master/libs/langchain/langchain_classic/chains/history_aware_retriever.py) | 无历史直接检索；有历史用提示词和模型产生搜索问题 | 可借鉴显式的查询处理分支 |
| [Azure Query Rewrite](https://learn.microsoft.com/en-us/azure/search/semantic-how-to-query-rewrite) | 预览功能，支持拼写修正与同义表达，原查询和改写查询共同参与检索；提醒精确标识符或产品代码可能在改写中丢失 | 保护精确词；但多查询召回不等于必须让未消解指代的原问题参与重排 |
| [Anthropic Contextual Retrieval](https://www.anthropic.com/engineering/contextual-retrieval) | 根据完整文档为片段生成简短上下文，再用于向量与 BM25 索引 | 解决片段脱离文档后缺少实体、范围等上下文的问题；这是文档侧处理，不是查询改写 |
| [Anthropic Context Engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) | 通过路径、元数据、搜索工具按需载入上下文；介绍 Claude Code 的渐进式读取方式 | 借鉴范围过滤和按需上下文。运行时多轮搜索也可能增加延迟 |

## Codex 源码

检查版本：`985cf47a4eb6084b2ff6b30ebdb1216acda85bb4`。根据仓库目录树选择工具搜索、文件搜索、记忆和提示词相关文件核查；并非逐行审计全仓库。

- [tool_description.md](https://github.com/openai/codex/blob/985cf47a4eb6084b2ff6b30ebdb1216acda85bb4/codex-rs/core/templates/search_tool/tool_description.md)：BM25 检索连接器工具元数据，并加载匹配的工具定义。这是工具发现，不是文档问答改写。
- [file-search/README.md](https://github.com/openai/codex/blob/985cf47a4eb6084b2ff6b30ebdb1216acda85bb4/codex-rs/file-search/README.md)：文件路径模糊匹配，使用 ignore 与 nucleo-matcher；不能当成向量检索方案。
- [memories/read_path_v2.md](https://github.com/openai/codex/blob/985cf47a4eb6084b2ff6b30ebdb1216acda85bb4/codex-rs/ext/memories/templates/memories/read_path_v2.md)：历史摘要可帮助定位用户偏好、纠正和工作背景；历史不能证明当前代码行为，必要时回到源文件核实。

检查范围内没有找到适合直接用于本项目多轮文档 RAG 的独立查询改写模板。不能据此声称整个项目绝对没有其他相关实现。

源码缓存位于 `data/research/query-rewrite/codex/`，下载文件按目录树中的 Git blob SHA 校验。

## 本地 Claude Code 源码

路径：`D:\Projects\TypeScript\Claude Code\src`。HEAD：`58231dcce408f805c645cfbc352d2876b517223b`。仓库 remote 不是 Anthropic 官方仓库，其来源与官方版本对应关系没有独立验证，因此以下结论仅针对本地副本。

| 文件 | 实际用途 | 可借鉴与限制 |
|---|---|---|
| `utils/agenticSessionSearch.ts:15` | 模型从历史会话元数据和摘录中选择相关会话；匹配标签、标题、分支等 | 借鉴结构化元数据。但提示词偏向宽松召回，不宜直接用于 RAG 前十结果排序 |
| `tools/ToolSearchTool/prompt.ts` | 工具查询支持精确选择、关键词与必选词 | 明确实体或工具名可以使用精确匹配约束 |
| `tools/ToolSearchTool/ToolSearchTool.ts:194` | 精确工具名优先；支持必选词过滤、字段匹配加权 | 属于工具检索实现，不能照搬权重到文档检索 |
| `memdir/memdir.ts:404` | 建议使用错误消息、文件路径、函数名等具体词搜索历史 | 保留信息量高的精确词，并按目标缩小搜索范围 |
| `services/compact/prompt.ts:61` | 会话压缩保留用户请求、纠正、最近任务和待办 | 可借鉴历史处理时保护最新意图；本身不是查询改写提示词 |

对 TS、TSX、Markdown 搜索改写、独立问题、语义检索等相关术语，并检查上述模块后，没有找到专用的文档 RAG 多轮查询改写提示词。

## 对当前检索实验的建议——本项目推导规则，非官方原文

1. **当前问题优先**：保留当前明确出现的实体、标识符、数字、否定条件及范围；历史不能擅自替换当前明确对象。
2. **历史最小补全**：只用历史消解指代和省略；遇到话题切换不要继续套用旧主题。
3. **完整问题不改写**：已有独立语义时原样保留；不把简短等同于不完整。
4. **不回答、不补造事实**：改写产物只表达用户问题，不能混入猜测的答案或用户未提出的条件。
5. **指代无法确定时显式标记不确定**：后续采用什么澄清或保留策略应单独定义并验证，不强行编出一个实体。
6. **分开定义召回与重排输入**：原问题可作为召回分支的候选方案，但未消解的原问题不应无条件作为独立重排依据。该判断来自本地固定候选池实验，不是 Azure 的原文规则。
7. **记录与缓存可复现**：记录原问题、使用的历史、改写文本、模型和提示词版本。变更提示词后使用新版本缓存键，相同完整输入继续复用结果，避免旧缓存冒充新实验。

### 与已经确认的失败对应

- 当前显式实体被历史实体替换：优先修正问题 1、2，配合正确指代消解案例做双向回归检查。
- `How many times is it there in the bible?`：已有正确改写；固定候选池下，加入未消解原问题重排使 nDCG@10 从 0.7845 降到 0.1413。此例需要修正重排输入契约，不应继续修改正确的改写。
- `Explain Spark.`：原问题与改写相同，扩候选后正例被挤出前十。改写规则不能解决全部排序问题。
- 相同文本不同 ID 的标注覆盖问题：保持官方 qrels，另设诊断结果，不通过改写或修改标签掩盖。

证据见 [上一轮诊断](../mtrag-m3-investigation/README.md)。这些规则尚未作为新方案运行；不能声称已带来质量提升。后续应先做定向回归，再用新的独立评估数据确认泛化；已有验证集已用于事后诊断。
