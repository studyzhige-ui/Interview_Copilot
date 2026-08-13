"""ConversationEngine — multi-turn outer shell shared by L1 + L2.

Owns every concern that is identical between chat and agent paths:

  1. Session lifecycle ........  transcript_service.ensure_session
  2. Context assembly .........  ContextAssemblyPipeline + renderer
  3. Per-turn execution .......  delegated to ExecutionStrategy
  4. Persistence ..............  transcript_service.append_turn with
                                   Claude-Code-style content blocks
  5. Error handling ...........  _humanize_exc — translates upstream
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

from app.conversation.events import HarnessEvent
from app.conversation.query_planner import QueryPlan, plan_query
from app.conversation.runtime_profile import runtime_profile_for_session
from app.conversation.strategy import (
    ExecutionStrategy,
    StrategyContext,
    StrategyResult,
)
from app.core.error_messages import humanize_error
from app.rag.application.service import rag_service
from app.rag.application.attachment_sources import (
    AttachmentParsingPendingError,
    load_attachment_sources,
    merge_retrieval_results,
)
from app.rag.domain.models import EMPTY_PLANNER_NO_RETRIEVAL
from app.services.analytics.telemetry_service import log_interaction_metrics
from app.services.chat.chat_history_service import transcript_service
from app.services.chat.context_assembly_pipeline import context_pipeline
from app.services.chat.shared_source_acquisition import (
    SharedSourceBundle,
    acquire_shared_read_only_sources,
)
from app.services.chat.source_requests import (
    explicit_source_requests_from_object_references,
    extract_explicit_urls,
)

logger = logging.getLogger(__name__)

_TURN_OUTCOMES = {"completed", "waiting", "blocked", "failed", "cancelled"}


def check_turn_completion(
    turn_id: str | None,
    user_id: int,
    attachment_requirements: tuple[dict[str, str], ...] = (),
) -> tuple[bool, str | None]:
    """Run the Shared Kernel's deterministic completed-candidate gate.

    It reads only authoritative state for this Turn. It does not create a
    product object, scan a Session, infer Tool semantics, or maintain another
    task lifecycle.
    """

    if not turn_id or user_id <= 0:
        return True, None

    from app.db.database import SessionLocal
    from app.models.agent_execution import AgentToolCall
    from app.services.chat.agent_task_service import (
        agent_task_structure_complete,
        get_agent_task,
    )

    db = SessionLocal()
    try:
        task = get_agent_task(db, turn_id=turn_id, user_id=user_id)
        calls = (
            db.query(AgentToolCall)
            .filter(AgentToolCall.turn_id == turn_id)
            .order_by(AgentToolCall.id)
            .all()
        )
        for call in calls:
            ok, reason = _tool_call_proves_completion(call)
            if not ok:
                return False, reason
        if attachment_requirements:
            from app.services.chat.attachment_coverage import (
                attachment_requirement_block_reason,
            )

            reason = attachment_requirement_block_reason(
                attachment_requirements,
                calls,
            )
            if reason:
                return False, reason
        if not agent_task_structure_complete(task):
            return False, "agent_task_incomplete"
        return True, None
    finally:
        db.close()


def _tool_call_proves_completion(call: object) -> tuple[bool, str | None]:
    """Validate the durable result needed for one concrete Tool claim.

    A model-visible Tool-like string never reaches this function.  It checks
    only the persisted call identity and redacted typed result.  External
    writes additionally require a provider receipt or read-back; adding an
    external-write Tool without that proof therefore fails closed.
    """

    call_id = str(getattr(call, "call_id", "unknown"))
    status = str(getattr(call, "status", ""))
    if status in {"running", "waiting", "unknown", "deferred"}:
        return False, f"unresolved_tool_call:{call_id}"

    result = getattr(call, "result_json", None)
    if status in {"denied", "cancelled", "failed", "timeout"}:
        # A closed failure/Policy result proves only that this concrete action
        # did not succeed. It must stay available to the Agent for replanning,
        # but it cannot permanently veto a Turn whose safe alternative path
        # completed. Success claims below still require their own typed proof.
        if (isinstance(result, dict) and result.get("error")) or getattr(
            call, "error", None
        ):
            return True, None
        return False, f"tool_failure_result_missing:{call_id}:{status}"
    if status != "completed":
        return False, f"tool_call_not_completed:{call_id}:{status or 'missing'}"
    if not isinstance(result, dict) or result.get("error"):
        return False, f"tool_result_missing_or_failed:{call_id}"

    effect = str(getattr(call, "effect", "unknown"))
    if effect == "external_write":
        proof = any(
            result.get(key)
            for key in (
                "provider_receipt",
                "receipt",
                "read_back",
                "readback",
            )
        )
        if not proof:
            return False, f"external_write_proof_missing:{call_id}"

    if effect == "client_action":
        action_status = str(
            result.get("client_action_status")
            or result.get("acknowledgement")
            or result.get("status")
            or ""
        ).casefold()
        acknowledged = (
            action_status
            in {
                "acknowledged",
                "completed",
                "ready",
                "entered",
                "started",
            }
            or result.get("ui_entered") is True
        )
        if not acknowledged:
            return False, f"client_action_ack_missing:{call_id}"

    return True, None


class ConversationEngine:
    """One per submit_message() call. Lives for the duration of one
    turn (preparation + execution + persistence)."""

    def __init__(
        self,
        *,
        user_id: str,
        user_pk: int = 0,
        session_id: str,
        user_message: str,
        strategy: ExecutionStrategy,
        turn_id: str | None = None,
        dispatch_generation: int = 1,
        question_indexes: tuple[int, ...] = (),
        attachments: tuple[dict, ...] = (),
        product_object_context: str = "",
        strategy_extras: dict | None = None,
    ) -> None:
        self.user_id = user_id
        self.user_pk = user_pk
        self.session_id = session_id
        self.user_message = user_message
        self.strategy = strategy
        self.turn_id = turn_id
        self.dispatch_generation = dispatch_generation
        self.question_indexes = tuple(
            dict.fromkeys(index for index in question_indexes if index > 0)
        )
        # Durable server-resolved snapshots from ConversationTurn. Raw client
        # ids never reach the runtime directly.
        self.attachments = tuple(dict(item) for item in attachments)
        self.product_object_context = str(product_object_context or "")
        self.strategy_extras = dict(strategy_extras or {})

        self._started_at = time.time()
        self._ctx: StrategyContext | None = None
        self._result = StrategyResult()
        # Set during _prepare; consumed by _fire_telemetry. Distinct
        # signals: "did we try retrieval at all" vs "did retrieval
        # surface anything useful". The three RAG-state fields below are
        # read straight off the turn's RetrievalState (single source of
        # truth) so fallback_rate / planner_failure_rate / empty_reason
        # are observable in metrics.jsonl (retrieval plan §2.1/§2.5/§2.7).
        self._retrieval_attempted: bool = False
        self._retrieval_hit: bool = False
        self._planner_failed: bool = False
        self._fallback_used: bool = False
        self._empty_reason: str | None = None
        self._rag_metrics: dict = {}
        # Set in submit_message when a phase crashes or pauses. Persistence is
        # terminal-only: a waiting Turn keeps the claimed user input but does
        # not manufacture an assistant answer before its Interaction resolves.
        self._turn_status: str = "completed"

    @property
    def outcome(self) -> str:
        return self._turn_status

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
        except AttachmentParsingPendingError:
            # Parsing is an expected durable wait, not a failed answer. The
            # Turn host owns releasing compute and resuming this same Turn
            # when its frozen projections become terminal.
            self._turn_status = "waiting"
            raise
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
            if self._result.outcome not in _TURN_OUTCOMES:
                raise ValueError(f"invalid Turn outcome: {self._result.outcome}")
            self._turn_status = self._result.outcome
        except Exception as exc:  # noqa: BLE001
            # Strategies are expected to yield error events themselves
            # for known-bad states. This catch-all is the last-resort
            # net — humanise + emit and let the user see the error,
            # but mark the turn as failed so persistence + post-turn
            # maintenance skip below (avoids writing the humanised
            # error string into conversation_messages as if it were a real
            # answer or letting downstream post-turn work treat it as one).
            self._turn_status = "failed"
            logger.error(
                "%s strategy crashed: %s\n%s",
                self.strategy.name,
                exc,
                traceback.format_exc(),
            )
            humanised = self._humanize_exc(exc)
            yield HarnessEvent.error(
                humanised,
                step=self._result.steps_used,
                elapsed_ms=self._elapsed_ms(),
            )

        # A blocked Turn may have honest partial results worth retaining. A
        # failed or waiting Turn must not be persisted as a successful answer.
        if self._turn_status in {"completed", "blocked"}:
            try:
                await self._persist_turn()
            except Exception as exc:  # noqa: BLE001
                logger.error("transcript persistence failed: %s", exc)
                self._turn_status = "failed"
                yield HarnessEvent.error(
                    "回答已生成，但保存失败，请重新发送本轮问题。",
                    step=self._result.steps_used,
                    elapsed_ms=self._elapsed_ms(),
                )
        await self._fire_telemetry()

        yield HarnessEvent.done(
            step=self._result.steps_used,
            elapsed_ms=self._elapsed_ms(),
            outcome=self._turn_status,
        )

    # ── Phase 1: Prepare ──────────────────────────────────────────

    async def _prepare(self) -> None:
        """Build the StrategyContext. Identical for L1 and L2 — the
        differences only kick in inside ``strategy.execute()``.

        Flow:
          1. Resolve the product runtime profile and current conversation state.
          2. Run the Chat retrieval planner when the selected strategy needs it.
          3. Load admitted sources through the shared RAG path.
        """
        # ``ensure_session`` opens a SessionLocal + INSERT — wrap in
        # to_thread so the event loop isn't blocked on the DB round-
        # trip. Same treatment for every sync DB read in this block —
        # collectively they used to chain ~4 sync queries on the loop
        # thread before the first await, freezing every concurrent
        # SSE turn for the duration.
        await asyncio.to_thread(
            transcript_service.ensure_session,
            self.session_id,
            self.user_id,
        )

        # Product-specific context is prepared by the runtime profile.  The
        # shared kernel therefore has no direct knowledge of interview-record
        # loading, while Career and Debrief still reuse the same planner,
        # context budgeting, strategies, and persistence path.
        meta = await asyncio.to_thread(
            transcript_service.get_session_meta,
            self.session_id,
        )
        runtime_profile = runtime_profile_for_session(meta)
        runtime_context = await runtime_profile.prepare_turn(meta)

        # Step 2: planner LLM. Inputs are STRUCTURED — recent_turns comes
        # straight from transcript_service, no pre-rendered string wrapper.
        # The planner builds its own prompt internally with the user message
        # at the end (LLMs attend more to the tail of the context).
        #
        # L2 (agent) mode skips the planner and recent-turn feeder read:
        # every planner output is RAG routing — unused, because the agent
        # retrieves via the ``search_knowledge`` tool. Paying a serial
        # fast-LLM round-trip for a discarded decision would be wasteful.
        agent_mode = self.strategy.name == "agent"
        if agent_mode:
            query_plan = QueryPlan()  # null plan: no retrieval, no body load
        else:
            if meta is None:
                recent_turns: list[dict] = []
            else:
                recent_turns = await asyncio.to_thread(
                    transcript_service.get_recent_turns,
                    self.session_id,
                    20,
                    meta["compaction_cursor"],
                )
            query_plan = await plan_query(
                user_message=self.user_message,
                recent_turns=recent_turns,
                interview_questions=runtime_context.planner_question_catalog,
            )

        # Explicit URLs are selected from the admitted current input rather
        # than delegated to the planner.  Chat may additionally request a
        # bounded read from one of four existing owners.  Agent keeps its
        # iterative owner tools, but receives explicit URL SourceResults from
        # this same SSRF-safe path so the two strategies share the source
        # universe without manufacturing a Tool Call.
        explicit_urls = extract_explicit_urls(self.user_message)
        explicit_owner_requests = explicit_source_requests_from_object_references(
            self.strategy_extras.get("admitted_object_references")
        )
        shared_source_task = (
            asyncio.create_task(
                acquire_shared_read_only_sources(
                    user_id=self.user_id,
                    user_pk=self.user_pk,
                    session_id=self.session_id,
                    turn_id=self.turn_id,
                    current_query=self.user_message,
                    requests=(query_plan.source_requests if not agent_mode else ()),
                    explicit_requests=explicit_owner_requests,
                    explicit_urls=explicit_urls,
                )
            )
            if explicit_urls
            or explicit_owner_requests
            or (not agent_mode and query_plan.source_requests)
            else None
        )

        debrief_reference = runtime_context.render_record_context(
            self.question_indexes,
            query_plan.referenced_question_indexes,
        )

        # Step 3: shared RAG/source loading.
        #
        # L2 (agent) mode skips engine-side RAG: the agent retrieves knowledge
        # on demand via the ``search_knowledge`` tool, so injecting it here
        # would be redundant and double-pay the Milvus + rerank cost. It also
        # lengthens the cache-stable prompt prefix — RAG chunks were the
        # per-turn-variable part of the agent's grounding. L1 (chat) keeps it.
        knowledge_task = (
            asyncio.create_task(
                rag_service.retrieve(
                    intents=query_plan.intents,
                    user_id=self.user_id,
                    planner_failed=query_plan.planner_failed,
                )
            )
            if query_plan.needs_knowledge_retrieval and not agent_mode
            else None
        )

        # Explicit files use the same RetrievalResult → GroundingBuilder →
        # [K#] source-card path as library RAG. The loader also picks up files
        # already owned by this conversation, matching mainstream chat-file
        # persistence without placing them in the global vector index.
        attachment_task = asyncio.create_task(
            asyncio.to_thread(
                load_attachment_sources,
                user_id=self.user_id,
                session_id=self.session_id,
                query=self.user_message,
                explicit_attachments=self.attachments,
            )
        )

        knowledge_result = await knowledge_task if knowledge_task else None
        attachment_bundle = await attachment_task
        shared_source_bundle = (
            await shared_source_task if shared_source_task else SharedSourceBundle()
        )
        from app.services.chat.attachment_coverage import (
            attachment_execution_requirements,
        )

        self.strategy_extras["attachment_execution_requirements"] = (
            attachment_execution_requirements(attachment_bundle.documents)
        )
        self.strategy_extras["explicit_source_failures"] = list(
            shared_source_bundle.explicit_failures
        )
        knowledge_result = merge_retrieval_results(
            attachment_bundle.result if attachment_bundle.documents else None,
            knowledge_result,
        )
        knowledge_result = merge_retrieval_results(
            shared_source_bundle.result if shared_source_bundle.attempted else None,
            knowledge_result,
        )

        # RetrievalState is the single source of truth for the turn's RAG
        # flags. When retrieval ran, read everything off it (the facade
        # already stamped planner_failed onto it); when it didn't (direct
        # chat / agent mode), planner_failed still comes from the plan.
        self._retrieval_attempted = (
            knowledge_task is not None
            or bool(attachment_bundle.documents)
            or shared_source_bundle.attempted
        )
        _state = knowledge_result.state if knowledge_result is not None else None
        self._retrieval_hit = bool(_state and _state.retrieval_hit)
        self._fallback_used = bool(_state and _state.fallback_used)
        self._empty_reason = (
            _state.empty_reason
            if _state
            else EMPTY_PLANNER_NO_RETRIEVAL
            if not self._retrieval_attempted
            else None
        )
        self._planner_failed = (
            _state.planner_failed if _state is not None else query_plan.planner_failed
        )
        if knowledge_result is not None:
            self._rag_metrics = {
                "intent_count": len(knowledge_result.intents),
                "retrieved_chunk_count": len(knowledge_result.chunks),
                "diagnostics": knowledge_result.diagnostics,
            }

        # Full answer context. Canonical Long-term Agent Memory is recalled
        # selectively as low-authority data; legacy mixed Memory is never read.
        # We build the AssembledContext ONCE here and hand it to the
        # strategy so it can render with its own system rules without
        # re-running the pipeline (and re-fetching the debrief
        # reference from the DB).
        # ``current_query`` is the user_message verbatim. The planner
        # no longer emits a ``standalone_query`` — the answer LLM resolves
        # references from the admitted conversation projection itself.
        # assemble_answer_context is async: it loads all turns after the
        # compaction cursor and may trigger threshold-based compaction
        # (LLM summarization) before returning. Sync DB reads inside are
        # dispatched to worker threads internally.
        # AGT-6: the compression threshold follows the ACTIVE primary
        # model's real window (a 128K model never hit the old hardcoded 1M
        # threshold and eventually 400'd instead of compressing).
        try:
            from app.core.user_model_selection import get_profile_for_role

            _window = get_profile_for_role(
                "primary", user_id=self.user_id
            ).context_window
        except Exception:  # noqa: BLE001 — cold catalog: fall back to default
            _window = None
        try:
            from app.services.agent_memory_service import render_recall_block

            memory_block = await asyncio.to_thread(
                render_recall_block,
                conversation_id=self.session_id,
                user_pk=self.user_pk,
                current_query=self.user_message,
            )
        except Exception:  # noqa: BLE001 - optional personalization fails closed
            logger.exception("Long-term Agent Memory recall failed closed")
            memory_block = ""
        assembled = await context_pipeline.assemble_answer_context(
            session_id=self.session_id,
            current_query=self.user_message,
            memory_block=memory_block,
            debrief_reference=debrief_reference,
            attachment_manifest=attachment_bundle.manifest,
            source_read_status=shared_source_bundle.status_manifest,
            product_object_context=self.product_object_context,
            retrieval_result=knowledge_result,
            user_id=self.user_id,
            model_context_window=_window,
        )

        self._ctx = StrategyContext(
            user_id=self.user_id,
            user_pk=self.user_pk,
            session_id=self.session_id,
            user_message=self.user_message,
            turn_id=self.turn_id,
            dispatch_generation=self.dispatch_generation,
            runtime_profile=runtime_profile.name,
            assembled=assembled,
            rewritten_query=None,
            needs_knowledge_retrieval=(
                query_plan.needs_knowledge_retrieval
                or bool(attachment_bundle.documents)
                or shared_source_bundle.attempted
            ),
            retrieval_hit=self._retrieval_hit,
            extras=self.strategy_extras,
        )

    # ── Phase 3: Persist + maintenance ────────────────────────────

    async def _persist_turn(self) -> None:
        """Write the user message + assistant message pair to
        conversation_messages, including Claude-Code-style content blocks.

        ``transcript_service.append_turn`` is a sync DB transaction
        (opens a SessionLocal, inserts 2 rows, commits). Dispatching
        to a worker thread keeps the event loop free while the commit
        roundtrips to Postgres — otherwise every concurrent SSE turn
        stalls for the ~10-50ms it takes.
        """
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
        # Persist the RAG sources alongside the answer so a reloaded history
        # turn can re-resolve [K#] source cards. The frontend (and the block
        # renderer) skip the unknown "sources" block when rendering the body.
        if self._ctx and self._ctx.assembled.sources:
            ai_blocks = [
                *ai_blocks,
                {"type": "sources", "sources": self._ctx.assembled.sources},
            ]
        if self.turn_id:
            await asyncio.to_thread(
                transcript_service.complete_background_turn,
                turn_id=self.turn_id,
                ai_msg=self._result.final_answer,
                rewritten_query=self._ctx.rewritten_query,
                ai_blocks=ai_blocks,
            )
        else:
            await asyncio.to_thread(
                transcript_service.append_turn,
                session_id=self.session_id,
                user_id=self.user_id,
                user_msg=self.user_message,
                ai_msg=self._result.final_answer,
                rewritten_query=self._ctx.rewritten_query,
                ai_blocks=ai_blocks,
            )

    async def persist_background_failure(self, message: str) -> None:
        if not self.turn_id:
            return
        warning = {"type": "text", "text": f"⚠️ {message}"}
        blocks = [warning, *self._result.assistant_blocks]
        await asyncio.to_thread(
            transcript_service.complete_background_turn,
            turn_id=self.turn_id,
            ai_msg=self._result.final_answer or warning["text"],
            rewritten_query=self._ctx.rewritten_query if self._ctx else None,
            ai_blocks=blocks,
        )

    async def _fire_telemetry(self) -> None:
        # Await the cheap local append so this also completes when the engine
        # runs inside a Celery thread whose event loop stops after the task.
        await log_interaction_metrics(
            session_id=self.session_id,
            user_id=self.user_id,
            latency=time.time() - self._started_at,
            prompt_tokens=self._result.prompt_tokens,
            completion_tokens=self._result.completion_tokens,
            cache_read_tokens=self._result.cache_read_tokens,
            cache_creation_tokens=self._result.cache_creation_tokens,
            provider_id=self._result.provider_id,
            prompt_cache_supported=self._result.prompt_cache_supported,
            prompt_cache_enabled=self._result.prompt_cache_enabled,
            retrieval_attempted=self._retrieval_attempted,
            retrieval_hit=self._retrieval_hit,
            planner_failed=self._planner_failed,
            fallback_used=self._fallback_used,
            empty_reason=self._empty_reason,
            stop_reason=self._result.stop_reason,
            rag_metrics={
                **self._rag_metrics,
                "grounded_source_count": (
                    len(self._ctx.assembled.sources) if self._ctx else 0
                ),
                "covered_intent_count": (
                    len(self._ctx.assembled.grounding.covered_intent_ids)
                    if self._ctx
                    else 0
                ),
                "missing_intent_count": (
                    len(self._ctx.assembled.grounding.missing_intent_ids)
                    if self._ctx
                    else 0
                ),
                "missing_term_count": (
                    len(self._ctx.assembled.grounding.missing_terms) if self._ctx else 0
                ),
                "citation": (self._result.extras or {}).get("citation_report"),
            },
        )

    # ── Error humanisation ────────────────────────────────────────

    async def _yield_error(self, exc: Exception) -> AsyncGenerator[HarnessEvent, None]:
        """Emit the user-facing error + done event when _prepare crashed."""
        humanised = self._humanize_exc(exc)
        logger.error(
            "ConversationEngine._prepare failed: %s\n%s",
            exc,
            traceback.format_exc(),
        )
        yield HarnessEvent.error(
            humanised,
            step=0,
            elapsed_ms=self._elapsed_ms(),
        )
        yield HarnessEvent.done(
            step=0,
            elapsed_ms=self._elapsed_ms(),
            outcome="failed",
        )

    @staticmethod
    def _humanize_exc(exc: Exception) -> str:
        """Translate an upstream exception into actionable Chinese.

        Delegates to the shared :func:`humanize_error` so L1 chat, L2
        agent, the SSE last-resort net, and this engine all surface
        identical wording. Full traceback still goes to the backend log
        via the caller's ``logger.error(...)``.
        """
        return humanize_error(exc)

    # ── Helpers ───────────────────────────────────────────────────

    def _elapsed_ms(self) -> float:
        return round((time.time() - self._started_at) * 1000, 2)


__all__ = ["ConversationEngine", "check_turn_completion"]
