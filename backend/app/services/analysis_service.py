import json
import logging
from llama_index.core import Settings
from llama_index.core.prompts import PromptTemplate

logger = logging.getLogger(__name__)

async def analyze_interview(transcript: str) -> dict:
    """
    通过 LlamaIndex 的底层 LLM 来阅读冗长的长文转录录音片段，
    将其深度重写、挑刺并拆解为精美的 QA 对 JSON 返回。
    """
    try:
        # 强制格式约束与提示词架构
        prompt_str = """
你是一个资深且极其严厉的技术面试官。请阅读以下的面试录音转录文本，将其拆解为多个详细的技术问答对（Question & Answer）。
请仔细分析候选人的回答，找出其中的技术漏洞或不完美之处，并提供改进后的完美回答思路。

【输出要求】
必须严格且只输出以下结构的 JSON（不要包含任何前缀或 markdown ```json 代码块标识，直接返回合法 JSON 对象字符串），如果转录内有多道考题，请扩展 qa_list 数组。
{{
  "overall_score": 8,
  "overall_feedback": "对面试者全盘表现的综合评价...",
  "qa_list": [
    {{
      "question": "面试官问的具体问题",
      "user_answer": "候选人的原始回答",
      "score": 7,
      "critique": "在此点明漏洞、不足与技术概念错误...",
      "improved_answer": "技术上 100% 正确且逻辑严密的最佳回答示范，必须可供后来背诵"
    }}
  ]
}}

【转录文本】
{transcript}
"""
        prompt_template = PromptTemplate(prompt_str)
        formatted_prompt = prompt_template.format(transcript=transcript)
        
        # 调度预先关联好的大模型深思出结果
        response = await Settings.llm.acomplete(formatted_prompt)
        raw_text = str(response.text).strip()
        
        # 工程级容错：清洗可能的 Markdown JSON 包裹符
        if raw_text.startswith("```json"):
            raw_text = raw_text[7:]
        elif raw_text.startswith("```"):
            raw_text = raw_text[3:]
            
        if raw_text.endswith("```"):
            raw_text = raw_text[:-3]
            
        return json.loads(raw_text.strip())
        
    except Exception as e:
        logger.error(f"分析服务引擎发生核心崩溃: {e}")
        raise
