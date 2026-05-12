"""User-level diagnostic report service.

Aggregates a user's historical interview mistakes and review records,
then asks the agent's fast LLM to produce a structured diagnosis
(strengths, weaknesses, skill radar).

Renamed from ``analytics_service`` to clearly distinguish from the
per-interview transcript scoring in
``app.services.voice.interview_analysis_service``.
"""

import json
import logging
import os
from typing import Any

from llama_index.core.storage.docstore import SimpleDocumentStore

from app.core.config import settings
from app.rag.embeddings import agent_fast_llm

logger = logging.getLogger(__name__)


def _extract_personal_memories(docstore: Any, user_id: str) -> list[dict[str, Any]]:
    memories: list[dict[str, Any]] = []
    docs = getattr(docstore, "docs", {}) or {}
    for _, doc in docs.items():
        metadata = getattr(doc, "metadata", {}) or {}
        if metadata.get("source_type") != "personal_memory":
            continue
        if metadata.get("user_id") != user_id:
            continue
        memories.append(
            {
                "content": getattr(doc, "text", ""),
                "score": float(metadata.get("original_score", 10.0)),
                "time": metadata.get("last_accessed", ""),
            }
        )
    return memories


def _clean_json_text(raw: str) -> str:
    cleaned = raw.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    elif cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    return cleaned.strip()


async def generate_comprehensive_report(limit: int = 20, user_id: str | None = None) -> dict:
    if not user_id:
        return {"status": "empty", "message": "missing user id"}

    try:
        docstore = None
        if os.path.exists(settings.DOCSTORE_DIR):
            docstore = SimpleDocumentStore.from_persist_dir(settings.DOCSTORE_DIR)
        else:
            return {"status": "empty", "message": "底层缓存为空"}

        personal_memories = _extract_personal_memories(docstore, user_id=user_id)
        if not personal_memories:
            return {"status": "empty", "message": "暂无人格记忆特征数据"}

        personal_memories.sort(key=lambda x: x["time"], reverse=True)
        records = personal_memories[:limit]
        structured_payload = json.dumps(records, ensure_ascii=False)

        sys_prompt = f"""
你是一位资深技术面试官，请根据候选人的历史错题与复盘记录输出结构化诊断。
必须输出 JSON 对象，严格遵循字段：
{{
  "overall_evaluation": "string",
  "strengths": [{{"topic":"string","evidence":"string"}}],
  "weaknesses": [{{"topic":"string","flaw":"string","plan":"string"}}],
  "skill_radar": {{"算法与数据结构": 0-10, "底层架构剖析": 0-10, "工程落地并发": 0-10, "源码深度追踪": 0-10}}
}}
输入记录：
{structured_payload}
"""
        response = await agent_fast_llm.acomplete(
            sys_prompt,
            response_format={"type": "json_object"},
        )
        raw_text = _clean_json_text(str(response.text))
        try:
            parsed = json.loads(raw_text)
            return {"status": "success", "report": parsed}
        except json.JSONDecodeError:
            return {
                "status": "fallback",
                "message": "模型输出非标准 JSON，已返回原文。",
                "raw_text": raw_text,
            }
    except Exception as exc:  # noqa: BLE001
        logger.error("生成全维诊断报告期间发生了毁灭性灾难: %s", exc)
        return {"status": "error", "message": f"诊断中断: {exc}"}


__all__ = ["generate_comprehensive_report"]
