# 工程收尾与面试追问依据（2026-10-13）

范围是当前本地 Interview Copilot 工作树，不代表已发布 GitHub 版本。源码可见、测试通过和真实业务效果是三种不同证据。历史性能指标不得替代当前验收。

## 本次修复

### 录音提取检查点的事务边界

旧链路先提交转写 projection／complete 状态，再独立插入 QA；重试又以现有行数决定跳过多少新结果。旧 partial QA 若仍存在，可能被新完成状态覆盖而未整体替换。根因是把一个逻辑检查点拆成两次事务，并用行数代替结果身份。

当前模型调用在事务外完成；`publish_recording_qa` 在一个短事务内锁住父记录、检查 review generation 和当前 transcript，整体替换 QA，再发布结构与完成状态。任一步失败全部回滚，旧任务不能写入新转写结果。删除旧 `set_transcript_projection` 入口，不保留两条发布路径。模拟面试仍从已有对话消息构造 QA，不经过录音提取。

验证包含：旧 partial 替换；插入 flush 后主动失败的回滚；当前转写已变化的拒绝；真实 PostgreSQL 中 generation 变化后旧任务拒绝、新任务正常提交。SQLite 用例不代替 PostgreSQL 验证。

### 用户显示与事实说明

录音提取产生 project／opening／career 等阶段，但报告原有标签映射只覆盖模拟面试阶段，页面出现英文内部枚举。阶段标签统一放在既有面试 domain specification 中，API 和分析服务共享，已有记录无需改库。

更正两处文档事实：Compose 是四个 Worker 服务承接五类队列；Memory 自动生产默认关闭，但已有有效记忆召回由账户／会话独立控制。此前“运行时不生成或召回”的表述不准确。同时删除架构文档对已不存在的 test_architecture 测试目录及完整无环导入检查的过时宣称；现有测试只验证明确列出的边界。

## 面试时必须讲得清楚的设计

| 追问 | 当前实现与取舍 | 源码／验证入口 |
| --- | --- | --- |
| 为什么不是微服务？ | 模块化单体共用模型和业务服务；按工作负载拆执行进程。降低跨服务事务和部署成本，代价是共享代码发布与数据库边界需要约束。 | `docker-compose.yml`、`backend/app/worker/` |
| 为什么用 Celery？ | 长模型任务离开 HTTP 生命周期，按 turns／transcription／pipeline／background／default 分流。Redis 传输任务，数据库保存事实。队列隔离不等于所有任务都只执行一次。 | `task_queue/celery_app.py`、`conversation/application/turn_store.py` |
| Agent 与普通工作流有什么区别？ | Agent 根据模型输出及工具中间结果继续选择动作；简历解析、上传录音复盘等固定业务步骤由服务编排。不能把一次 LLM 调用或固定流水线宣传成自主 Agent。 | `conversation/agent_strategy.py`、`conversation/chat_strategy.py` |
| Agent 和回合执行器如何分工？ | 策略负责模型／工具循环；执行器监督回合、取消和事件交付；存储服务管理 durable 状态及租约。SSE 断开与业务完成是不同事件。 | `conversation/engine.py`、`conversation/application/turn_executor.py`、`turn_store.py` |
| 工具重试为什么危险？ | 外部副作用可能已经发生但响应丢失。必须区分失败和结果未知，不能盲目再发送。工具执行记录和策略检查负责约束，不能承诺外部世界 exactly-once。 | `agent_runtime/tool_call_executor.py`、`tool_policy.py`、`test_security_and_usage.py` |
| RAG 为什么混合检索？ | BGE 处理语义相似，BM25 补充明确词项；RRF 融合候选后重排。它不是天然优于所有单路检索，效果须用标注查询和消融实验说明。 | `rag/retrieval/candidates.py`、`reranking.py`、`rag/application/service.py` |
| HNSW 是否另有一份业务数据？ | 检索统一使用 retrieval_entries，索引受 owner／generation 约束，运维显式准备 HNSW。近似召回有精度与维护成本，不能用“用了 HNSW”代替延迟／召回实测。 | `rag/hybrid_index.py`、`rag/index/hnsw.py`、`scripts/prepare_rag_hnsw.py` |
| 删除文档后为什么不会再搜到？ | 检索范围受来源有效性、用户和索引 generation 约束；索引更新使用来源快照防止旧生成覆盖。真实 PG 测试覆盖 exact／HNSW 的归属和删除限制。 | `rag/index/source.py`、`rag/index/knowledge.py`、`test_database_mainline.py` |
| 长录音为什么分窗？ | 限制音频与模型内存；核心区各自拥有 PCM，边界用语音切分。全录音声学聚类再逐窗重建保持标签一致，代价是说话人计算分两遍。 | `media/application/evidence_windows.py`、`whisperx_engine.py`、`local_inference/pyannote_audio.py` |
| ASR 不准怎么办？ | 原始转写保留，LLM 结合完整上下文纠正有依据的错字和角色归属，同时返回回听来源。引用有效只能证明定位合法，不能证明语义绝对正确。 | `interviews/application/recording_qa_service.py`、`test_recording_qa.py` |
| 为什么不再显示覆盖率 100%？ | 旧算法用模型自己给出的角色／分类作为分母，再据此算覆盖率，不能识别自身分类错误。现在报告具体疑点，用参考录音对照检验效果。 | `docs/architecture/interview-audio-to-qa-pipeline.md` |
| 用户编辑与后台结果竞争怎么办？ | 复盘写入锁父记录并校验 review generation；用户修正使旧分析失效。此次再将完整提取结果放进一个事务，避免新状态配旧 QA。 | `review_fence.py`、`transcript_corrections.py`、`test_interview_recovery.py` |
| Memory 是否已经自动记住一切？ | 不是。自动生产默认关闭且用户贡献需授权；已有有效记录可以按账户／会话控制召回。长期相关性、隐私删除与成本需要独立评估。 | `memory/lifecycle.py::_effective_controls`、`memory/recall.py` |
| 用量是否等于供应商账单？ | 记录资源调用、预留和结算；未知消费不随意退回额度。本地异常保留真实原因。unpriced 收据不能承诺金额准确。 | `usage/runtime.py`、`test_security_and_usage.py` |

## 不能包装成已完成的能力

- 真实模型录音回归仍出现“元数据→原数据”同音词；未对单一样本添加替换表或反复抽取直到碰巧成功。
- 超出内部 LLM 上下文／输出容量的录音提取未实现任意长度保证；不静默截断，不宣称支持数小时完整语义提取。
- Gmail／Canva／Notion OAuth、实时麦克风与扬声器未完整验收。
- 当前网络 Fake-IP 阻断 NLTK 从零联网构建；离线使用既有资源构建成功不等于新用户网络安装成功。
- 尚无可归因于当前版本的生产用户规模、SLA、长期稳定性和大规模压测指标。不要引用旧报告中的 Hit Rate、nDCG、P95 或上下文压缩比例充当当前成绩。

完整业务验收与模型测试边界见 [10 月 12 日验收记录](web-release-acceptance-2026-10-12.md)。本次执行日志位于被忽略的 `data/release-acceptance/closure-*`。本地检查点保存在项目外 `_checkpoints/Interview_Copilot-before-final-review-20261013-000206.zip`。


## 最终执行结果

- 新构建镜像已启动；API 中事务发布、回合编排、QA API 和阶段定义四个修改文件的 SHA-256 与本地源码一致。
- 后端主测试：84 passed、4 skipped。跳过项为显式外部服务测试；随后真实 PostgreSQL 的迁移、检索约束与事务回滚／版本隔离 3 项全部通过。S3 本次未重跑，沿用上一轮独立服务证据。
- 前端：类型检查、lint、13 项测试通过。共享 Pydantic 和实时协议导出检查、TypeScript 生成快照检查通过。
- 新镜像 Web／Chromium：10 passed、1 skipped（本轮未重新启用简历模型测试）；覆盖登录与 19 个页面导航。复盘 API 返回“项目经历／技术基础”，当前记录保持 completed。
- 真实 DeepSeek：已在包含新事务发布逻辑的镜像上完成一次重新提取，原转写保留、QA ID 整组更新、报告完成；对照全文两轮问题及第二轮答案一致，第一轮答案仍只有“元→原”一处差异。该调用发生在最终阶段标签调整前，没有为术语错误再次抽取。
- 本地模型依赖完整重装成功，但构建仍使用既有 NLTK 资源；新旧安装版本仅 soupsieve 从 3.0.2 到 3.0.3。项目尚未锁定所有传递依赖，不能承诺不同日期构建完全一致；本轮已保存版本清单便于追溯。
- Ruff 和 git diff 空白检查通过；未修改测试来掩盖术语错误，未发布或推送 GitHub。
