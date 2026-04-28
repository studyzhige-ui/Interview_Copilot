import json
import logging
from typing import List
from pydantic import BaseModel, Field
from llama_index.core.prompts import PromptTemplate
from app.rag.embeddings import agent_fast_llm

logger = logging.getLogger(__name__)

class RouteDecision(BaseModel):
    needs_retrieval: bool = Field(..., description="指示本次自然语言访问是否需要提取外部/离线信息。")
    target_sources: List[str] = Field(..., description="应该挂载的知识存储库目标。仅支持子集：'interview_qa', 'official_docs', 'personal_memory'")
    search_keywords: str = Field(..., description="Query Rewrite 重写协议：将用户问题提取、提纯为极简的核心技术关键词串（摒弃无用停用词）。专门供给下层 BM25 进行词频命中。")
    routing_strategy: str = Field(..., description="针对请求的聚合解析策略标识。")
    reasoning: str = Field(..., description="做出判断过程中的逻辑说明，供调试审计。")

async def analyze_intent(user_query: str) -> RouteDecision:
    """
    进化版网关中枢（Multi-hop Intent Routing & Query Rewriting）。
    剥离慢迭代 Agent 的黑盒包袱，强制化简文本供给确定性并发执行器使用。
    """
    try:
        # 为了兼容并适配绝大多数基座 OS，放弃 LlamaIndex 的重型结构化封装，使用裸 Prompt JSON
        sys_prompt = """
你是一个极高权限的多跳路由仲裁中心。请审视以下用户的访谈语句，并必须严格输出唯一的结构化 JSON。
【严格核心约束】：严禁输出哪怕一个字的 Markdown 代码块标签 (诸如 ```json) ，或混入任何基于 CoT 的思考过程文本。你只允许输出一个能够通过 Python json.loads() 直接并100%成功解析的合规字典！

【Query Rewrite 提取协议 (关键)】
若判定 needs_retrieval 为 True，你必须为随后的底层混搜库引擎（BM25 词频）执行关键词投喂。
请将用户的超长问题极其无情地提取、浓缩、碾碎为 2-4 个没有任何感情色彩的【纯架构/技术名词】，放入 "search_keywords"。如果是无效日常对话，传空串 ""。

【可用子存储挂载点】
- "interview_qa"：高频题库检索、技术八股文存储。
- "official_docs"：原始底层官方代码及其原理结构说明数据。
- "personal_memory"：针对使用者私人的错漏暴露、成绩弱点档案、以及纠正措施。

【路由安全策略】
1. 日常寒暄或明确不需要资料的技术探讨：needs_retrieval 为 false, target_sources 置空, search_keywords 为 "", strategy 取位 "direct_chat"。
2. 明确的单一体系技术复习或查错集：needs_retrieval 为 true, 选出最为匹配的 1 个源置入数组, strategy 取位 "single_source"。
3. 要求既要高维理论又要切合曾经在某道题上的真实反应对比问：强制挑出 2-3 个可用资源点，strategy 为 "multi_source_synthesis"。

【解析目标语句】
USER: {query}

【响应标准结构必须形如下方示例】
{{
    "needs_retrieval": true,
    "target_sources": ["interview_qa", "official_docs"],
    "search_keywords": "MySQL 并发死锁 Repeatable Read MVCC",
    "routing_strategy": "multi_source_synthesis",
    "reasoning": "用户在讨论并发写条件下的数据安全异常，并隐晦地要求查验官设标准规范，故激活读盘与文档联合源并提取了强核词汇。"
}}
"""
        template = PromptTemplate(sys_prompt)
        prompt_text = template.format(query=user_query)

        logger.info("Router [前置解析器]: 开始解析当前输入意图 (搭载 V3 极速通道 + Native JSON Mode)...")
        response = await agent_fast_llm.acomplete(
            prompt_text,
            response_format={"type": "json_object"}
        )

        raw_text = str(response.text).strip()
        data = json.loads(raw_text)

        # Pydantic 类型绑定校验
        decision = RouteDecision(**data)

        # 强沙盒过滤隔离机制
        valid_banks = {"interview_qa", "official_docs", "personal_memory"}
        decision.target_sources = [src for src in decision.target_sources if src in valid_banks]

        return decision

    except Exception as e:
        logger.warning(f"Router 前置解析器过载或返回错乱，触发防御降级策略: {e}")
        return RouteDecision(
            needs_retrieval=True,
            target_sources=["interview_qa"], # 安全防爆回滚至标准 QA 库
            search_keywords=user_query, # 粗放容灾退防
            routing_strategy="single_source",
            reasoning="系统解析 JSON 时引擎重试超载解体，静默使用自然输入退防降级查询安全通道"
        )
