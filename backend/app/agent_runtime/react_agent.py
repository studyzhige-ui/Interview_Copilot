import asyncio
import logging
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from app.agent_runtime.tools import (
    AgentToolContext,
    build_default_tool_registry,
    build_openai_tool_schemas,
    format_tool_manifest,
    format_validation_error,
    parse_tool_arguments,
    safe_json_dumps,
)
from app.core.config import settings
from app.core.model_registry import build_async_openai_client_for_role
from app.services.agent_trace_service import append_step, create_run, finish_run
from app.services.context_service import context_pipeline
from app.services.interview_state_service import interview_state_service
from app.services.memory_extraction_service import (
    memory_retrieval_service,
    post_turn_maintenance_service,
)
from app.services.transcript_service import transcript_service

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """
You are a planning-and-execution job assistant.
Solve the user's goal by deciding when to call tools and when to answer directly.

Rules:
- Use tools only when needed.
- Never fabricate tool outputs.
- Prefer concise, actionable answers.
- If data is missing, say what is missing and ask for concrete next info.
- Treat working state and interview state as the source of truth for current session progress.
"""


@dataclass
class AgentBudget:
    started_at: float
    steps: int = 0
    tool_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    stop_reason: str | None = None

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    @property
    def elapsed_seconds(self) -> float:
        return time.perf_counter() - self.started_at

    def check(self) -> str | None:
        if self.steps >= settings.AGENT_MAX_STEPS:
            return "max_steps_exceeded"
        if self.tool_calls >= settings.AGENT_MAX_TOOL_CALLS:
            return "max_tool_calls_exceeded"
        if self.total_tokens >= settings.AGENT_MAX_TOTAL_TOKENS:
            return "token_budget_exceeded"
        if self.elapsed_seconds >= settings.AGENT_MAX_RUNTIME_SECONDS:
            return "runtime_timeout"
        return None


def _tool_call_payload(tool_call: Any) -> dict[str, Any]:
    return {
        "id": tool_call.id,
        "type": "function",
        "function": {
            "name": tool_call.function.name,
            "arguments": tool_call.function.arguments,
        },
    }


def _tool_observation_for_llm(observation: Any) -> str:
    text = safe_json_dumps(observation)
    limit = settings.AGENT_OBSERVATION_CHAR_LIMIT
    return text if len(text) <= limit else text[:limit] + "...(truncated)"


async def _append_budget_stop_trace(run_id: str, step_index: int, reason: str) -> None:
    await append_step(
        run_id=run_id,
        step_index=step_index,
        action_type="budget_stop",
        observation={"error": reason},
        assistant_content="",
        is_error=True,
        latency_ms=0.0,
    )


async def run_react_agent(
    user_message: str,
    user_id: str,
    session_id: str,
) -> dict[str, Any]:
    transcript_service.ensure_session(session_id, user_id)
    interview_state_service.ensure_state(session_id, user_id)

    relevant_memories = await memory_retrieval_service.recall_relevant(
        user_id=user_id,
        query=user_message,
    )
    assembled = context_pipeline.assemble_answer_context(
        session_id=session_id,
        user_id=user_id,
        current_query=user_message,
        relevant_memories=relevant_memories,
    )

    registry = build_default_tool_registry()
    tool_schemas = build_openai_tool_schemas(registry)
    tool_manifest = format_tool_manifest(registry)
    tool_usage_by_name: dict[str, int] = defaultdict(int)

    run_id = await create_run(
        user_id=user_id,
        session_id=session_id,
        goal=user_message,
        mode="function_calling",
    )

    budget = AgentBudget(started_at=time.perf_counter())
    trace: list[dict[str, Any]] = []
    final_answer = ""
    status = "completed"
    error_message: str | None = None

    client, agent_profile = build_async_openai_client_for_role("agent")
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "system",
            "content": (
                f"Available tools:\n{tool_manifest}\n\n"
                f"Conversation context:\n{assembled.context_text or 'No context.'}"
            ),
        },
        {"role": "user", "content": user_message},
    ]

    try:
        while True:
            stop_reason = budget.check()
            if stop_reason:
                budget.stop_reason = stop_reason
                status = "stopped"
                await _append_budget_stop_trace(
                    run_id=run_id,
                    step_index=budget.steps + 1,
                    reason=stop_reason,
                )
                break

            budget.steps += 1
            started = time.perf_counter()
            response = await client.chat.completions.create(
                model=agent_profile.model,
                messages=messages,
                tools=tool_schemas,
                tool_choice="auto",
                temperature=settings.AGENT_TEMPERATURE,
                max_tokens=settings.AGENT_MAX_RESPONSE_TOKENS,
            )
            latency_ms = round((time.perf_counter() - started) * 1000.0, 2)

            usage = response.usage
            if usage:
                budget.prompt_tokens += int(getattr(usage, "prompt_tokens", 0) or 0)
                budget.completion_tokens += int(getattr(usage, "completion_tokens", 0) or 0)

            choice = response.choices[0]
            message = choice.message
            assistant_content = (message.content or "").strip()
            tool_calls = list(message.tool_calls or [])

            if tool_calls:
                messages.append(
                    {
                        "role": "assistant",
                        "content": message.content or "",
                        "tool_calls": [_tool_call_payload(call) for call in tool_calls],
                    }
                )
                for tool_call in tool_calls:
                    tool_name = tool_call.function.name
                    tool_args: dict[str, Any] = {}
                    tool_error = False
                    started = time.perf_counter()

                    if budget.tool_calls >= settings.AGENT_MAX_TOOL_CALLS:
                        observation = {"error": "max_tool_calls_exceeded"}
                        tool_error = True
                    elif tool_usage_by_name[tool_name] >= settings.AGENT_MAX_CALLS_PER_TOOL:
                        observation = {
                            "error": "tool_call_limit_exceeded",
                            "tool_name": tool_name,
                            "limit": settings.AGENT_MAX_CALLS_PER_TOOL,
                        }
                        tool_error = True
                    elif tool_name not in registry:
                        observation = {"error": "unknown_tool", "tool_name": tool_name}
                        tool_error = True
                    else:
                        try:
                            tool_args = parse_tool_arguments(tool_call.function.arguments)
                            observation = await asyncio.wait_for(
                                registry[tool_name].execute(
                                    tool_args,
                                    AgentToolContext(user_id=user_id, session_id=session_id),
                                ),
                                timeout=settings.AGENT_TOOL_TIMEOUT_SECONDS,
                            )
                        except ValidationError as exc:
                            observation = format_validation_error(exc)
                            tool_error = True
                        except ValueError as exc:
                            observation = {"error": str(exc)}
                            tool_error = True
                        except asyncio.TimeoutError:
                            observation = {"error": "tool_timeout", "tool_name": tool_name}
                            tool_error = True
                        except Exception as exc:  # noqa: BLE001
                            observation = {
                                "error": "tool_execution_failed",
                                "detail": str(exc),
                            }
                            tool_error = True

                    budget.tool_calls += 1
                    tool_usage_by_name[tool_name] += 1
                    tool_latency_ms = round((time.perf_counter() - started) * 1000.0, 2)
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": _tool_observation_for_llm(observation),
                        }
                    )
                    trace.append(
                        {
                            "step": budget.steps,
                            "tool": tool_name,
                            "args": tool_args,
                            "observation": observation,
                            "latency_ms": tool_latency_ms,
                            "is_error": tool_error,
                        }
                    )
                    await append_step(
                        run_id=run_id,
                        step_index=budget.steps,
                        action_type="tool_call",
                        tool_name=tool_name,
                        tool_call_id=tool_call.id,
                        tool_args=tool_args,
                        observation=observation,
                        assistant_content=assistant_content,
                        is_error=tool_error,
                        latency_ms=tool_latency_ms,
                    )
                continue

            if assistant_content:
                final_answer = assistant_content
                trace.append(
                    {
                        "step": budget.steps,
                        "tool": None,
                        "args": {},
                        "observation": {},
                        "latency_ms": latency_ms,
                        "is_error": False,
                    }
                )
                await append_step(
                    run_id=run_id,
                    step_index=budget.steps,
                    action_type="final_answer",
                    assistant_content=assistant_content,
                    observation={},
                    is_error=False,
                    latency_ms=latency_ms,
                )
                break

            messages.append(
                {
                    "role": "user",
                    "content": "Please provide a final answer now based on gathered tool outputs.",
                }
            )

        if not final_answer:
            if budget.stop_reason:
                final_answer = (
                    f"Agent execution stopped due to budget policy: {budget.stop_reason}. "
                    "Please retry with a narrower goal."
                )
            else:
                final_answer = "Agent could not produce a final answer."

    except Exception as exc:  # noqa: BLE001
        status = "failed"
        error_message = str(exc)
        final_answer = "Agent execution failed. Please retry later."
        logger.error("Agent execution failed: %s", exc)
        await append_step(
            run_id=run_id,
            step_index=budget.steps + 1,
            action_type="error",
            observation={"error": str(exc)},
            assistant_content="",
            is_error=True,
            latency_ms=0.0,
        )
    finally:
        await finish_run(
            run_id=run_id,
            status=status,
            final_answer=final_answer,
            steps_used=budget.steps,
            tool_calls=budget.tool_calls,
            prompt_tokens=budget.prompt_tokens,
            completion_tokens=budget.completion_tokens,
            total_latency_ms=round((time.perf_counter() - budget.started_at) * 1000.0, 2),
            error_message=error_message,
            budget_stop_reason=budget.stop_reason,
        )

    transcript_service.append_turn(
        session_id=session_id,
        user_id=user_id,
        user_msg=user_message,
        ai_msg=final_answer,
    )
    asyncio.create_task(post_turn_maintenance_service.run(session_id, user_id))
    return {
        "run_id": run_id,
        "reply": final_answer,
        "trace": trace,
        "steps_used": budget.steps,
        "tool_calls": budget.tool_calls,
        "prompt_tokens": budget.prompt_tokens,
        "completion_tokens": budget.completion_tokens,
        "budget_stop_reason": budget.stop_reason,
    }
