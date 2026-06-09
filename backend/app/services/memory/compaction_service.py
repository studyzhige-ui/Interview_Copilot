"""Conversation summary compaction service.

Compresses old conversation turns into the session's ``summary`` column using
a dual-threshold trigger (token growth + turn count) — adapts to conversation
density better than a fixed modulo cadence. This is the assembly-time (outer)
trigger of the same autocompact mechanism the L2 loop runs inline; both fold
the conversation into one ``summary`` rendered via the [Context Summary] slot
(see plan §8 — the two will fully merge under D1).
"""

import logging

from app.rag.embeddings import agent_fast_llm
from app.services.chat.chat_history_service import transcript_service
from app.services.chat.context_assembly_pipeline import count_tokens
from app.services.memory._json_payload import _extract_json_payload

logger = logging.getLogger(__name__)


class CompactionService:
    """Compresses old conversation turns into the session's ``summary`` column.

    Dual-threshold trigger:
      - Token growth ≥ COMPACT_MIN_TOKEN_GROWTH AND turns ≥ COMPACT_MIN_TURNS
      - OR turns ≥ COMPACT_MAX_TURNS (hard cap, fires regardless of token count)

    This replaces the old fixed "every 20 turns" (modulo) trigger which could
    not adapt to conversation density — heavy sessions (long RAG analysis)
    waited too long while lightweight sessions (short Q&A) triggered too early.

    The summary uses the structured 6-section template (``COMPACTION_PROMPT``)
    instead of the old flat 300-char blob.
    """

    # ── Dual-threshold parameters ────────────────────────────────────
    COMPACT_MIN_TOKEN_GROWTH = 6_000  # pending tokens since last compact
    COMPACT_MIN_TURNS = 4             # minimum turns between compactions
    COMPACT_MAX_TURNS = 15            # hard cap — always compact at this point
    SUMMARY_MAX_TOKENS = 2_500  # cap on the stored 6-section summary

    COMPACTION_PROMPT = """你是一个对话摘要助手。
你的输出会被注入到一段独立的对话中，让一个**不同的**助手能够无缝接续当前对话。
不要回答对话中的任何问题——只输出结构化摘要。
使用对话中用户使用的同一种语言撰写摘要。

规则：
- 使用下面的结构化格式输出
- 如果已有旧摘要，在其基础上增量更新：保留仍然相关的信息，添加新进展，只删除明确过时的内容
- 控制在 1000 字以内
- 具体、准确：包含文件路径、命令、错误消息、具体数值，避免模糊描述
- 用户的个人信息（姓名、技术栈、目标岗位等）由长期记忆系统单独管理，不要在摘要中重复
- 输出纯 JSON 格式：{{"summary": "..."}}

旧摘要：
{old_summary}

新对话：
{new_conversation}

输出的 summary 字段必须包含以下六个章节：

## 当前状态
[现在正在进行什么？如果对话在此中断，下一个助手应该从哪里接上？
这是最重要的字段——必须反映最新的对话状态]

## 目标
[用户在这段对话中想要达成什么？整体目标是什么？]

## 已完成事项
[编号列表。每条具体说明做了什么、结果是什么。示例：
1. 讨论了 TCP 三次握手的 SYN/ACK 流程，确认了半连接队列的作用
2. 对比了 RDB 和 AOF 持久化方案，结论是混合持久化最优
3. 修改了 context_service.py 中的 SESSION_STATE_BUDGET 从 2000 → 3000]

## 已解决的问题
[用户提过的、已经回答的问题——列出问题和答案要点。
目的：下一个助手不要重复回答这些问题]

## 关键决策
[对话中做出的重要决定及其原因。示例：
- 选择方案 B（双阈值触发），因为方案 A 在轻量会话中触发过早
- 确认使用 DeepSeek 作为 fast 模型，因为性价比最优]

## 待跟进
[还没回答完的问题、用户提出但未完成的请求、需要深入的话题。
如果没有，写"无"]
"""

    async def compact_if_needed(self, session_id: str) -> bool:
        import asyncio

        # All transcript_service reads/writes are sync DB queries.
        # ``compact_if_needed`` runs as a background task (engine
        # dispatches via ``safe_background_task``), but the LLM call
        # below YIELDS the loop, so any other coroutine pinned on
        # this thread could land during the await. Without to_thread
        # wrapping, the three queries here form sync bottlenecks
        # that block the loop for ~10-50ms each. Wrapped to keep the
        # parent's event-loop thread free across the whole compaction.
        meta = await asyncio.to_thread(
            transcript_service.get_session_meta, session_id,
        )
        if meta is None:
            return False

        pending = await asyncio.to_thread(
            transcript_service.get_recent_turns,
            session_id, 100, meta["compaction_cursor"],
        )
        if not pending:
            return False

        # ── Dual-threshold trigger ───────────────────────────────────
        turns_since_compact = (len(pending) + 1) // 2
        pending_tokens = sum(count_tokens(m["content"]) for m in pending)

        should_compact = (
            (pending_tokens >= self.COMPACT_MIN_TOKEN_GROWTH
             and turns_since_compact >= self.COMPACT_MIN_TURNS)
            or turns_since_compact >= self.COMPACT_MAX_TURNS
        )
        if not should_compact:
            return False

        logger.info(
            "Compaction triggered for session %s: %d turns, %d tokens pending",
            session_id, turns_since_compact, pending_tokens,
        )

        old_summary = meta.get("summary", "")
        conversation = "\n".join(
            f"{item['role']}: {item['content']}" for item in pending
        )
        new_summary = await summarize_conversation(old_summary, conversation)
        if not new_summary:
            return False  # LLM / parse failure (already logged)

        await asyncio.to_thread(
            transcript_service.update_session_fields,
            session_id,
            summary=new_summary,
            compaction_cursor=pending[-1]["seq"],
        )
        logger.info(
            "Compaction completed for session %s: summary=%d tokens",
            session_id, count_tokens(new_summary),
        )
        return True


async def summarize_conversation(old_summary: str, conversation: str) -> str:
    """The single LLM summarization core — used by BOTH the outer post-turn
    compaction (assembly-time trigger, ``compact_if_needed``) and the inner
    loop autocompact (loop-time trigger, ``QueryLoopCompactor.autocompact``).
    One function, two call sites, one 6-section summary.

    Iteratively updates ``old_summary`` with ``conversation`` (the formatted
    new turns / messages). Returns the new, capped summary; ``""`` on LLM or
    parse failure (logged).
    """
    prompt = CompactionService.COMPACTION_PROMPT.format(
        old_summary=old_summary or "(无)",
        new_conversation=conversation,
    )
    try:
        response = await agent_fast_llm.acomplete(
            prompt, response_format={"type": "json_object"},
        )
        new_summary = str(
            _extract_json_payload(str(response.text)).get("summary", "")
        ).strip()
    except Exception as exc:  # noqa: BLE001
        logger.error("Conversation summarization failed: %s", exc)
        return ""
    if count_tokens(new_summary) > CompactionService.SUMMARY_MAX_TOKENS:
        new_summary = new_summary[:1200]
    return new_summary


compaction_service = CompactionService()


__all__ = ["CompactionService", "compaction_service", "summarize_conversation"]
