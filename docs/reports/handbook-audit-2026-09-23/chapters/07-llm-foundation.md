# 07-llm-foundation：逐章审查

全部 14 章均有映射。判定针对本项目当前实现；“基础具备”不等于生产验收通过，“边界知识”不要求增加相应技术栈。知识点提纲来自该章二级及三级标题，保留原手册链接供逐点追问；本表的工程判断聚焦章节在项目中的实际落点。

[总报告](../README.md) · [代码证据索引](../代码证据索引.md)

## 01｜LLM Foundation 在 AI Application 中负责什么

**判定：基础具备**。模型适配、检索、运行时有独立职责；外部模型能力不等于产品能力。

**工程证据：** [A4](../代码证据索引.md#a4)。缺陷编号见总报告。

**手册知识点：** 1. 先讲人话；2. 本模块回答哪些问题；3. 模型层与系统层必须分开；4. AI Application Engineer 需要学多深；需要真正理解；需要知道概念与工程影响，但不要求训练算法岗推导；5. 为什么这个模块放在 Vector DB 之后、RAG 之前；6. 一个典型 AI 请求的模型侧生命周期；7. AI 应用里的三个最重要边界；Boundary 1：模型能力 ≠ 外部事实；Boundary 2：Context Window ≠ Memory；Boundary 3：Model API ≠ Agent Runtime；8. 🎯 面试怎么回答；9. ⚠️ 面试易错点；10. 🔍 继续追问。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/07-llm-foundation/docs/01-LLMFoundation%E5%9C%A8AI%E5%BA%94%E7%94%A8%E4%B8%AD%E7%9A%84%E8%81%8C%E8%B4%A3.md)

## 02｜Token、Context Window 与 Long Context：从输入单位到上下文预算

**判定：基础具备**。tokenizer、预算、context checkpoint 具备；缺真实长任务质量回归 F12。

**工程证据：** [C1](../代码证据索引.md#c1)。缺陷编号见总报告。

**手册知识点：** 1. Token 是什么；2. Token 为什么是工程成本单位；3. Context Window 是什么；4. Context Budget 不只是“不能超长度”；5. 长上下文为什么不等于无限记忆；6. Lost in the Middle 的直觉；7. 为什么 RAG 仍然有价值；8. 为什么 Agent 更容易遇到 Context Pressure；9. Context 预算怎么估；10. Token Cost 和 Latency 的关系；Input Token 增加；Output Token 增加；11. 常见错误；12. 面试怎么答；Q：Context Window 是什么？；Q：Long Context 能替代 RAG 吗？；13. 自测。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/07-llm-foundation/docs/02-TokenContext%E4%B8%8ELongContext.md)

## 03｜Transformer Block：Architecture、FFN、Residual 与 Normalization

**判定：边界知识**。调用模型不要求实现 Transformer；面试解释 Attention/FFN/残差即可。

**工程证据：** [A4](../代码证据索引.md#a4)。缺陷编号见总报告。

**手册知识点：** 1. Decoder-only LLM 的整体路径；2. 一个 Transformer Block 大致有什么；3. Hidden State 是什么；4. Attention 负责什么；5. FFN / MLP 负责什么；6. 为什么 FFN 参数很多；7. Residual Connection 为什么重要；8. Normalization 做什么；9. Pre-Norm 与 Post-Norm 的直觉；Post-Norm 风格；Pre-Norm 风格；10. 为什么要堆很多层；11. Parameter Count 和 Compute 的直觉；12. 常见错误；13. 面试怎么答；Q：Transformer Block 里主要有什么？；Q：Attention 和 FFN 的角色有什么区别？；14. 自测。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/07-llm-foundation/docs/03-TransformerBlock.md)

## 04｜Attention 与 Position：QKV、Multi-Head、Causal Mask 与 RoPE

**判定：边界知识**。QKV/RoPE 属模型机制；不能把增加 context 配置当长上下文能力提升。

**工程证据：** [A4](../代码证据索引.md#a4)。缺陷编号见总报告。

**手册知识点：** 1. Self-Attention 的核心问题；2. Attention Score 怎么形成；3. 为什么要除以 sqrt(dk)；4. Self-Attention 为什么比 RNN 更适合并行；5. Multi-Head Attention 为什么需要多个 Head；6. Causal Mask 为什么生成模型必须有；7. Padding Mask 与 Causal Mask 不一样；Padding Mask；Causal Mask；8. Attention 为什么需要位置信息；9. Absolute Position 与 Relative Position 直觉；10. RoPE 的核心直觉；11. RoPE 和 Long Context 的关系；12. Attention 的计算成本直觉；13. QKV 和 KV Cache 的关系；14. 常见错误；15. 面试怎么答；Q：Q、K、V 怎么理解？；Q：为什么需要 Causal Mask？；Q：RoPE 在做什么？；16. 自测。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/07-llm-foundation/docs/04-Attention%E4%B8%8EPosition.md)

## 05｜Autoregressive Generation：Logits、Softmax、Sampling 与 Decoding

**判定：基础具备**。统一温度、输出限制和能力适配；temperature 低不等于确定性。

**工程证据：** [A4](../代码证据索引.md#a4)。缺陷编号见总报告。

**手册知识点：** 1. Autoregressive 是什么；2. 为什么 Output Token 数直接影响延迟；3. Logits 是什么；4. Softmax 怎么把 Logits 变成概率；5. Greedy Decoding；6. Temperature 在做什么；T 较低；T 较高；7. Top-k；8. Top-p / Nucleus Sampling；9. Top-k、Top-p 和 Temperature 怎么组合；10. “Temperature=0 就完全 deterministic”为什么不绝对；11. Stop Condition；12. Repetition 与 Degeneration；13. Structured Output 与 Sampling 的关系；14. AI Application 怎么调生成参数；Tool / Extraction / Routing；Knowledge QA；Creative；15. 常见错误；16. 面试怎么答；Q：LLM 是怎么生成下一个 Token 的？；Q：Temperature、Top-k、Top-p 有什么区别？；17. 自测。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/07-llm-foundation/docs/05-Generation%E4%B8%8EDecoding.md)

## 06｜KV Cache、Prefill 与 Decode：LLM 推理的两阶段模型

**判定：需改进**。有缓存 token 遥测；缺 TTFT/TPOT 分拆与 prefix 命中收益实测 F17。

**工程证据：** [O1](../代码证据索引.md#o1)。缺陷编号见总报告。

**手册知识点：** 1. 为什么 Autoregressive Generation 会重复用历史 Token；2. KV Cache 缓存什么；3. KV Cache 为什么会变成资源瓶颈；4. Prefill 是什么；5. Decode 是什么；6. Prefill 和 Decode 为什么性能特征不同；7. TTFT 与 TPOT；Time To First Token；Time Per Output Token；8. 为什么长 Context 会同时拖累体验和容量；9. Prefix / Prompt Cache 的直觉；10. KV Cache 和 Application Cache 不是一回事；KV Cache；Response Cache / Semantic Cache；11. GQA / MQA 为什么和 KV Cache 有关；12. Streaming 和 Decode；13. 常见错误；14. 面试怎么答；Q：KV Cache 为什么能加速 LLM 推理？；Q：Prefill 和 Decode 有什么区别？；15. 自测。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/07-llm-foundation/docs/06-KVCache%E4%B8%8EPrefillDecode.md)

## 07｜LLM Serving Engine：Continuous Batching、PagedAttention、Latency、Cost 与 Quantization

**判定：边界知识**。未自建 vLLM；提供方 serving 是外部边界，需客户端并发/限流预算。

**工程证据：** [D1](../代码证据索引.md#d1)。缺陷编号见总报告。

**手册知识点：** 1. 为什么普通 Static Batch 不适合在线生成；2. Continuous Batching 的核心思想；3. 为什么 Decode 更适合动态 Batch；4. KV Cache 传统连续内存的问题；5. PagedAttention 的核心直觉；6. Serving Scheduler 还要做什么；7. 四个最重要的在线指标；TTFT；TPOT；Throughput；End-to-end Latency；8. 为什么 Throughput 和 Latency 会冲突；9. Capacity 不是“GPU 能不能放下模型”；10. Precision 为什么影响 Serving；11. Quantization 不是“压缩模型就结束”；12. Model Size、Context、Output 对成本的不同影响；更大 Model；更长 Input；更长 Output；13. Provider API 场景怎么理解 Serving；14. Benchmark 应该怎么做；15. 常见错误；16. 面试怎么答；Q：Continuous Batching 为什么能提高 LLM Serving 吞吐？；Q：PagedAttention 解决什么问题？；Q：LLM Serving 该看哪些性能指标？；17. 自测。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/07-llm-foundation/docs/07-ServingEngine%E4%B8%8E%E6%80%A7%E8%83%BD.md)

## 08｜Model API、Provider Adapter 与 Model Selection

**判定：需改进**。供应商能力/凭证/model selection 已分层；跨 loop 复用需修复 F02。

**工程证据：** [A4](../代码证据索引.md#a4)。缺陷编号见总报告。

**手册知识点：** 1. Model API 在抽象什么；2. Message Role 为什么重要；3. Provider Adapter 为什么存在；4. Adapter 不应该过度抽象；5. Model Selection 不是“选最强模型”；6. 先按 Task 定义 Quality；Classification / Routing；Structured Extraction；Coding；RAG QA；Agent；7. Model Capability Matrix；8. Small Model vs Large Model；9. Context Window 大不代表更适合任务；10. Cost 怎么估；11. Reliability 也是 Model Selection 指标；12. Model Version 为什么要显式记录；13. Streaming 的 Provider 差异；14. Fallback 与 Multi-provider；15. 常见错误；16. 面试怎么答；Q：模型怎么选型？；Q：为什么要做 Provider Adapter？；17. 自测。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/07-llm-foundation/docs/08-ModelAPI%E4%B8%8ESelection.md)

## 09｜Embedding 与 Reranker：Bi-Encoder / Cross-Encoder 的分工

**判定：基础具备**。embedding、reranker 注册与契约已有；更换后须重评阈值 F12。

**工程证据：** [R3](../代码证据索引.md#r3)。缺陷编号见总报告。

**手册知识点：** 1. Embedding Model 在做什么；2. Bi-Encoder 为什么适合大规模检索；3. Query Encoder 和 Document Encoder 不一定完全一样；4. Embedding 质量怎么评估；5. Embedding Model 选型看什么；6. 为什么 Dense Embedding 不是万能的；7. Cross-Encoder 为什么更准但更贵；8. Reranker 的典型位置；9. 为什么 Rerank 不能救回未召回的文档；10. Reranker 输入长度与截断；11. Reranker 也有 Domain Shift；12. Cross-Encoder 和 LLM Judge 的区别；13. Embedding 与 Reranker 的版本治理；14. 常见错误；15. 面试怎么答；Q：Bi-Encoder 和 Cross-Encoder 区别？；Q：为什么先 Top20 再 Rerank Top5？；16. 自测。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/07-llm-foundation/docs/09-Embedding%E4%B8%8EReranker.md)

## 10｜Multimodal Foundation：从视觉输入到可验证的多模态系统

**判定：需改进**。附件视觉、OCR、ASR/说话人分离有入口；缺全链准确率/隐私删除验收。

**工程证据：** [R2](../代码证据索引.md#r2)。缺陷编号见总报告。

**手册知识点：** 1. 多模态模型解决什么；2. 视觉输入怎样进入语言模型；3. Visual Token / Multimodal Budget；4. 为什么“整份 PDF 截图全塞模型”通常不稳；5. OCR / Layout Parser / Direct Vision 的边界；OCR / Parser 路线；Direct Vision 路线；两者组合；6. Layout 为什么是一等信息；7. 多模态对齐到底意味着什么；8. Multimodal Embedding 与 Multimodal Generative Model；Multimodal Embedding；Multimodal Generative Model；9. Audio / Video 为什么比单图再多一层复杂性；10. Production Failure 要分层定位；10.1 Perception Failure；10.2 Retrieval / Selection Failure；10.3 Alignment / Grounding Failure；10.4 Reasoning Failure；10.5 Generation Failure；11. 多模态 Evaluation 应该怎么做；12. 模型 / 路线选型不要只看“支持 Vision”；13. Security / Privacy / Data Governance；14. 多模态与 RAG / Agent 的边界；RAG 负责；LLM Foundation 负责；Agent Harness 负责；15. 🎯 30 秒回答；16. ⚠️ 高频易错点；17. 🔍 深挖追问。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/07-llm-foundation/docs/10-MultimodalFoundation.md)

## 11｜Prompt Engineering：从“写提示词”到可评估工程

**判定：需改进**。prompt 有模块和归属；失效导入测试揭示变更契约未闭合 F11。

**工程证据：** [C1](../代码证据索引.md#c1)。缺陷编号见总报告。

**手册知识点：** 1. Prompt 到底在控制什么；2. 一个稳定的 Prompt 结构；3. System / Developer / User 的边界；4. 为什么 Few-shot Example 有用；5. Prompt 和 Structured Output；6. Prompt 版本化；7. Prompt 优化必须有 Evaluation；8. Prompt 不是所有问题的解法；模型根本不知道最新知识；需要改变长期行为或领域风格；Tool 调用失败；长任务忘记状态；权限问题；9. 常见 Prompt Failure；9.1 指令冲突；9.2 Context 太长；9.3 Output Contract 不明确；9.4 Prompt 对某几个案例过拟合；9.5 把不可信内容混进 Instruction；10. Prompt Regression；11. 🎯 面试怎么回答；12. ⚠️ 易错点；13. 🔍 继续追问。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/07-llm-foundation/docs/11-PromptEngineering.md)

## 12｜Hallucination、Factuality 与 Prompt / RAG / Fine-tuning 的干预边界

**判定：需改进**。有证据门与 citation；事实正确性、拒答与对抗评测未证明达标 F12。

**工程证据：** [R4](../代码证据索引.md#r4)。缺陷编号见总报告。

**手册知识点：** 1. Hallucination 是什么；2. 模型为什么会“编”；3. Factuality 和 Fluency 不一样；4. Prompt 能解决什么；5. Prompt 不能稳定补充模型没有的动态知识；6. RAG 主要解决什么；7. Fine-tuning 主要解决什么；8. Tool / Verification 什么时候更合适；9. 一个错误归因决策树；10. Grounding 怎么降低风险；11. 为什么 Citation 也可能是假的；12. “不知道就说不知道”为什么仍需要 Eval；13. Fine-tuning 为什么不能自动修复事实性；14. Model Change 什么时候有意义；15. 一个实际改进顺序；16. 常见错误；17. 面试怎么答；Q：怎么降低大模型 Hallucination？；Q：Prompt、RAG、Fine-tuning 怎么选？；18. 自测。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/07-llm-foundation/docs/12-Hallucination%E4%B8%8E%E5%B9%B2%E9%A2%84%E8%BE%B9%E7%95%8C.md)

## 13｜Fine-tuning、SFT 与 LoRA / PEFT：什么时候值得训练自己的适配层

**判定：边界知识**。没有 LoRA 不是缺陷；先按失败类型确定检索还是微调。

**工程证据：** [A4](../代码证据索引.md#a4)。缺陷编号见总报告。

**手册知识点：** 1. Fine-tuning 改变的是什么；2. SFT 是什么；3. 数据质量为什么比“多跑几个 Epoch”重要；4. 为什么必须有独立 Eval Set；5. Full Fine-tuning 为什么贵；6. PEFT 是什么；7. LoRA 的核心直觉；8. Rank r 控制什么；9. LoRA 通常插在哪里；10. LoRA 与 Quantization 可以结合；11. Fine-tuning 不适合解决动态知识；12. Catastrophic Forgetting / Capability Regression；13. 什么时候 Fine-tuning 才值得做；14. Fine-tuning 的 Production Versioning；15. Serving LoRA 的工程价值；16. 常见错误；17. 面试怎么答；Q：什么时候会考虑 Fine-tuning？；Q：LoRA 为什么省资源？；18. 自测。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/07-llm-foundation/docs/13-FineTuning%E4%B8%8ELoRA.md)

## 14｜RLHF / DPO / GRPO / Distillation 的应用工程边界

**判定：边界知识**。RLHF/DPO/蒸馏为面试储备；未训练就不能写在项目能力里。

**工程证据：** [A4](../代码证据索引.md#a4)。缺陷编号见总报告。

**手册知识点：** 1. 为什么 SFT 之后还不够；2. RLHF 的基本链路；3. DPO；4. GRPO 应该理解到什么程度；5. Reward 为什么危险；6. Knowledge Distillation；7. Distillation 不是“复制全部能力”；8. Synthetic Data；9. 应用团队什么时候真的需要 Post-training；10. 面试里怎样回答 PPO / DPO / GRPO；11. 🎯 面试怎么回答；12. ⚠️ 易错点。

[原章节](https://github.com/studyzhige-ui/ai-application-interview-handbook/blob/e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5/curriculum/07-llm-foundation/docs/14-PostTraining%E4%B8%8EDistillation.md)
