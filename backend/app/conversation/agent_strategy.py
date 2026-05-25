"""L2 ReAct agent strategy — the autonomous tool-calling loop.

Hosts the ``while True:`` agent loop that used to live in
``agent_runtime.query_engine.QueryEngine._query_loop``. Everything that
was multi-turn outer-shell concern (memory recall, context assembly,
transcript persistence, post-turn maintenance) is now in
:class:`~app.conversation.engine.ConversationEngine`; this strategy
only handles the per-turn execution.

The strategy:
  * builds the initial messages array from the prepared context
  * drives the LLM↔tool ReAct loop until a final answer / budget stop
  * tracks token usage + budget on its own (engine reads back via
    :class:`StrategyResult`)
  * emits ``HarnessEvent`` for SSE
  * builds the Anthropic-style ``content_blocks_json`` chain
    (interleaved text/tool_use/tool_result) so the engine can persist
    it for the Claude-Code-style folded-card frontend UX
  * writes ``agent_runs`` + ``agent_steps`` trace inline (developer
    debugging surface, distinct from the user-facing transcript)
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, AsyncGenerator

from app.agent_runtime.agent_progress_hooks import PostSamplingHookRunner
from app.agent_runtime.context_compactor import QueryLoopCompactor
from app.agent_runtime.react_agent import (
    AgentBudget,
    _args_summary,
    _result_summary,
    _tool_call_payload,
)
from app.agent_runtime.retry_utils import call_with_retry
from app.agent_runtime.tool_call_streaming import _ToolCallAccumulator
from app.agent_runtime.tool_registry import (
    AgentToolContext,
    parse_tool_arguments,
    registry,
    safe_json_dumps,
)
from app.agent_runtime.tool_result_storage import (
    enforce_turn_budget,
    maybe_persist_result,
)
from app.conversation.events import HarnessEvent
from app.conversation.strategy import StrategyContext, StrategyResult
from app.core.config import settings
from app.core.model_registry import build_async_openai_client_for_role
from app.services.agent_trace_service import append_step, create_run, finish_run

# Trigger tool self-registration on first import.
import app.agent_runtime.tools  # noqa: F401

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """你是 Interview Copilot 的执行 Agent，帮助用户完成面试准备相关的复杂任务。

# 工作原则

## 1. 先想清楚再调工具，不要盲调
- 收到用户问题，先判断：用户的问题真的需要工具吗？需要哪个？
- **工具是数据增强，不是知识替代**。你的训练知识本身就涵盖了大量信息（公司、技术栈、框架对比、最佳实践、面经常见题……）。能直接答的就直接答，工具只用于补充你不知道的、时效性强的、用户私有的数据。
- 「我想做 agent 开发，哪些公司在招」→ 即使 search_jobs 返回 0 条，也要用你训练数据里的知识列出 OpenAI / Anthropic / Cognition / Adept / Sierra / Imbue 等，配上每家的方向特点。**不要**因为工具没数据就不答了。
- 「帮我分析这道题」→ 直接答，不用调任何工具
- 「我之前讨论过的 Redis 你还记得吗」→ 调 recall_memory（关闭全局记忆时此工具不会出现在你的 manifest 里）
- 反例（不要做）：一收到问题就并发调 read_resume + read_interview_history + recall_memory + search_jobs。这样既慢又浪费 token，还会让用户看到一堆「0 条结果」的卡片。

## 2. 工具失败 ≠ 任务失败 —— 永远要给用户有用的答复

工具会因为各种原因失败或返回空：
- 用户还没上传简历 / 没有面试历史 / 知识库为空
- 外部 API 没配密钥（search_jobs、web_search）
- 网络问题、限流

**绝对不要**因为工具失败就放弃。正确做法：
- 基于你已知的领域知识 + 部分工具结果，给用户一个**还不错的回答**
- 用**友善的语气**说明哪些信息缺失，提供具体的下一步建议
- 例如 search_jobs 返回 0 条 → 用你自己掌握的"哪些公司招 agent 开发"知识答题，并友善提示「Lever 公司列表配上后可以拉到实时职位」

## 3. 失败信息的友好转译

- ❌ "工具调用失败，请重试"  ← 用户看了一脸懵
- ✅ "我没找到你的简历的结构化版本，但看到资料库里有一份 PDF —— 我可以基于通用建议先答，或者你可以告诉我你的背景关键词（学校 / 工作经验 / 技术栈），我能更精准。"

- ❌ "No resume found"  ← 直译报错
- ✅ "看起来还没上传过简历。上传到「资料库 → 文件」之后我能给更个性化的分析。先从通用角度聊聊？"

## 4. 工具返回 disabled / 工具不可见 / 工具失败时的处理

- 工具返回 `{"disabled": true, "reason": ...}`：尊重它，不要再调，按用户本会话上下文继续
- 工具不在你的 manifest 里：说明该功能未启用，不要假装会用
- 工具抛错：先看 error 信息，常见原因（无数据、未配置）友好转译给用户

## 5. 关于工具组合

如果一个工具结果不够，**主动**用其它工具补：
- read_resume 说"有 PDF 但没解析"→ 调 search_knowledge 带"工作经历"/"教育背景"查 PDF 内容
- search_jobs 返回 0 条 → 试 web_search 用「AI Agent 工程师 招聘」等关键词
- read_url 拿到 JD → 配合 read_resume / search_knowledge 做差距分析

## 6. 你能做的事

- 分析岗位要求（JD）与用户能力的差距
- 基于面试历史识别薄弱环节并制定学习计划
- 搜索互联网获取面经、公司信息、技术资料
- 从知识库检索八股文和技术文档
- 把重要结论 save_memory 存起来（仅当全局记忆开启）
- 导出结构化的分析报告和学习笔记为文件

# 输出规则

- 用结构化的、可执行的建议
- 不要编造工具没返回的数据
- 不要以「我失败了，请重试」结尾 —— 永远给用户**至少一个可以立刻做的下一步**
- 如果用户问的是知识 / 概念问题，直接答，不要绕一大圈调工具
"""


def _build_graceful_fallback(
    blocks: list[dict[str, Any]],
    error_message: str,
) -> str:
    """Construct a user-facing message when the agent loop crashed.

    Pre-fix behaviour: any exception in the inner loop produced a
    flat "Agent 执行失败，请稍后重试" string, discarding every tool
    call's worth of context the user just watched run. That's the
    failure mode the user called out — 4 tools fired, then a generic
    dead-end message. New behaviour:

    1. If any text block was emitted before the crash, surface it
       (the LLM did say SOMETHING useful).
    2. Summarise which tools ran and what they returned (success /
       empty / error) — at minimum the user knows what was attempted.
    3. Close with a friendly suggestion + the raw error in a small
       debug note (not at the top, not the headline).

    The intent: never leave the user with a content-less "I failed"
    bubble. There's always something to say.
    """
    parts: list[str] = []
    text_blocks = [b for b in blocks if b.get("type") == "text" and b.get("text")]
    tool_use_blocks = [b for b in blocks if b.get("type") == "tool_use"]
    tool_result_blocks = [b for b in blocks if b.get("type") == "tool_result"]

    if text_blocks:
        # The LLM produced reasoning text before crashing — that's
        # likely the bulk of a useful answer. ``str()`` wrap is a
        # defensive guard against an unexpected non-string ``text``
        # field (the loop itself only ever writes strings, but block
        # shapes can drift over time).
        parts.append(str(text_blocks[-1].get("text") or "").strip())

    if tool_use_blocks:
        tool_names = ", ".join(
            sorted({b.get("name", "?") for b in tool_use_blocks})
        )
        empty_or_error = sum(
            1 for b in tool_result_blocks
            if b.get("is_error") or "未找到" in (b.get("summary") or "")
            or "0 条" in (b.get("summary") or "")
            or "⊘" in (b.get("summary") or "")
        )
        parts.append(
            f"\n\n---\n本轮我已尝试调用：{tool_names}"
            + (
                f"（其中 {empty_or_error} 个未返回有效数据）"
                if empty_or_error else ""
            )
            + "。"
        )

    # Friendly close — never blame the user.
    parts.append(
        "\n\n执行链路中途断开，没能完整跑完。可以再发一次相同的问题让我重试，"
        "或者把问题拆得更具体一点 —— 比如直接给关键词 / 公司名 / 技术方向，"
        "通常能跳过工具直接答。"
    )

    # Last: a small dev-debug line (kept short — users will see it
    # but it's not the headline). Strip backticks so an error message
    # containing them doesn't break the surrounding markdown code-span.
    safe_err = (error_message or "")[:200].replace("`", "'")
    parts.append(f"\n\n_错误详情_: `{safe_err}`")

    body = "".join(parts).strip()
    return body or "执行过程中断，请稍后重试。"


class AgentLoopStrategy:
    """The L2 ReAct execution strategy."""

    name = "agent"

    def __init__(self) -> None:
        # Subsystems are constructed lazily in execute() so the strategy
        # object itself is cheap to instantiate (per-turn).
        pass

    # ── Public entry: execute one turn ────────────────────────────

    async def execute(
        self,
        ctx: StrategyContext,
        result: StrategyResult,
    ) -> AsyncGenerator[HarnessEvent, None]:
        # ── Per-turn state ────────────────────────────────────────
        budget = AgentBudget(started_at=time.perf_counter())
        client, profile = build_async_openai_client_for_role("agent")
        compactor = QueryLoopCompactor(profile=profile)

        # Per-turn tool gating. When the global-memory toggle is OFF
        # for this session, drop ``recall_memory`` and ``save_memory``
        # from the LLM's tool manifest entirely (Claude Code's
        # ``isAutoMemoryEnabled=false`` semantics). The pre-fix
        # behaviour kept them visible so the LLM "wouldn't be confused
        # by an asymmetric tool list" — but in practice the LLM
        # eagerly called them, got back a 273-char ``disabled`` refusal,
        # and the user saw a noisy "✅ 完成 (273 chars)" card for what
        # was really a no-op. Hiding the tools is the honest signal.
        from app.services.memory.recall_policy import (
            is_global_memory_enabled_for_session,
        )
        global_memory_on = is_global_memory_enabled_for_session(
            ctx.session_id, ctx.user_id,
        )
        excluded_tools: set[str] = (
            set() if global_memory_on else {"recall_memory", "save_memory"}
        )
        tool_schemas = registry.get_openai_schemas(exclude=excluded_tools)
        manifest_text = registry.format_manifest(exclude=excluded_tools)

        # Persistent trace surface (developer view) lives in agent_runs/
        # agent_steps. The user-facing transcript with content_blocks
        # is built up in ``blocks`` below and handed back via
        # ``result.assistant_blocks`` for the engine to persist.
        run_id = await create_run(
            user_id=ctx.user_id, session_id=ctx.session_id,
            goal=ctx.user_message, mode="function_calling",
        )
        ctx.run_id = run_id

        post_sampling_hooks = PostSamplingHookRunner(
            run_id=run_id,
            session_id=ctx.session_id,
            user_id=ctx.user_id,
        )

        # Render the full AssembledContext so the agent sees memory +
        # debrief reference + RAG chunks + session state + recent
        # turns. The system_prompt slot is suppressed here — the agent
        # has its own SYSTEM_PROMPT loaded as a separate message —
        # but every other SLOT_ORDER slot reaches the LLM.
        from app.services.chat.context_assembly_pipeline import prompt_renderer
        grounding_text = (
            prompt_renderer.render_answer_prompt(ctx.assembled, system_prompt="")
            if ctx.assembled is not None else "No context."
        )

        # Three system messages in cache-friendly order: stable →
        # less-stable → per-turn. DeepSeek's prompt cache (the L1/L2
        # default provider) hashes the prefix as a single contiguous
        # span IMPLICITLY — a per-turn change in the grounding text
        # would otherwise invalidate the cached tokens for the manifest
        # too, costing 800-2000 cached-token misses per turn. Splitting
        # into separate messages lets DeepSeek reuse the SYSTEM_PROMPT
        # + manifest prefix across every turn in a session.
        #
        # Order is load-bearing: the cache prefix only extends as far
        # as the longest stable run. Putting the stable manifest
        # before the per-turn grounding ensures the manifest tokens
        # are inside the cacheable prefix even when grounding_text
        # changes byte-by-byte across turns.
        #
        # NB for Anthropic: Claude requires EXPLICIT ``cache_control``
        # markers per content block to actually cache. The message
        # boundary split alone does nothing for Claude. If we add an
        # Anthropic backend, the manifest message needs a
        # ``cache_control: {"type": "ephemeral"}`` annotation —
        # tracked as a follow-up.
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "system", "content": f"Available tools:\n{manifest_text}"},
            {"role": "system", "content": (
                f"Conversation context:\n{grounding_text or 'No context.'}"
            )},
            {"role": "user", "content": ctx.user_message},
        ]

        # Accumulated Anthropic-style content blocks for the final
        # assistant turn. Built up as the loop encounters text / tool
        # calls / tool results so the persisted message faithfully
        # replays the same UX the frontend showed live.
        blocks: list[dict[str, Any]] = []

        # Trace blob mirrored to agent_steps for the developer view.
        trace: list[dict[str, Any]] = []

        status = "completed"
        error_message: str | None = None
        final_answer = ""

        try:
            async for event in self._loop(
                ctx=ctx,
                messages=messages,
                blocks=blocks,
                trace=trace,
                budget=budget,
                client=client,
                profile=profile,
                compactor=compactor,
                tool_schemas=tool_schemas,
                post_sampling_hooks=post_sampling_hooks,
                run_id=run_id,
            ):
                if event.type.value == "text":
                    final_answer = event.data.get("content", "")
                yield event
        except Exception as exc:
            status = "failed"
            error_message = str(exc)
            # Don't end on a dead "请稍后重试" — that throws away every
            # tool call the user just watched run. If we have any
            # accumulated text or tool results, render a graceful
            # partial-answer fallback referencing them. The LLM can't
            # be called again from inside an except block (the client
            # might be in a bad state), but we can deterministically
            # build a message that's strictly better than a generic
            # "I failed".
            final_answer = _build_graceful_fallback(
                blocks=blocks,
                error_message=str(exc),
            )
            logger.error("AgentLoopStrategy crashed: %s", exc)
            await append_step(
                run_id=run_id, step_index=budget.steps + 1,
                action_type="error", observation={"error": str(exc)},
                assistant_content="", is_error=True, latency_ms=0.0,
            )
        finally:
            # Always persist agent_runs row (developer view) even on
            # failure — separate from the user-facing chat transcript
            # which the ConversationEngine handles uniformly.
            await finish_run(
                run_id=run_id, status=status,
                final_answer=final_answer,
                steps_used=budget.steps,
                tool_calls=budget.tool_calls,
                prompt_tokens=budget.prompt_tokens,
                completion_tokens=budget.completion_tokens,
                total_latency_ms=round(budget.elapsed_seconds * 1000, 2),
                error_message=error_message,
                budget_stop_reason=budget.stop_reason,
            )

        # Ensure a trailing text block exists (so the persisted message
        # always carries a final answer, even when the loop ended on
        # budget stop).
        if not final_answer:
            final_answer = (
                f"Agent 执行因预算策略停止: {budget.stop_reason}. "
                "请缩小目标范围后重试。"
                if budget.stop_reason else "Agent 无法生成最终回答。"
            )
            blocks.append({"type": "text", "text": final_answer})
        elif not blocks or blocks[-1].get("type") != "text":
            blocks.append({"type": "text", "text": final_answer})

        result.final_answer = final_answer
        result.assistant_blocks = blocks
        result.prompt_tokens = budget.prompt_tokens
        result.completion_tokens = budget.completion_tokens
        result.tool_calls = budget.tool_calls
        result.steps_used = budget.steps
        result.stop_reason = budget.stop_reason
        # Surface run_id so callers of the batch API (run_react_agent)
        # can plumb it back to the UI for trace lookups. Engine
        # passes ``ctx`` through to the strategy untouched, so this
        # mutation is safe.
        result.extras["run_id"] = run_id

        # Final budget event carries run_id so the batch wrapper
        # (run_react_agent) can plumb it back to the API response —
        # the streaming wire format doesn't have a dedicated channel
        # for one-shot identifiers and adding a new HarnessEvent type
        # would break existing frontend dispatchers. The frontend
        # already ignores fields it doesn't recognise on budget.
        budget_payload = budget.to_dict()
        budget_payload["run_id"] = run_id
        yield HarnessEvent.budget(
            budget_payload,
            step=budget.steps,
            elapsed_ms=round(budget.elapsed_seconds * 1000, 2),
        )

    # ── Inner loop ────────────────────────────────────────────────

    async def _loop(
        self,
        *,
        ctx: StrategyContext,
        messages: list[dict[str, Any]],
        blocks: list[dict[str, Any]],
        trace: list[dict[str, Any]],
        budget: AgentBudget,
        client: Any,
        profile: Any,
        compactor: QueryLoopCompactor,
        tool_schemas: list[dict[str, Any]],
        post_sampling_hooks: PostSamplingHookRunner,
        run_id: str,
    ) -> AsyncGenerator[HarnessEvent, None]:
        # Track which text we've already emitted as a block so the
        # final pass doesn't double-count.
        pending_text_for_block = ""

        while True:
            # Budget check
            stop = budget.check()
            if stop:
                budget.stop_reason = stop
                await append_step(
                    run_id=run_id, step_index=budget.steps + 1,
                    action_type="budget_stop",
                    observation={"error": stop},
                    assistant_content="", is_error=True, latency_ms=0.0,
                )
                break

            budget.consume_step()

            # Layer 1 + 2 of the compactor (pre-LLM pruning + token warning)
            messages[:] = compactor.pre_llm_compact(messages, budget.prompt_tokens)
            if compactor.is_at_blocking_limit(budget.prompt_tokens):
                budget.stop_reason = "context_window_exhausted"
                await append_step(
                    run_id=run_id, step_index=budget.steps,
                    action_type="budget_stop",
                    observation={"error": "context_window_exhausted"},
                    assistant_content="", is_error=True, latency_ms=0.0,
                )
                yield HarnessEvent.error(
                    "上下文窗口即将耗尽，停止执行。请缩小目标范围后重试。",
                    step=budget.steps,
                    elapsed_ms=round(budget.elapsed_seconds * 1000, 2),
                )
                break

            stream, _ = await self._call_llm_stream(
                client=client, profile=profile, messages=messages,
                tool_schemas=tool_schemas, compactor=compactor, budget=budget,
            )

            assistant_content = ""
            tool_calls_acc: list[_ToolCallAccumulator] = []
            # Thinking-mode reasoning trace must round-trip back to the
            # API on the next assistant message — accumulate it here
            # and pass to ``_execute_tools`` which writes the message.
            reasoning_acc: list[str] = []
            stream_started_at = time.perf_counter()

            async for ev in self._consume_stream(
                stream, budget, tool_calls_acc, reasoning_acc,
            ):
                if isinstance(ev, HarnessEvent):
                    yield ev
                elif isinstance(ev, str):
                    assistant_content += ev

            latency_ms = round((time.perf_counter() - stream_started_at) * 1000, 2)
            compactor.reset_circuit_breaker()

            # If the model emitted any text in this turn (whether it
            # ends in tool_calls or final answer), capture it as a
            # block before any tool blocks are appended. This keeps
            # the storyline order: text → tools → text → tools → text.
            if assistant_content:
                pending_text_for_block += assistant_content
                if tool_calls_acc:
                    blocks.append({
                        "type": "text", "text": pending_text_for_block.strip(),
                    })
                    pending_text_for_block = ""

            if tool_calls_acc:
                async for ev in self._execute_tools(
                    ctx=ctx, messages=messages, blocks=blocks,
                    trace=trace, tool_calls_acc=tool_calls_acc,
                    assistant_content=assistant_content,
                    reasoning_content="".join(reasoning_acc),
                    budget=budget, post_sampling_hooks=post_sampling_hooks,
                    run_id=run_id,
                ):
                    yield ev
                continue

            if assistant_content:
                # Final answer — terminator for the loop. NB:
                # ``reasoning_acc`` is intentionally NOT persisted on
                # this path. The thinking trace is intra-turn only —
                # it must round-trip while the loop is calling tools
                # within a single user-turn, but the persisted message
                # (``content_blocks_json``) carries only the visible
                # ``text`` blocks. On the NEXT user turn we start
                # fresh from system + persisted blocks; the model
                # generates new reasoning_content for that turn from
                # scratch. Discarding is correct.
                trace.append({
                    "step": budget.steps, "tool": None, "args": {},
                    "observation": {}, "latency_ms": latency_ms,
                    "is_error": False,
                })
                await append_step(
                    run_id=run_id, step_index=budget.steps,
                    action_type="final_answer",
                    assistant_content=assistant_content,
                    observation={}, is_error=False, latency_ms=latency_ms,
                )
                blocks.append({"type": "text", "text": assistant_content})
                yield HarnessEvent.text(
                    assistant_content, step=budget.steps,
                    elapsed_ms=round(budget.elapsed_seconds * 1000, 2),
                )
                break

            # Empty response → nudge for an explicit final answer.
            messages.append({
                "role": "user",
                "content": "Please provide a final answer now based on gathered tool outputs.",
            })

    # ── LLM streaming primitives ──────────────────────────────────

    async def _call_llm_stream(
        self,
        *,
        client: Any,
        profile: Any,
        messages: list[dict[str, Any]],
        tool_schemas: list[dict[str, Any]],
        compactor: QueryLoopCompactor,
        budget: AgentBudget,
    ) -> tuple[Any, float]:
        async def _make_call() -> Any:
            return await client.chat.completions.create(
                model=profile.model,
                messages=messages,
                tools=tool_schemas if tool_schemas else None,
                tool_choice="auto" if tool_schemas else None,
                temperature=settings.AGENT_TEMPERATURE,
                max_tokens=settings.AGENT_MAX_RESPONSE_TOKENS,
                stream=True,
                stream_options={"include_usage": True},
            )

        async def _on_context_too_long() -> bool:
            messages[:], should_retry = compactor.on_context_too_long(messages)
            if should_retry:
                budget.refund_step()
            return should_retry

        started = time.perf_counter()
        stream = await call_with_retry(
            _make_call, max_retries=3,
            on_context_too_long=_on_context_too_long,
        )
        return stream, round((time.perf_counter() - started) * 1000, 2)

    async def _consume_stream(
        self,
        stream: Any,
        budget: AgentBudget,
        tool_calls_acc: list[_ToolCallAccumulator],
        reasoning_acc: list[str],
    ) -> AsyncGenerator[HarnessEvent | str, None]:
        """Yield either a HarnessEvent (text_delta) for SSE OR a raw
        text-chunk str for the loop to accumulate.

        ``reasoning_acc`` is a mutable single-element-style list the
        caller passes in to capture the model's ``reasoning_content``
        (DeepSeek / o1-style thinking-mode field). Same pattern as
        ``tool_calls_acc``: out-of-band side-channel because the yield
        protocol is already overloaded with two types. We do NOT yield
        reasoning as ``text_delta`` — it's the model's internal scratch
        pad and the frontend doesn't render it; we only need it to
        replay back into the NEXT LLM call (the API errors out
        otherwise — see issue C in commit message).
        """
        index_map: dict[int, _ToolCallAccumulator] = {}
        saw_tool_call = False

        async for chunk in stream:
            if hasattr(chunk, "usage") and chunk.usage is not None:
                usage = chunk.usage
                budget.prompt_tokens += int(getattr(usage, "prompt_tokens", 0) or 0)
                budget.completion_tokens += int(getattr(usage, "completion_tokens", 0) or 0)

            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta

            # Thinking-mode reasoning trace. DeepSeek V3.x / V4 Flash
            # and OpenAI o1-mini stream this on a separate ``delta``
            # field. The downstream API REQUIRES us to send it back
            # on the next-turn assistant message — without it the
            # second LLM call rejects with HTTP 400 "The
            # reasoning_content in the thinking mode must be passed
            # back to the API". So we accumulate even though we never
            # surface it to the UI.
            reasoning_piece = getattr(delta, "reasoning_content", None)
            if reasoning_piece:
                reasoning_acc.append(str(reasoning_piece))

            if delta.content:
                # Always accumulate into the loop's local text buffer.
                yield delta.content
                if not saw_tool_call:
                    yield HarnessEvent.text_delta(
                        delta.content, step=budget.steps,
                        elapsed_ms=round(budget.elapsed_seconds * 1000, 2),
                    )

            if delta.tool_calls:
                saw_tool_call = True
                for tc_delta in delta.tool_calls:
                    idx = tc_delta.index
                    if idx not in index_map:
                        acc = _ToolCallAccumulator(
                            id=tc_delta.id or "",
                            name=(tc_delta.function.name
                                  if tc_delta.function and tc_delta.function.name else ""),
                            arguments="",
                        )
                        index_map[idx] = acc
                        tool_calls_acc.append(acc)
                    else:
                        acc = index_map[idx]
                    if tc_delta.id:
                        acc.id = tc_delta.id
                    if tc_delta.function:
                        if tc_delta.function.name:
                            acc.name = tc_delta.function.name
                        if tc_delta.function.arguments:
                            acc.arguments += tc_delta.function.arguments

    # ── Tool execution ────────────────────────────────────────────

    async def _execute_tools(
        self,
        *,
        ctx: StrategyContext,
        messages: list[dict[str, Any]],
        blocks: list[dict[str, Any]],
        trace: list[dict[str, Any]],
        tool_calls_acc: list[_ToolCallAccumulator],
        assistant_content: str,
        reasoning_content: str,
        budget: AgentBudget,
        post_sampling_hooks: PostSamplingHookRunner,
        run_id: str,
    ) -> AsyncGenerator[HarnessEvent, None]:
        # ``reasoning_content`` (thinking-mode trace) MUST round-trip
        # back to the API on the next assistant message — otherwise
        # DeepSeek V4 Flash / o1-style models reject the next call with
        # HTTP 400 "The reasoning_content in the thinking mode must be
        # passed back to the API". We attach it conditionally so plain
        # (non-thinking) models that never produce reasoning_content
        # don't get a confusing empty field.
        assistant_msg: dict[str, Any] = {
            "role": "assistant",
            "content": assistant_content,
            "tool_calls": [_tool_call_payload(c) for c in tool_calls_acc],
        }
        if reasoning_content:
            assistant_msg["reasoning_content"] = reasoning_content
        messages.append(assistant_msg)

        turn_tool_messages: list[dict[str, Any]] = []

        for tc in tool_calls_acc:
            tool_name = tc.name
            tool_error = False
            tool_started = time.perf_counter()

            # Capture the tool_use BLOCK before invoking — so the UI
            # can show a "running" folded card even mid-flight (in the
            # future when streaming tool persistence lands).
            try:
                parsed_args = parse_tool_arguments(tc.arguments)
            except Exception:
                parsed_args = {}
            tool_use_block = {
                "type": "tool_use",
                "id": tc.id,
                "name": tool_name,
                "input": parsed_args,
            }

            yield HarnessEvent.tool_start(
                tool_name, _args_summary(tc.arguments),
                step=budget.steps,
                elapsed_ms=round(budget.elapsed_seconds * 1000, 2),
                tool_call_id=tc.id,
            )

            observation: dict[str, Any]
            if budget.tool_usage[tool_name] >= settings.AGENT_MAX_CALLS_PER_TOOL:
                observation = {"error": "tool_call_limit_exceeded", "tool_name": tool_name}
                tool_error = True
            elif tool_name not in registry:
                observation = {"error": "unknown_tool", "tool_name": tool_name}
                tool_error = True
            else:
                try:
                    tool_ctx = AgentToolContext(
                        user_id=ctx.user_id, session_id=ctx.session_id,
                    )
                    observation = await asyncio.wait_for(
                        registry.dispatch(tool_name, parsed_args, tool_ctx),
                        timeout=settings.AGENT_TOOL_TIMEOUT_SECONDS,
                    )
                    if "error" in observation:
                        tool_error = True
                except asyncio.TimeoutError:
                    observation = {"error": "tool_timeout", "tool_name": tool_name}
                    tool_error = True
                except ValueError as exc:
                    observation = {"error": str(exc)}
                    tool_error = True
                except Exception as exc:  # noqa: BLE001
                    observation = {"error": "tool_execution_failed", "detail": str(exc)}
                    tool_error = True

            budget.consume_tool_call(tool_name)
            latency_ms = round((time.perf_counter() - tool_started) * 1000, 2)

            # Persist large tool results to disk; the LLM context only
            # keeps a small preview pointer.
            result_text = safe_json_dumps(observation)
            result_text = maybe_persist_result(
                content=result_text,
                tool_name=tool_name,
                tool_call_id=tc.id,
                session_id=ctx.session_id,
            )

            tool_msg = {
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result_text,
            }
            messages.append(tool_msg)
            turn_tool_messages.append(tool_msg)

            trace.append({
                "step": budget.steps, "tool": tool_name,
                "args": parsed_args if not tool_error else {},
                "observation": observation,
                "latency_ms": latency_ms, "is_error": tool_error,
            })

            # Persistent chain (frontend folded-card replay).
            # ``content`` carries the full LLM-visible result text,
            # which is either the raw JSON observation or a
            # ``<persisted-output ...>`` pointer string. The frontend
            # uses ``content`` to render the expanded view and
            # ``summary`` as the always-visible folded label.
            blocks.append(tool_use_block)
            blocks.append({
                "type": "tool_result",
                "tool_use_id": tc.id,
                "is_error": tool_error,
                "latency_ms": latency_ms,
                "summary": _result_summary(observation),
                "content": result_text,
            })

            await append_step(
                run_id=run_id, step_index=budget.steps,
                action_type="tool_call", tool_name=tool_name,
                tool_call_id=tc.id,
                tool_args=parsed_args if not tool_error else {},
                observation=observation,
                assistant_content=assistant_content,
                is_error=tool_error, latency_ms=latency_ms,
            )

            yield HarnessEvent.tool_done(
                tool_name, _result_summary(observation),
                step=budget.steps,
                elapsed_ms=round(budget.elapsed_seconds * 1000, 2),
                tool_latency_ms=latency_ms, is_error=tool_error,
                # Ship the full result text on the wire so the live
                # tool card can render the expanded view without a
                # refresh. ``result_text`` is already capped at the
                # per-tool ``max_result_chars`` ceiling so this won't
                # blow up an SSE frame.
                result_content=result_text,
                # Mirror tool_start's id so the frontend can pair the
                # tool_use / tool_result blocks by id rather than the
                # ambient FIFO order — robust to parallel tools and
                # makes the live-stream shape match the persisted
                # blocks loaded by ``/chat/transcript``.
                tool_call_id=tc.id,
            )

        if turn_tool_messages:
            enforce_turn_budget(turn_tool_messages, ctx.session_id)

        if post_sampling_hooks:
            await post_sampling_hooks.execute(
                step=budget.steps,
                messages=messages,
                tool_results=turn_tool_messages,
                budget_snapshot=budget.to_dict(),
            )


__all__ = ["AgentLoopStrategy"]
