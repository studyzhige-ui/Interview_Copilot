"""Translate upstream exceptions into actionable, user-facing Chinese.

ONE place maps every foreseeable failure (auth, balance, rate limit,
model-not-found, context overflow, network, server) to a friendly
message with a concrete next step, so L1 chat, L2 agent, the SSE
last-resort net, and the engine all surface identical wording.

Philosophy (mirrors Claude Code's layered error handling — see the study
notes ``chapters/U.md``): low-level retries stay invisible; only a
user-actionable failure reaches the UI, and it always tells the user
what to DO, not merely that something broke. Automatic recovery
(retry / fallback model) is out of scope here — this module is purely
the "say it clearly" layer.

The OpenAI-compatible SDK only models a handful of statuses as dedicated
exception subclasses (401→AuthenticationError, 429→RateLimitError, …).
Vendor-specific statuses like DeepSeek's **402 Insufficient balance**
arrive as a generic ``APIStatusError`` whose only signal is
``status_code`` + the body message — so we classify by status code AND
message phrase, not exception type alone.
"""
from __future__ import annotations

import openai

# Message bodies as constants so callers + tests can assert on them
# without hard-coding the full string at every site.
MSG_AUTH = (
    "当前模型的密钥无效或已失效。请到「模型」页面，找到对应厂商卡片，"
    "重新配置 API 密钥后再试。"
)
MSG_BALANCE = (
    "当前所选模型的账户余额不足，无法继续调用。请到「模型」页面更换为其它可用模型，"
    "或为该厂商账户充值后再试。"
)
MSG_RATE_LIMIT = "模型厂商当前限流（请求过于频繁），请稍等几秒后重试。"
MSG_MODEL_NOT_FOUND = (
    "所选模型不存在或当前不可用。请到「模型」页面重新选择一个可用模型。"
)
MSG_CONTEXT = (
    "本次对话上下文过长，已超出模型的窗口上限。请缩小问题范围，或开启一个新会话后再试。"
)
MSG_CONNECTION = "无法连接到模型服务，请检查网络连接或稍后再试。"
MSG_TIMEOUT = "模型响应超时，请重试一次。"
MSG_SERVER = "模型服务暂时不可用（厂商端繁忙或故障），请稍后再试。"
MSG_GENERIC = (
    "系统出了点问题，请稍后再试。如果反复发生，请把这次操作的时间告诉运维。"
)

# Substring signals (matched case-insensitively against ``str(exc)``).
_BALANCE_PHRASES = (
    "insufficient_balance",
    "insufficient account balance",
    "insufficient_quota",
    "exceeded your current quota",
    "payment required",
    "余额不足",
    "欠费",
)
_CONTEXT_PHRASES = (
    "context_length_exceeded",
    "maximum context length",
    "reduce the length",
    "token limit",
    "context window",
    "prompt is too long",
)
_MODEL_NOT_FOUND_PHRASES = (
    "model_not_found",
    "does not exist",
    "no such model",
    "model not found",
)


def _status_code(exc: Exception) -> int | None:
    code = getattr(exc, "status_code", None)
    return code if isinstance(code, int) else None


def humanize_error(exc: Exception) -> str:
    """Map *exc* to an actionable, user-facing Chinese message.

    Ordering matters: the most specific / most actionable classifications
    win first (balance → auth → rate limit → not-found → context → network
    → server → bad-request → generic).
    """
    msg = str(exc).lower()
    status = _status_code(exc)

    # Balance / quota exhausted — retrying never helps; the user must
    # switch model or top up. DeepSeek surfaces this as HTTP 402.
    if status == 402 or any(p in msg for p in _BALANCE_PHRASES):
        return MSG_BALANCE

    # Auth — invalid / missing key, or forbidden.
    if isinstance(exc, (openai.AuthenticationError, openai.PermissionDeniedError)):
        return MSG_AUTH
    if status in (401, 403):
        return MSG_AUTH

    # Rate limit.
    if isinstance(exc, openai.RateLimitError) or status == 429:
        return MSG_RATE_LIMIT

    # Model not found / wrong model id.
    if (
        isinstance(exc, openai.NotFoundError)
        or status == 404
        or any(p in msg for p in _MODEL_NOT_FOUND_PHRASES)
    ):
        return MSG_MODEL_NOT_FOUND

    # Context window exceeded (often a 400 BadRequest — check before the
    # generic bad-request branch so the message is specific + actionable).
    if any(p in msg for p in _CONTEXT_PHRASES):
        return MSG_CONTEXT

    # Network / timeout. APITimeoutError subclasses APIConnectionError, so
    # test it FIRST.
    if isinstance(exc, openai.APITimeoutError) or "timeout" in msg or "timed out" in msg:
        return MSG_TIMEOUT
    if isinstance(exc, openai.APIConnectionError):
        return MSG_CONNECTION

    # Server-side (5xx / overloaded).
    if (
        isinstance(exc, openai.InternalServerError)
        or (status is not None and status >= 500)
        or "overloaded" in msg
        or "server_error" in msg
    ):
        return MSG_SERVER

    # Bad request (400) — surface the model's own reason when present.
    if isinstance(exc, openai.BadRequestError) or status == 400:
        detail = ""
        body = getattr(exc, "body", None)
        if isinstance(body, dict):
            err = body.get("error")
            if isinstance(err, dict):
                detail = str(err.get("message") or "")
        if detail:
            return f"请求被模型拒绝：{detail}"
        return "请求被模型拒绝（可能是参数不合规或上下文过长）。"

    return MSG_GENERIC


__all__ = ["humanize_error"]
