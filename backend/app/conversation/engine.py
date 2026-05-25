"""ConversationEngine — multi-turn outer shell shared by L1 + L2.

Owns every concern that is identical between chat and agent paths:

  1. Session lifecycle ........  transcript_service.ensure_session
  2. Memory recall ............  v3_context_loader (universal +
                                  on-demand bodies, gated by
                                  ``recall_enabled_for_session``)
  3. Context assembly .........  ContextAssemblyPipeline + renderer
  4. Per-turn execution .......  delegated to ExecutionStrategy
  5. Persistence ..............  transcript_service.append_turn with
                                  Claude-Code-style content blocks
  6. Post-turn maintenance ....  realtime extraction (via post-turn
                                  maintenance service, kicked into
                                  background)
  7. Error handling ...........  _humanize_exc — translates upstream
                                  exceptions into actionable Chinese

Strategy-specific work (loop control, tool dispatch, deterministic
pipeline orchestration) lives in the strategy implementation. The
engine is the executive function; the strategy is the action.
"""
from __future__ import annotations

import asyncio
import logging
import time
import traceback
from typing import AsyncGenerator

import openai

from app.conversation.events import HarnessEvent
from app.conversation.strategy import (
    ExecutionStrategy,
    StrategyContext,
    StrategyResult,
)
from app.core.background_tasks import safe_background_task
from app.conversation.query_planner import plan_query
from app.rag.knowledge_retriever import knowledge_retriever
from app.services.chat.chat_history_service import transcript_service
from app.services.chat.context_assembly_pipeline import context_pipeline
from app.services.memory.post_turn_maintenance import post_turn_maintenance_service
from app.services.memory.v3_context_loader import (
    attach_active_bodies,
    load_profile_only,
    load_universal,
)
from app.services.telemetry_service import log_interaction_metrics

logger = logging.getLogger(__name__)


class ConversationEngine:
    """One per submit_message() call. Lives for the duration of one
    turn (preparation + execution + persistence)."""

    def __init__(
        self,
        *,
        user_id: str,
        session_id: str,
        user_message: str,
        strategy: ExecutionStrategy,
    ) -> None:
        self.user_id = user_id
        self.session_id = session_id
        self.user_message = user_message
        self.strategy = strategy

        self._started_at = time.time()
        self._ctx: StrategyContext | None = None
        self._result = StrategyResult()
        # Set during _prepare; consumed by _fire_telemetry. Distinct
        # signals: "did we try retrieval at all" vs "did retrieval
        # surface anything useful".
        self._retrieval_attempted: bool = False
        self._retrieval_hit: bool = False
        # Set in submit_message when a phase crashes. Persistence +
        # post-turn maintenance gate on this so error-humanised text
        # ("系统出了点问题…") doesn't enter chat_messages or feed
        # realtime memory extraction.
        self._turn_status: str = "completed"

    # ── Public entry ──────────────────────────────────────────────

    async def submit_message(self) -> AsyncGenerator[HarnessEvent, None]:
        """Run the whole turn. Yields HarnessEvents for SSE."""
        yield HarnessEvent.status(
            "正在准备对话上下文...",
            step=0,
            elapsed_ms=self._elapsed_ms(),
        )

        try:
            await self._prepare()
        except Exception as exc:  # noqa: BLE001
            self._turn_status = "failed"
            async for ev in self._yield_error(exc):
                yield ev
            return

        yield HarnessEvent.status(
            "开始执行...",
            step=0,
            elapsed_ms=self._elapsed_ms(),
        )

        try:
            async for event in self.strategy.execute(self._ctx, self._result):
                yield event
        except Exception as exc:  # noqa: BLE001
            # Strategies are expected to yield error events themselves
            # for known-bad states. This catch-all is the last-resort
            # net — humanise + emit and let the user see the error,
            # but mark the turn as failed so persistence + post-turn
            # maintenance skip below (avoids writing the humanised
            # error string into chat_messages as if it were a real
            # answer, and avoids feeding it to memory extraction).
            self._turn_status = "failed"
            logger.error(
                "%s strategy crashed: %s\n%s",
                self.strategy.name, exc, traceback.format_exc(),
            )
            humanised = self._humanize_exc(exc)
            yield HarnessEvent.error(
                humanised,
                step=self._result.steps_used,
                elapsed_ms=self._elapsed_ms(),
            )

        # Persistence + post-turn maintenance run only on success.
        # A crashed turn shouldn't pollute the transcript with the
        # humanised error message, and feeding that text into v3
        # memory extraction would manufacture fake user-state facts.
        if self._turn_status == "completed":
            try:
                self._persist_turn()
            except Exception as exc:  # noqa: BLE001
                logger.error("transcript persistence failed: %s", exc)
            self._fire_post_turn_maintenance()
        self._fire_telemetry()

        yield HarnessEvent.done(
            step=self._result.steps_used,
            elapsed_ms=self._elapsed_ms(),
        )

    # ── Phase 1: Prepare ──────────────────────────────────────────

    async def _prepare(self) -> None:
        """Build the StrategyContext. Identical for L1 and L2 — the
        differences only kick in inside ``strategy.execute()``.

        Flow:
          1. Universal memory load (fast: ~4 local DB reads, no LLM).
             Gives the planner the knowledge index + strategy / habit
             descriptions it needs to make body-load decisions.
          2. Single planner LLM call: rewrites query + decides RAG
             + picks memory bodies. (Used to be two LLM calls —
             planner then a separate selection LLM. Merged in the
             post-Stage-G simplification.)
          3. Concurrent: RAG retrieval (Milvus + reranker, ~hundreds
             of ms) // memory body loads (cheap DB reads). Running
             them as tasks just lets the RAG round-trip overlap with
             body loads + saves a few tens of ms.
        """
        transcript_service.ensure_session(self.session_id, self.user_id)

        from app.services.memory.recall_policy import recall_enabled_for_session
        recall_on = recall_enabled_for_session(self.session_id, self.user_id)

        # Step 1: cheap universal load — picks up user_profile + the
        # three description / index lines the planner needs to make
        # informed body-load decisions. Privacy mode skips everything
        # except user_profile (basic identity).
        if recall_on:
            universal_ctx = load_universal(self.user_id)
        else:
            universal_ctx = load_profile_only(self.user_id)

        # Step 2: planner LLM. Inputs are STRUCTURED — session_state +
        # recent_turns come straight from transcript_service, no
        # pre-rendered string wrapper. The planner builds its own
        # prompt internally with the user message at the end (LLMs
        # attend more to the tail of the context).
        meta = transcript_service.get_session_meta(self.session_id)
        if meta is None:
            session_state: dict = {}
            recent_turns: list[dict] = []
        else:
            from app.services.chat.session_state import parse_session_state
            session_state = parse_session_state(
                meta["session_state"],
                meta.get("session_type", "general"),
            )
            recent_turns = transcript_service.get_recent_turns(
                session_id=self.session_id,
                max_turns=20,
                after_seq=meta["compaction_cursor"],
            )

        query_plan = await plan_query(
            user_message=self.user_message,
            session_state=session_state,
            recent_turns=recent_turns,
            knowledge_index_lines=universal_ctx.knowledge_index_lines,
            strategy_description=universal_ctx.strategy_description,
            habit_description=universal_ctx.habit_description,
            recall_on=recall_on,
        )

        # Step 3: concurrent RAG + memory body loads.
        knowledge_task = (
            asyncio.create_task(
                knowledge_retriever.retrieve(
                    dense_query=query_plan.dense_query or self.user_message,
                    sparse_query=query_plan.sparse_query,
                    user_id=self.user_id,
                )
            )
            if query_plan.needs_knowledge_retrieval else None
        )

        wants_bodies = bool(
            query_plan.knowledge_topics
            or query_plan.load_strategy
            or query_plan.load_habit
        )
        bodies_task = (
            asyncio.create_task(
                attach_active_bodies(
                    universal_ctx,
                    user_id=self.user_id,
                    topics=query_plan.knowledge_topics,
                    load_strategy=query_plan.load_strategy,
                    load_habit=query_plan.load_habit,
                )
            )
            if wants_bodies else None
        )

        if bodies_task is not None:
            v3_memory = await bodies_task
        else:
            v3_memory = universal_ctx

        knowledge_result = await knowledge_task if knowledge_task else None
        knowledge_chunks = knowledge_result.chunks if knowledge_result else []

        self._retrieval_attempted = knowledge_task is not None
        self._retrieval_hit = bool(
            knowledge_result and getattr(knowledge_result, "retrieval_hit", False)
        )

        v3_memory_block = v3_memory.render()

        # Full answer context — memory and debrief reference land in
        # SEPARATE slots now (post Stage-G refactor). Debrief reference
        # is auto-injected by the pipeline when in debrief mode.
        # We build the AssembledContext ONCE here and hand it to the
        # strategy so it can render with its own system rules without
        # re-running the pipeline (and re-fetching the debrief
        # reference from the DB).
        # ``current_query`` is the user_message verbatim. The planner
        # no longer emits a ``standalone_query`` — the answer LLM
        # resolves pronouns itself using [Recent Turns] + [Memory].
        assembled = context_pipeline.assemble_answer_context(
            session_id=self.session_id,
            current_query=self.user_message,
            memory_block=v3_memory_block,
            knowledge_chunks=knowledge_chunks,
        )

        self._ctx = StrategyContext(
            user_id=self.user_id,
            session_id=self.session_id,
            user_message=self.user_message,
            assembled=assembled,
            knowledge_chunks=knowledge_chunks,
            v3_memory_block=v3_memory_block,
            rewritten_query=None,
            needs_knowledge_retrieval=query_plan.needs_knowledge_retrieval,
        )

    # ── Phase 3: Persist + maintenance ────────────────────────────

    def _persist_turn(self) -> None:
        """Write the user message + assistant message pair to
        chat_messages, including Claude-Code-style content blocks."""
        if not self._ctx:
            return
        # Empty answer guard — don't poison the transcript with a
        # blank Agent turn (happens when _prepare itself failed).
        if not self._result.final_answer and not self._result.assistant_blocks:
            return
        # Default the assistant_blocks for L1 chat (single text block)
        # if the strategy didn't supply richer ones.
        ai_blocks = self._result.assistant_blocks or [
            {"type": "text", "text": self._result.final_answer},
        ]
        transcript_service.append_turn(
            session_id=self.session_id,
            user_id=self.user_id,
            user_msg=self.user_message,
            ai_msg=self._result.final_answer,
            rewritten_query=self._ctx.rewritten_query,
            ai_blocks=ai_blocks,
        )

    def _fire_post_turn_maintenance(self) -> None:
        """Realtime memory extraction. Always background — never blocks
        the SSE done event. Only called when ``_turn_status`` is
        ``completed`` (gated in submit_message)."""
        if not self._result.final_answer:
            return
        safe_background_task(
            post_turn_maintenance_service.run(
                self.session_id,
                self.user_id,
                allow_memory_write=True,
            )
        )

    def _fire_telemetry(self) -> None:
        safe_background_task(
            log_interaction_metrics(
                session_id=self.session_id,
                user_id=self.user_id,
                latency=time.time() - self._started_at,
                prompt_tokens=self._result.prompt_tokens,
                completion_tokens=self._result.completion_tokens,
                retrieval_attempted=self._retrieval_attempted,
                retrieval_hit=self._retrieval_hit,
            )
        )

    # ── Error humanisation ────────────────────────────────────────

    async def _yield_error(self, exc: Exception) -> AsyncGenerator[HarnessEvent, None]:
        """Emit the user-facing error + done event when _prepare crashed."""
        humanised = self._humanize_exc(exc)
        logger.error(
            "ConversationEngine._prepare failed: %s\n%s",
            exc, traceback.format_exc(),
        )
        yield HarnessEvent.error(
            humanised, step=0, elapsed_ms=self._elapsed_ms(),
        )
        yield HarnessEvent.done(step=0, elapsed_ms=self._elapsed_ms())

    @staticmethod
    def _humanize_exc(exc: Exception) -> str:
        """Translate an upstream exception into actionable Chinese.

        Moved here from ``qa_pipeline.agent_executor._humanize_exc`` so
        the L2 agent path benefits from the same friendly messages.
        Full traceback still goes to the backend log via the caller's
        ``logger.error(...)``.
        """
        if isinstance(exc, openai.AuthenticationError):
            return (
                "当前模型的密钥无效或已失效。请到「模型」页面，找到对应厂商卡片，"
                "重新配置 API 密钥后再试。"
            )
        if isinstance(exc, openai.RateLimitError):
            return "模型厂商当前限流（请求过于频繁），请稍等几秒后重试。"
        if isinstance(exc, openai.APIConnectionError):
            return "无法连接到模型服务，请检查网络或稍后再试。"
        if isinstance(exc, openai.APITimeoutError):
            return "模型响应超时，请重试一次。"
        if isinstance(exc, openai.BadRequestError):
            try:
                detail = (exc.body or {}).get("error", {}).get("message", "")
            except Exception:  # noqa: BLE001
                detail = ""
            if detail:
                return f"请求被模型拒绝：{detail}"
            return "请求被模型拒绝（可能是上下文过长或参数不合规）。"
        return (
            "系统出了点问题，请稍后再试。如果反复发生，请把这次操作的时间告诉运维。"
        )

    # ── Helpers ───────────────────────────────────────────────────

    def _elapsed_ms(self) -> float:
        return round((time.time() - self._started_at) * 1000, 2)


__all__ = ["ConversationEngine"]
