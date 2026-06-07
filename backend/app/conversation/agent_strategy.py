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

Developer trace observability lives in LangSmith (every LLM call is
auto-captured by ``wrap_openai`` in ``core/llm_tracing.py``). The
former ``agent_runs`` + ``agent_steps`` persistence was deleted in
the audit cleanup — LangSmith covers the same surface with a UI for
free, and the user-facing tool cards still come from
``chat_messages.content_blocks_json``.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, AsyncGenerator

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
from app.core.error_messages import humanize_error
from app.core.model_registry import build_async_openai_client_for_role

# Trigger tool self-registration on first import.
import app.agent_runtime.tools  # noqa: F401

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """你是 Interview Copilot 的执行 Agent，通过调用工具帮助用户完成面试准备相关的复杂任务。

# 能力
- 分析岗位要求（JD）与用户能力之间的差距
- 基于面试历史识别薄弱环节，制定学习计划
- 检索互联网与知识库，获取面经、公司信息、技术资料
- 将重要结论沉淀到记忆（仅当全局记忆开启），并可导出分析报告与学习笔记为文件

# 工具使用原则
- 先判断再调用：先想清楚问题是否需要工具、需要哪个，不要一上来就并发调用多个工具。
- 工具是数据增强，不是知识替代：能用自身知识直接回答的（公司、技术栈、框架对比、最佳实践、常见面试题等）直接回答；工具只用于补充时效性强的、用户私有的、你不掌握的数据。
- 主动组合：单个工具结果不足时，主动用其它工具补全后再作答。
- 尊重工具状态：工具返回 disabled 时不再调用；工具未出现在 manifest 中即表示该功能未启用，不要假装会用。

# 错误处理
- 工具失败或返回空不等于任务失败：结合已有领域知识与部分工具结果，仍要给出有用的回答。
- 友好转译失败：不直接抛出技术报错，也不以「失败，请重试」收尾；说明缺少了哪些信息，并给出具体的下一步建议。

# 输出规则
- 给出结构化、可执行的建议。
- 不编造工具未返回的数据。
- 知识 / 概念类问题直接回答，不绕弯调工具。
- 始终为用户留下至少一个可以立刻执行的下一步。
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


# Repeated identical tool calls (same tool + same args) are steered with a soft
# nudge at these counts — never a hard stop (the step valve is the only hard
# limit). Replaces the old per-tool hard cap.
_REPEAT_NUDGE_SOFT = 3
_REPEAT_NUDGE_FIRM = 6


def _repeat_call_nudge(tool_name: str, count: int) -> str:
    """Soft-steer message when a tool is re-called with identical arguments."""
    base = (
        f"Note: `{tool_name}` has now been called {count} times with identical "
        f"arguments — repeating it rarely yields new information."
    )
    if count >= _REPEAT_NUDGE_FIRM:
        return (
            base + " Stop repeating it: change the arguments, try a different "
            "tool, or give your final answer based on what you already have."
        )
    return (
        base + " Consider changing the arguments, trying a different tool, or "
        "answering with what you have."
    )


def _reconstruct_history_messages(turns: list[dict]) -> list[dict[str, Any]]:
    """Rebuild prior conversation turns as real OpenAI messages, including the
    agent's tool roundtrips (like Claude Code keeps the full message stream).

    Each persisted Agent turn carries Anthropic-style ``blocks`` (text /
    tool_use / tool_result). We reconstruct them into an ``assistant`` message
    (text + ``tool_calls``) followed by one ``tool`` message per tool_result —
    so on the next turn the agent sees what it already called, not just the
    final text. User turns become plain ``user`` messages. (orphaned pairs are
    repaired by ``compress()``'s sanitize before the first LLM call.)
    """
    messages: list[dict[str, Any]] = []
    for turn in turns:
        role = turn.get("role")
        if role == "User":
            messages.append({"role": "user", "content": turn.get("content", "")})
            continue
        if role != "Agent":
            continue
        text_parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        tool_messages: list[dict[str, Any]] = []
        for block in turn.get("blocks") or []:
            btype = block.get("type")
            if btype == "text":
                text_parts.append(str(block.get("text") or ""))
            elif btype == "tool_use":
                tool_calls.append({
                    "id": block.get("id", ""),
                    "type": "function",
                    "function": {
                        "name": block.get("name", ""),
                        "arguments": json.dumps(block.get("input") or {}, ensure_ascii=False),
                    },
                })
            elif btype == "tool_result":
                tool_messages.append({
                    "role": "tool",
                    "tool_call_id": block.get("tool_use_id", ""),
                    "content": str(block.get("content") or ""),
                })
        assistant: dict[str, Any] = {"role": "assistant", "content": "".join(text_parts)}
        if tool_calls:
            assistant["tool_calls"] = tool_calls
        messages.append(assistant)
        messages.extend(tool_messages)
    return messages


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
        client, profile = build_async_openai_client_for_role(
            "agent", user_id=ctx.user_id,
        )
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
        #
        # NB: ``ctx.global_memory_on`` is populated by the engine in
        # ``_prepare`` so we don't re-query the DB for the same
        # boolean (pre-P1-H this opened a second SessionLocal +
        # 2 sync queries per agent turn).
        excluded_tools: set[str] = (
            set() if ctx.global_memory_on else {"recall_memory", "save_memory"}
        )
        tool_schemas = registry.get_openai_schemas(exclude=excluded_tools)
        manifest_text = registry.format_manifest(exclude=excluded_tools)

        # Developer trace observability is handled by LangSmith
        # (``wrap_openai`` in core/llm_tracing.py captures every LLM
        # call automatically). User-facing tool cards come from the
        # ``content_blocks_json`` chain we build below in ``blocks``
        # and hand back via ``result.assistant_blocks`` for the
        # engine to persist on ``chat_messages``.

        # Build the agent's context through the SAME shared pipeline as L1
        # chat (one SLOT_ORDER, no separate agent assembler). L2 differs only
        # in the system-prompt slot: it carries the agent's SYSTEM_PROMPT +
        # the tool manifest — tools ARE part of the system prompt. SLOT_ORDER
        # owns the cache-stable ordering: the stable prefix (system / summary /
        # recent turns) precedes the per-turn grounding (memory / RAG) inside
        # the system block, so a grounding change can't evict the cached
        # prefix — no manual multi-message split needed.
        #
        # ``current_input`` is skipped here and sent as the user message
        # instead, so the model has a user turn to answer and the loop can
        # append assistant/tool turns after it.
        from app.services.chat.context_assembly_pipeline import prompt_renderer
        agent_system_prompt = f"{SYSTEM_PROMPT}\n\nAvailable tools:\n{manifest_text}"
        history_messages: list[dict[str, Any]] = []
        if ctx.assembled is not None:
            # L2 skips the flattened [Recent Turns] slot — prior turns are
            # spliced in as REAL messages (with tool roundtrips) instead, so the
            # agent sees its own tool history. current_input becomes the user msg.
            system_block = prompt_renderer.render_answer_prompt(
                ctx.assembled,
                system_prompt=agent_system_prompt,
                skip_fields={"current_input", "recent_turns"},
            )
            history_messages = _reconstruct_history_messages(ctx.assembled.recent_turns)
        else:
            system_block = agent_system_prompt
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_block},
            *history_messages,
            {"role": "user", "content": ctx.user_message},
        ]

        # Accumulated Anthropic-style content blocks for the final
        # assistant turn. Built up as the loop encounters text / tool
        # calls / tool results so the persisted message faithfully
        # replays the same UX the frontend showed live.
        blocks: list[dict[str, Any]] = []

        final_answer = ""

        try:
            async for event in self._loop(
                ctx=ctx,
                messages=messages,
                blocks=blocks,
                budget=budget,
                client=client,
                profile=profile,
                compactor=compactor,
                tool_schemas=tool_schemas,
            ):
                if event.type.value == "text":
                    final_answer = event.data.get("content", "")
                yield event
        except Exception as exc:
            logger.error("AgentLoopStrategy crashed: %s", exc)
            # Surface the failure to the LIVE stream as an actionable error.
            # THE BUG this fixes: pre-fix the except only built a fallback
            # into ``result`` (persisted) and never *yielded* anything, so a
            # clean API failure — e.g. a 402 "insufficient balance" on the
            # very first LLM call — left the user staring at an empty turn
            # with no idea what broke or how to fix it. ``humanize_error``
            # is the same translator the L1 chat path uses via the engine,
            # so the wording is identical regardless of which path failed.
            yield HarnessEvent.error(
                humanize_error(exc),
                step=budget.steps,
                elapsed_ms=round(budget.elapsed_seconds * 1000, 2),
            )
            # Still build the graceful partial answer for the PERSISTED
            # transcript so the tool work the user watched isn't lost on
            # reload. We deliberately don't re-raise: re-raising would route
            # through the engine's last-resort catch (a second error event)
            # and skip persistence of this partial answer.
            final_answer = _build_graceful_fallback(
                blocks=blocks,
                error_message=str(exc),
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

        # Final budget event for the FE's BudgetInfo handler. LangSmith
        # captures the same fields via the OpenAI wrap, but the FE
        # surfaces budget in-band on the SSE stream so the chat panel
        # can render token/step badges without a trace-service call.
        yield HarnessEvent.budget(
            budget.to_dict(),
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
        budget: AgentBudget,
        client: Any,
        profile: Any,
        compactor: QueryLoopCompactor,
        tool_schemas: list[dict[str, Any]],
    ) -> AsyncGenerator[HarnessEvent, None]:
        # Track which text we've already emitted as a block so the
        # final pass doesn't double-count.
        pending_text_for_block = ""

        while True:
            # Budget check
            stop = budget.check()
            if stop:
                budget.stop_reason = stop
                break

            budget.consume_step()

            # Proactive compaction: self-measure the prompt, run the cheap
            # pre-pass if it's over the threshold, and stop cleanly if the
            # result still sits at the blocking limit (a doomed LLM call).
            messages[:], at_blocking_limit = await compactor.compress(messages)
            if at_blocking_limit:
                budget.stop_reason = "context_window_exhausted"
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

            async for ev in self._consume_stream(
                stream, budget, tool_calls_acc, reasoning_acc,
            ):
                if isinstance(ev, HarnessEvent):
                    yield ev
                elif isinstance(ev, str):
                    assistant_content += ev

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
                    tool_calls_acc=tool_calls_acc,
                    assistant_content=assistant_content,
                    reasoning_content="".join(reasoning_acc),
                    budget=budget,
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
            messages[:], should_retry = await compactor.on_context_too_long(messages)
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
        tool_calls_acc: list[_ToolCallAccumulator],
        assistant_content: str,
        reasoning_content: str,
        budget: AgentBudget,
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
        nudge_repeat = 0
        nudge_tool = ""

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
            if tool_name not in registry:
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

            signature = f"{tool_name}\x00{tc.arguments}"
            repeat_count = budget.consume_tool_call(tool_name, signature)
            if repeat_count in (_REPEAT_NUDGE_SOFT, _REPEAT_NUDGE_FIRM):
                nudge_repeat, nudge_tool = repeat_count, tool_name
            latency_ms = round((time.perf_counter() - tool_started) * 1000, 2)

            # Persist large tool results to disk; the LLM context only
            # keeps a small preview pointer. maybe_persist_result does
            # sync file_path.write_text() for oversized content — offload
            # so a chatty agent step doesn't stall the loop on disk I/O.
            result_text = safe_json_dumps(observation)
            result_text = await asyncio.to_thread(
                maybe_persist_result,
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

        # Repeated identical tool calls: steer the model with a soft nudge
        # appended AFTER the tool results (never a hard stop — the step valve
        # is the only hard limit). Placed after the results so the
        # assistant(tool_calls)→tool→tool pairing stays intact.
        if nudge_repeat:
            messages.append({
                "role": "user",
                "content": _repeat_call_nudge(nudge_tool, nudge_repeat),
            })


__all__ = ["AgentLoopStrategy"]
