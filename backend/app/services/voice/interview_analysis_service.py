"""Interview transcript analysis — scoring & critique of recorded interviews.

Renamed from ``app.services.analysis_service`` to clearly differentiate from
``app.services.diagnostics_report_service`` (user-level diagnostic reports
across multiple interviews).
"""

import json
import logging
import re
from typing import Any

import tiktoken
from llama_index.core import Settings
from llama_index.core.prompts import PromptTemplate

from app.core.config import settings

logger = logging.getLogger(__name__)

SPEAKER_LINE_RE = re.compile(r"^\s*\*\*\[(?P<speaker>[^\]]+)\]\*\*:\s*(?P<text>.*)$")

try:
    _tokenizer = tiktoken.get_encoding("cl100k_base")
except Exception:
    _tokenizer = None


def _count_tokens(text: str) -> int:
    if not text:
        return 0
    if _tokenizer is None:
        return len(text.encode("utf-8"))
    return len(_tokenizer.encode(text))


def _clean_json_response(raw_text: str) -> dict[str, Any]:
    raw_text = str(raw_text).strip()
    if raw_text.startswith("```json"):
        raw_text = raw_text[7:]
    elif raw_text.startswith("```"):
        raw_text = raw_text[3:]
    if raw_text.endswith("```"):
        raw_text = raw_text[:-3]
    return json.loads(raw_text.strip())


def _normalize_chunk_result(data: dict[str, Any]) -> dict[str, Any]:
    qa_list = data.get("qa_list", [])
    if not isinstance(qa_list, list):
        qa_list = []

    normalized_qa_list: list[dict[str, Any]] = []
    for qa in qa_list:
        if not isinstance(qa, dict):
            continue
        normalized_qa_list.append(
            {
                "question": str(qa.get("question", "")).strip(),
                "user_answer": str(qa.get("user_answer", "")).strip(),
                "score": float(qa.get("score", 0) or 0),
                "critique": str(qa.get("critique", "")).strip(),
                "improved_answer": str(qa.get("improved_answer", "")).strip(),
            }
        )

    return {
        "overall_score": float(data.get("overall_score", 0) or 0),
        "overall_feedback": str(data.get("overall_feedback", "")).strip(),
        "qa_list": normalized_qa_list,
    }


def _parse_speaker_turns(transcript: str) -> list[dict[str, str]]:
    turns: list[dict[str, str]] = []
    current_speaker: str | None = None
    current_parts: list[str] = []

    for raw_line in transcript.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = SPEAKER_LINE_RE.match(line)
        if match:
            if current_speaker is not None and current_parts:
                turns.append(
                    {
                        "speaker": current_speaker,
                        "text": " ".join(current_parts).strip(),
                    }
                )
            current_speaker = match.group("speaker").strip()
            current_parts = [match.group("text").strip()]
        elif current_speaker is not None:
            current_parts.append(line)

    if current_speaker is not None and current_parts:
        turns.append(
            {
                "speaker": current_speaker,
                "text": " ".join(current_parts).strip(),
            }
        )
    return turns


def _build_qa_pairs(turns: list[dict[str, str]]) -> list[dict[str, str]]:
    if len(turns) < 2:
        return []

    interviewer = turns[0]["speaker"]
    qa_pairs: list[dict[str, str]] = []
    i = 0

    while i < len(turns):
        question_parts: list[str] = []
        answer_parts: list[str] = []

        while i < len(turns) and turns[i]["speaker"] == interviewer:
            question_parts.append(turns[i]["text"])
            i += 1

        while i < len(turns) and turns[i]["speaker"] != interviewer:
            answer_parts.append(turns[i]["text"])
            i += 1

        question = "\n".join(part for part in question_parts if part).strip()
        answer = "\n".join(part for part in answer_parts if part).strip()
        if question and answer:
            qa_pairs.append({"question": question, "answer": answer})

    return qa_pairs


def _fallback_pairs_from_paragraphs(transcript: str) -> list[dict[str, str]]:
    parts = [part.strip() for part in transcript.split("\n\n") if part.strip()]
    qa_pairs: list[dict[str, str]] = []
    for idx in range(0, len(parts) - 1, 2):
        qa_pairs.append({"question": parts[idx], "answer": parts[idx + 1]})
    return qa_pairs


def _pair_to_text(pair: dict[str, str], index: int) -> str:
    return (
        f"### QA Pair {index}\n"
        f"[Question]\n{pair['question']}\n\n"
        f"[Candidate Answer]\n{pair['answer']}"
    )


def _chunk_pairs(qa_pairs: list[dict[str, str]], token_limit: int) -> list[str]:
    chunks: list[str] = []
    current_pairs: list[str] = []
    current_tokens = 0

    for idx, pair in enumerate(qa_pairs, start=1):
        pair_text = _pair_to_text(pair, idx)
        pair_tokens = _count_tokens(pair_text)

        if current_pairs and current_tokens + pair_tokens > token_limit:
            chunks.append("\n\n".join(current_pairs))
            current_pairs = []
            current_tokens = 0

        current_pairs.append(pair_text)
        current_tokens += pair_tokens

        if pair_tokens > token_limit:
            logger.warning(
                "Single QA pair token size %s exceeds chunk limit %s; preserving intact pair.",
                pair_tokens,
                token_limit,
            )
            chunks.append("\n\n".join(current_pairs))
            current_pairs = []
            current_tokens = 0

    if current_pairs:
        chunks.append("\n\n".join(current_pairs))

    return chunks


async def _analyze_chunk(chunk_text: str, chunk_index: int, total_chunks: int) -> dict[str, Any]:
    prompt_str = """
你是一名资深且非常严格的技术面试官。下面给你的是一段已经整理好的完整问答对集合，
每个 QA Pair 都是完整的“面试官问题 + 候选人回答”，请逐题分析候选人的回答质量。

你的任务：
1. 逐个识别 QA Pair。
2. 对每个 QA Pair 输出 question、user_answer、score、critique、improved_answer。
3. 给出当前分段的 overall_score 和 overall_feedback。
4. 不要遗漏任何一个 QA Pair，不要合并不同题目。

输出要求：
必须只输出一个合法 JSON 对象，不允许输出 markdown 代码块，不允许输出解释文字。

JSON 结构如下：
{{
  "overall_score": 8,
  "overall_feedback": "对这一分段的综合评价",
  "qa_list": [
    {{
      "question": "面试官问的具体问题",
      "user_answer": "候选人的原始回答",
      "score": 7,
      "critique": "技术缺陷、遗漏点、错误点",
      "improved_answer": "更完整、更严谨的改进答案"
    }}
  ]
}}

当前是第 {chunk_index} / {total_chunks} 个分段。

【问答对分段文本】
{chunk_text}
"""
    prompt = PromptTemplate(prompt_str).format(
        chunk_index=chunk_index,
        total_chunks=total_chunks,
        chunk_text=chunk_text,
    )
    response = await Settings.llm.acomplete(prompt)
    return _normalize_chunk_result(_clean_json_response(response.text))


def _chunk_summary_text(result: dict[str, Any], chunk_index: int) -> str:
    qa_lines = []
    for qa_idx, qa in enumerate(result.get("qa_list", []), start=1):
        qa_lines.append(
            f"{qa_idx}. 问题: {qa['question']}\n"
            f"得分: {qa['score']}\n"
            f"问题点评: {qa['critique']}"
        )
    joined_qa = "\n\n".join(qa_lines) if qa_lines else "无有效 QA 提取结果"
    return (
        f"## Chunk {chunk_index}\n"
        f"分段评分: {result.get('overall_score', 0)}\n"
        f"分段反馈: {result.get('overall_feedback', '')}\n\n"
        f"{joined_qa}"
    )


async def _summarize_results(chunk_results: list[dict[str, Any]]) -> dict[str, Any]:
    all_qa: list[dict[str, Any]] = []
    for result in chunk_results:
        all_qa.extend(result.get("qa_list", []))

    if not chunk_results:
        return {"overall_score": 0.0, "overall_feedback": "", "qa_list": []}

    if len(chunk_results) == 1:
        single = chunk_results[0]
        single["qa_list"] = all_qa
        return single

    summary_text = "\n\n".join(
        _chunk_summary_text(result, idx)
        for idx, result in enumerate(chunk_results, start=1)
    )

    prompt_str = """
你是一名资深技术面试官。下面是多个“分段面试分析结果”，每个分段都已经包含：
- 分段评分
- 分段反馈
- 逐题 question / score / critique

请你基于这些分段结果，输出全局汇总结论。

要求：
1. overall_score 给出整个面试的综合评分，范围 0-10。
2. overall_feedback 必须是对整场面试的整体总结，要指出主要优点和最关键的薄弱点。
3. 只输出合法 JSON，不要输出 markdown，不要输出任何解释。

JSON 结构：
{{
  "overall_score": 8,
  "overall_feedback": "对整场面试的综合评价"
}}

【分段分析结果】
{summary_text}
"""
    prompt = PromptTemplate(prompt_str).format(summary_text=summary_text)
    response = await Settings.llm.acomplete(prompt)
    final_summary = _clean_json_response(response.text)

    return {
        "overall_score": float(final_summary.get("overall_score", 0) or 0),
        "overall_feedback": str(final_summary.get("overall_feedback", "")).strip(),
        "qa_list": all_qa,
    }


async def analyze_interview(transcript: str) -> dict:
    """
    对带有 speaker diarization 的转录文本进行分段分析。
    优先按完整问答对切分，再基于 token 阈值分批送入模型，最后汇总为统一 JSON。
    """
    try:
        turns = _parse_speaker_turns(transcript)
        qa_pairs = _build_qa_pairs(turns)
        if not qa_pairs:
            qa_pairs = _fallback_pairs_from_paragraphs(transcript)

        if not qa_pairs:
            logger.warning("No QA pairs detected from transcript; falling back to single-pass analysis.")
            chunk_results = [await _analyze_chunk(transcript, 1, 1)]
            return await _summarize_results(chunk_results)

        chunks = _chunk_pairs(qa_pairs, settings.ANALYSIS_CHUNK_TOKEN_LIMIT)
        logger.info(
            "Interview analysis entering chunked mode: %s QA pairs split into %s chunks (limit=%s tokens).",
            len(qa_pairs),
            len(chunks),
            settings.ANALYSIS_CHUNK_TOKEN_LIMIT,
        )

        chunk_results: list[dict[str, Any]] = []
        for idx, chunk_text in enumerate(chunks, start=1):
            chunk_results.append(await _analyze_chunk(chunk_text, idx, len(chunks)))

        return await _summarize_results(chunk_results)

    except Exception as e:
        logger.error(f"Analysis service failed: {e}")
        raise


__all__ = ["analyze_interview"]
