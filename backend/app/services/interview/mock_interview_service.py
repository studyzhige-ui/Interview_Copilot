"""Mock interview Runtime Director.

Designed to behave like a real human interviewer:

  1. Read resume + JD + persona once → freeze into a cacheable prefix.
  2. Open with a one-shot "interview brief" + opening line (LLM #1).
  3. Each turn: feed the director the cached prefix + map + history + the
     candidate's latest answer, and let it produce one natural utterance with
     control signals (LLM #2). The server validates the output and retries
     with a violation hint up to MAX_DIRECTOR_RETRIES times. The server never
     fabricates an interview question.
  4. Optionally, every 6 turns, condense the older qa_history into a 200-char
     summary (LLM #3) so the prompt input stays roughly flat.

Post-interview scoring is handled by the unified
``InterviewAnalysisOrchestrator``; this module is only the conducting layer.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from app.rag.embeddings import mock_interview_llm as _mock_llm

logger = logging.getLogger(__name__)


# ── Public constants ─────────────────────────────────────────────────────

INTERVIEWER_STYLES: dict[str, str] = {
    "friendly": (
        "你是一位温和友善的面试官，给候选人充分的思考时间和适度的引导。"
        "肯定为主，不咄咄逼人；当候选人卡壳时给出温和的提示。"
    ),
    "professional": (
        "你是一位专业、就事论事的面试官。节奏标准，问题清晰，不带情绪色彩。"
        "回答到位就推进，模糊就追问一层。"
    ),
    "rigorous": (
        "你是一位严谨挑剔的面试官，会追究边界 case 和具体细节。"
        "追问比较尖锐，但保持职业；不允许笼统含糊的回答蒙混过去。"
    ),
    "pressure": (
        "你是一位高强度的压力面试官，连珠追问、质疑回答的细节和动机，模拟真实大厂压力面。"
        "保持专业边界，不羞辱不嘲讽；目的是看候选人在压力下的思路稳定性。"
    ),
}

DISPLAY_INTENT: dict[str, str] = {
    "follow_up": "追问",
    "new_question": "新问题",
    "transition": "换个角度",
    "hint": "提示",
    "clarify": "澄清",
    "reverse_answer": "回答你",
    "finish": "结束",
}

VALID_ACTIONS = tuple(DISPLAY_INTENT.keys())
VALID_PHASES = (
    "self_intro",
    "resume_deep_dive",
    "technical",
    "behavioral",
    "reverse_qa",
)
QUALITY_LEVELS = ("weak", "partial", "good", "strong")

# Hard caps the server enforces regardless of LLM behaviour.
MAX_FOLLOW_UP_DEPTH = 2
MAX_DIRECTOR_RETRIES = 2
SUMMARY_EVERY_N_TURNS = 6

DEFAULT_TURN_BUDGETS = {"min": 6, "target": 10, "max": 14}

# Transition words the validator looks for in spoken_response when
# action == transition.
_TRANSITION_PHRASES = (
    "接下来", "下一个话题", "下一题", "换个角度", "换个话题", "下面",
    "再看一下", "这块先到这里", "我们继续", "再聊聊",
)


def _style_brief(style: str | None) -> str:
    return INTERVIEWER_STYLES.get((style or "professional").strip(), INTERVIEWER_STYLES["professional"])


# ── Cacheable prefix ─────────────────────────────────────────────────────


def build_prefix(resume_context: str, jd_context: str, style: str) -> str:
    """Verbatim-stable prefix that every LLM call in a session starts with.

    Keep this function deterministic w.r.t. its inputs — no timestamps, no
    random whitespace — so DeepSeek prompt cache can hit on the prefix tokens.
    Call once at session start, store the result in mock_interview_state, and reuse.
    """
    resume = (resume_context or "").strip() or "（候选人未提供简历）"
    jd = (jd_context or "").strip() or "（未提供 JD）"
    return (
        "你是资深技术面试官。核心原则：认真听 → 基于材料判断 → "
        "接住对方刚说的话 → 决定追问 / 推进。每次只问一个清晰问题；"
        "不要书面化堆砌；不要一口气问多个。\n"
        "\n═════════ 候选人简历（全文） ═════════\n"
        f"{resume}\n"
        "\n═════════ 目标岗位 JD（全文） ═════════\n"
        f"{jd}\n"
        "\n═════════ 你的人设 ═════════\n"
        f"{_style_brief(style)}\n"
    )


def prefix_hash(prefix: str) -> str:
    return hashlib.sha256(prefix.encode("utf-8")).hexdigest()[:16]


# ── Output schema ────────────────────────────────────────────────────────


@dataclass
class AnswerQuality:
    level: str = "partial"
    reason: str = ""


@dataclass
class StateUpdate:
    covered_topics_add: list[str] = field(default_factory=list)
    weak_topics_add: list[str] = field(default_factory=list)
    strong_topics_add: list[str] = field(default_factory=list)
    phase_should_advance: bool = False


@dataclass
class DirectorOutput:
    action: str
    phase: str
    spoken_response: str
    next_question: str
    topic: str
    answer_quality: AnswerQuality
    state_update: StateUpdate
    should_finish: bool = False


# ── Brief output ─────────────────────────────────────────────────────────


@dataclass
class InterviewBrief:
    interview_plan: dict[str, Any]
    opening_spoken: str
    opening_question: str
    min_turns: int
    target_turns: int
    max_turns: int


# ── JSON parsing helpers ─────────────────────────────────────────────────


def _clean_json(raw_text: str) -> dict[str, Any]:
    raw = (raw_text or "").strip()
    if raw.startswith("```json"):
        raw = raw[7:]
    elif raw.startswith("```"):
        raw = raw[3:]
    if raw.endswith("```"):
        raw = raw[:-3]
    data = json.loads(raw.strip())
    if not isinstance(data, dict):
        raise ValueError("Top-level JSON must be an object")
    return data


def _parse_director_output(raw_text: str) -> DirectorOutput:
    data = _clean_json(raw_text)

    action = str(data.get("action") or "").strip()
    if action not in VALID_ACTIONS:
        raise ValueError(f"action 必须是 {VALID_ACTIONS}，收到 {action!r}")

    phase = str(data.get("phase") or "").strip()
    if phase not in VALID_PHASES:
        raise ValueError(f"phase 必须是 {VALID_PHASES}，收到 {phase!r}")

    aq_raw = data.get("answer_quality") or {}
    if not isinstance(aq_raw, dict):
        raise ValueError("answer_quality 必须是对象")
    aq = AnswerQuality(
        level=str(aq_raw.get("level") or "partial"),
        reason=str(aq_raw.get("reason") or "").strip(),
    )
    if aq.level not in QUALITY_LEVELS:
        aq.level = "partial"

    su_raw = data.get("state_update") or {}
    if not isinstance(su_raw, dict):
        su_raw = {}
    su = StateUpdate(
        covered_topics_add=_str_list(su_raw.get("covered_topics_add")),
        weak_topics_add=_str_list(su_raw.get("weak_topics_add")),
        strong_topics_add=_str_list(su_raw.get("strong_topics_add")),
        phase_should_advance=bool(su_raw.get("phase_should_advance", False)),
    )

    return DirectorOutput(
        action=action,
        phase=phase,
        spoken_response=str(data.get("spoken_response") or "").strip(),
        next_question=str(data.get("next_question") or "").strip(),
        topic=str(data.get("topic") or "").strip(),
        answer_quality=aq,
        state_update=su,
        should_finish=bool(data.get("should_finish", False)),
    )


def _str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(x).strip() for x in value if isinstance(x, (str, int)) and str(x).strip()]


# ── Topic + state_update helpers ─────────────────────────────────────────


def normalize_topic(t: str | None) -> str:
    """Canonical form: lowercase, snake_case, [a-z0-9_一-龥] only, ≤40 chars."""
    s = (t or "").strip().lower().replace(" ", "_").replace("-", "_")
    s = re.sub(r"[^a-z0-9_一-鿿]", "", s)
    return s[:40]


def _similarity(a: str, b: str) -> float:
    """Cheap char-overlap ratio. Good enough to catch redis_cache vs cache_redis."""
    if not a or not b:
        return 0.0
    sa, sb = set(a), set(b)
    inter = sa & sb
    return len(inter) / max(len(sa), len(sb))


def _is_dup(topic: str, against: Iterable[str]) -> bool:
    n = normalize_topic(topic)
    for existing in against:
        e = normalize_topic(existing)
        if not e:
            continue
        if e == n or _similarity(e, n) > 0.7:
            return True
    return False


def apply_state_update(state: dict, update: StateUpdate) -> None:
    """In-place: enforce per-turn caps (≤1 of each), exclusivity (weak↔strong)
    and topic normalization. Mutates state.covered_topics / weak_topics /
    strong_topics. Does NOT trust the LLM for cap enforcement."""
    covered = state.setdefault("covered_topics", [])
    weak = state.setdefault("weak_topics", [])
    strong = state.setdefault("strong_topics", [])

    # Each list: at most one fresh normalized topic per turn, no dupes with
    # existing entries in the SAME list. weak ↔ strong are mutually exclusive
    # (a topic can't be both at the same time — the new entry wins).
    for raw in update.covered_topics_add[:1]:
        n = normalize_topic(raw)
        if n and not _is_dup(n, covered):
            covered.append(n)

    for raw in update.weak_topics_add[:1]:
        n = normalize_topic(raw)
        if not n:
            continue
        # Remove from strong if it's there (exclusivity)
        state["strong_topics"] = [t for t in strong if normalize_topic(t) != n]
        if not _is_dup(n, weak):
            weak.append(n)
        strong = state["strong_topics"]  # refresh local view

    for raw in update.strong_topics_add[:1]:
        n = normalize_topic(raw)
        if not n:
            continue
        state["weak_topics"] = [t for t in weak if normalize_topic(t) != n]
        if not _is_dup(n, strong):
            strong.append(n)


# ── Validators (V1-V6) ──────────────────────────────────────────────────


def _looks_like_reverse_invitation(q: str) -> bool:
    q = (q or "").strip()
    if not q:
        return False
    keywords = ("想问", "想了解", "有什么问题", "什么想问", "想问我的")
    return any(k in q for k in keywords)


def _has_transition_phrase(s: str) -> bool:
    s = (s or "")
    return any(p in s for p in _TRANSITION_PHRASES)


def _allow_finish(state: dict) -> tuple[bool, str | None]:
    turn_count = int(state.get("turn_count", 0))
    if turn_count < int(state.get("min_turns", DEFAULT_TURN_BUDGETS["min"])):
        return False, "未达最低轮次"
    phase_progress = state.get("phase_progress", {}) or {}
    if phase_progress.get("self_intro", 0) == 0:
        return False, "未做自我介绍"
    core = sum(phase_progress.get(p, 0) for p in ("resume_deep_dive", "technical", "behavioral"))
    if core < 5:
        return False, "核心阶段覆盖不足（需 ≥5 题）"
    if state.get("current_phase") == "reverse_qa" and not state.get("reverse_qa_prompted"):
        return False, "反问环节未触发"
    return True, None


def validate_director(result: DirectorOutput, state: dict) -> str | None:
    """Return None when result is acceptable, otherwise a human-readable
    violation message that the LLM should be told about on retry."""

    follow_up_depth = int(state.get("follow_up_depth", 0))
    max_turns = int(state.get("max_turns", DEFAULT_TURN_BUDGETS["max"]))
    turn_count = int(state.get("turn_count", 0))

    # V1 follow_up depth cap
    if result.action == "follow_up" and follow_up_depth >= MAX_FOLLOW_UP_DEPTH:
        return (
            f"本题已追问 {follow_up_depth} 次（上限 {MAX_FOLLOW_UP_DEPTH}）。"
            "必须改成 transition 或 new_question。"
        )

    # V2 first entry into reverse_qa must look like an invitation
    if result.phase == "reverse_qa" and not state.get("reverse_qa_prompted"):
        if result.action != "transition" or not _looks_like_reverse_invitation(result.next_question):
            return (
                "首次进入反问阶段，action 必须为 transition，"
                "next_question 必须邀请候选人提问（如「你有什么想问我的吗？」）。"
            )

    # V3 should_finish server-side review
    if result.should_finish:
        ok, reason = _allow_finish(state)
        if not ok:
            return f"不允许结束面试：{reason}。请继续推进下一题。"

    # V4 max_turns reached but reverse_qa not yet triggered → force transition into it
    if turn_count >= max_turns and not state.get("reverse_qa_prompted"):
        if result.phase != "reverse_qa":
            return (
                f"已达最高轮次 {max_turns}。请用 transition 进入反问阶段，"
                "next_question 邀请候选人提问。"
            )

    # V5 spoken_response must not contain a question mark unless this is clarify
    if result.action != "clarify":
        if "?" in result.spoken_response or "？" in result.spoken_response:
            return (
                "spoken_response 在非 clarify 场景下不允许含问号；问句必须放进 next_question。"
            )

    # V6 transition must contain an explicit transition phrase
    if result.action == "transition":
        if not _has_transition_phrase(result.spoken_response):
            return (
                "transition 的 spoken_response 必须含明显过渡词（接下来 / 换个角度 / 下一个话题 等）。"
            )

    # finish should leave next_question empty; LLM sometimes still fills it.
    # Not strictly invalid but normalize downstream — no retry needed.

    return None


# ── Prompts ──────────────────────────────────────────────────────────────


BRIEF_PROMPT = """{prefix}
请为这场约 25-30 分钟的模拟面试写一份「面试地图」+ 开场白。**不要**输出完整问题列表 —— 只输出策略骨架。

输出严格 JSON：
{{
  "interview_plan": {{
    "interview_goal": "一句话本场考察什么",
    "candidate_focus": ["从简历中值得深挖的方向 2-3 条，点出具体名词"],
    "jd_focus": ["JD 中必须覆盖的硬能力 2-3 条"],
    "phases": [
      {{
        "phase": "self_intro|resume_deep_dive|technical|behavioral|reverse_qa",
        "budget": 1,
        "goal": "这个阶段的目的（一句话）",
        "suggested_topics": ["话题1（具体名词）", "话题2"],
        "difficulty": "warm_up|core|stretch"
      }}
    ]
  }},
  "opening_spoken": "极简口语招呼，≤ 8 字，例如「你好」或「咱们开始吧」",
  "opening_question": "请候选人做自我介绍的一句话，≤ 20 字",
  "min_turns": 6,
  "target_turns": 10,
  "max_turns": 14
}}

注意：
- phases 必须按 self_intro → resume_deep_dive → technical → behavioral → reverse_qa 顺序列全 5 个。
- min/target/max_turns 根据简历复杂度自行决定，但 min<target<max。

# 开场白硬约束（极其重要 —— 第一句话由 opening_question 直接展示给用户，必须干净）

opening_spoken：
- 仅是招呼，最多 8 字
- ✅ 合法（按 interviewer_style 选择匹配语气）：
  · 友好/默认：「你好」「咱们开始吧」「你好，准备好了吗」
  · 专业/严谨：「您好」「我们开始吧」「您好，准备好了吗」
- ❌ 违规：任何提到面试时长、岗位名、考察方向、JD 内容、简历项目的字样

opening_question：
- **必须**是单一、干净的「请你做自我介绍」类引导，最多 20 字
- ✅ 合法：「先简单做个自我介绍吧」「咱们从自我介绍开始」「请先做个自我介绍」「请您先简单介绍一下自己」
- ❌ 违规（绝对禁止）：
  · 提到面试时长（「这场 30 分钟的面试…」）
  · 提到考察方向或 JD 关键词（「我们今天主要看 Python 后端…」）
  · 点名简历里的具体项目 / 公司 / 技术栈
  · 把欢迎语和问题黏在一起（「欢迎参加面试，请介绍一下你的项目经验」）
  · 任何「请详细阐述」「请深入介绍」类书面语 —— 自我介绍阶段就是让候选人放松开口，不是技术拷问
"""


DIRECTOR_PROMPT = """{prefix}
## 本场面试地图
{plan_compact}

## 阶段进度（已问 / 预算）
{phase_progress_text}

## 话题覆盖
覆盖过：{covered}
偏弱：{weak}
偏强：{strong}

## 历史摘要
{history_summary}

## 最近 5 轮 QA
{recent_qa}

## 当前问题（候选人正在回答这一句）
{pending_question}

## 候选人刚才的回答
{user_answer}
{prior_violation_block}
## 你的决策流程

1. 判断回答属哪种：
   A 笼统  B 提到具体名词但没解释  C 给了数字但没基线
   D 答得不错可推进  E 卡壳  F 偏题  G 阶段聊够了

2. 决定 action（必须是这 7 类之一）：
   - follow_up：接住候选人刚说的某个具体词，深挖。必须复述对方刚说的某个名词或短语。
   - new_question：同阶段换主问题。
   - transition：切换到下一阶段；spoken_response 必含过渡词（接下来 / 换个角度 / 这块先到这里）。
   - hint：候选人卡壳时降难度 —— 优先用 hint_scenario（给一个具体场景让对方上手），完全没头绪时用 hint_options（给两个方向让对方二选一）。
   - clarify：候选人答案有歧义时澄清；spoken_response 可含 1 个问号。
   - reverse_answer：在反问阶段（reverse_qa_prompted=true）回答候选人的问题。
   - finish：所有重要的都聊过了 + 反问环节已完成。

3. 硬约束（违反任一你的输出会被服务端拒绝，并要求你重做）：
   - follow_up_depth = {follow_up_depth}，若 ≥ {max_depth} 则禁止 follow_up。
   - 阶段切换 spoken_response 必含明显过渡词。
   - 候选人放弃（说"不知道 / 不会 / 跳过"）→ 用 transition 或 new_question 温和带过，绝不准 follow_up。
   - 首次进入 reverse_qa（reverse_qa_prompted=false）→ action 必须是 transition，next_question 必须邀请提问（"你有什么想问我的吗？"）。
   - 已达 max_turns 但 reverse_qa_prompted=false → 必须 transition 进入 reverse_qa。
   - spoken_response 不含问号（clarify 除外）。问句永远放在 next_question 里。

4. 说出口的话（两段）：
   - spoken_response：1-2 句口语，TTS 朗读流畅。例："嗯，听起来当时挺折腾。"、"好，这块清楚了。"、"明白了。"
   - next_question：单一意图、≤ 40 字、可直接朗读。不要塞多个问号。finish/reverse_answer 时可为空字符串。

5. answer_quality（判断你刚才那一题的回答质量，作为复盘先验）：
   - weak：答非所问 / 完全空泛
   - partial：方向对但浅
   - good：覆盖主要点，有一定深度
   - strong：有 trade-off 思考 + 失败 case + 取舍

6. state_update：每轮至多新增 1 个 covered_topics、1 个 weak_topics、1 个 strong_topics（snake_case 中文/英文短语标签）。

输出严格 JSON：
{{
  "action": "follow_up | new_question | transition | hint | clarify | reverse_answer | finish",
  "phase": "self_intro | resume_deep_dive | technical | behavioral | reverse_qa",
  "spoken_response": "...",
  "next_question": "...",
  "topic": "snake_case 当前话题标签",
  "answer_quality": {{ "level": "weak|partial|good|strong", "reason": "1 句话依据" }},
  "state_update": {{
    "covered_topics_add": [],
    "weak_topics_add": [],
    "strong_topics_add": [],
    "phase_should_advance": false
  }},
  "should_finish": false
}}
"""


SUMMARY_PROMPT = """{prefix}
请把下面这段面试早期对话压缩成不超过 200 字的中文摘要，保留：
- 已经聊过哪些项目 / 话题
- 候选人在哪些点表现较好 / 较弱
- 仍未澄清的疑点

已有摘要（如非空，请基于它继续滚动）：
{previous_summary}

待压缩的对话片段：
{old_history}

只输出摘要文本，不要前后说明。"""


# ── Helper formatters for prompt assembly ───────────────────────────────


def _plan_compact(plan: dict[str, Any] | None) -> str:
    if not plan:
        return "（无）"
    lines: list[str] = []
    goal = plan.get("interview_goal") or ""
    if goal:
        lines.append(f"目标：{goal}")
    cf = plan.get("candidate_focus") or []
    if cf:
        lines.append("简历重点：" + "; ".join(str(x) for x in cf))
    jd = plan.get("jd_focus") or []
    if jd:
        lines.append("JD 重点：" + "; ".join(str(x) for x in jd))
    for ph in plan.get("phases") or []:
        if not isinstance(ph, dict):
            continue
        name = ph.get("phase")
        budget = ph.get("budget")
        topics = ph.get("suggested_topics") or []
        topics_str = ("话题：" + ", ".join(str(t) for t in topics)) if topics else ""
        lines.append(f"  - {name} (budget {budget}) {topics_str}")
    return "\n".join(lines)


def _phase_progress_text(plan: dict[str, Any] | None, progress: dict[str, int] | None) -> str:
    if not plan or not isinstance(plan.get("phases"), list):
        return "（无）"
    progress = progress or {}
    parts: list[str] = []
    for ph in plan["phases"]:
        if not isinstance(ph, dict):
            continue
        name = ph.get("phase")
        budget = ph.get("budget")
        done = progress.get(name, 0)
        parts.append(f"{name}: {done}/{budget}")
    return "  ".join(parts)


def _recent_qa_block(qa_history: list[dict[str, Any]], n: int = 5) -> str:
    if not qa_history:
        return "（首题，无历史）"
    lines: list[str] = []
    for i, entry in enumerate(qa_history[-n:], start=max(1, len(qa_history) - n + 1)):
        q = (entry.get("question") or "")[:300]
        a = (entry.get("answer") or "")[:600]
        ph = entry.get("phase") or ""
        lines.append(f"  [{i}] ({ph}) 问: {q}\n      答: {a}")
    return "\n".join(lines)


def _prior_violation_block(violation: str | None) -> str:
    if not violation:
        return ""
    return (
        "\n## 上一次输出被服务端拒绝\n"
        f"原因：{violation}\n"
        "请严格按规则重新生成。\n"
    )


# ── Public API ──────────────────────────────────────────────────────────


async def generate_brief(
    *,
    resume_context: str,
    jd_context: str,
    interviewer_style: str = "professional",
) -> InterviewBrief:
    """LLM #1 — fired once at session start. Returns the interview map + opening
    line + turn budgets. The prefix is the same one we'll cache for the rest
    of the session, so this call also primes the DeepSeek prompt cache."""
    prefix = build_prefix(resume_context, jd_context, interviewer_style)
    prompt = BRIEF_PROMPT.format(prefix=prefix)
    response = await _mock_llm.acomplete(prompt, response_format={"type": "json_object"})
    try:
        data = _clean_json(str(response.text))
    except (json.JSONDecodeError, ValueError) as exc:
        logger.exception("Brief generation parse failed; using fallback: %s", exc)
        return _fallback_brief()

    plan = data.get("interview_plan") or {}
    plan = _normalize_plan(plan)
    # Defaults respect the same caps advertised to the LLM in the
    # prompt (opening_spoken ≤ 8 字 / opening_question ≤ 20 字), so
    # whether the JSON parses cleanly or we fall back to the defaults
    # the user-visible opener still satisfies the contract.
    opening_spoken = str(data.get("opening_spoken") or "你好").strip()
    opening_question = str(data.get("opening_question") or "先简单做个自我介绍吧").strip()

    min_turns = _int_in_range(data.get("min_turns"), 3, 20, default=DEFAULT_TURN_BUDGETS["min"])
    target_turns = _int_in_range(data.get("target_turns"), min_turns, 30, default=DEFAULT_TURN_BUDGETS["target"])
    max_turns = _int_in_range(data.get("max_turns"), target_turns, 40, default=DEFAULT_TURN_BUDGETS["max"])

    return InterviewBrief(
        interview_plan=plan,
        opening_spoken=opening_spoken,
        opening_question=opening_question,
        min_turns=min_turns,
        target_turns=target_turns,
        max_turns=max_turns,
    )


async def run_director(
    state: dict,
    user_answer: str,
) -> DirectorOutput:
    """LLM #2 — fired every turn. Retries up to MAX_DIRECTOR_RETRIES times
    with violation feedback if the server-side validator rejects the output.
    Raises ``DirectorRetryExhausted`` when retries are exhausted."""
    prefix = state.get("cacheable_prefix") or build_prefix(
        state.get("resume_context", ""),
        state.get("jd_context", ""),
        state.get("interviewer_style", "professional"),
    )

    plan = state.get("interview_plan") or {}
    plan_compact = _plan_compact(plan)
    progress_text = _phase_progress_text(plan, state.get("phase_progress"))
    recent_qa = _recent_qa_block(state.get("qa_history") or [])
    follow_up_depth = int(state.get("follow_up_depth", 0))

    violation: str | None = None
    last_result: DirectorOutput | None = None
    for attempt in range(MAX_DIRECTOR_RETRIES + 1):
        prompt = DIRECTOR_PROMPT.format(
            prefix=prefix,
            plan_compact=plan_compact,
            phase_progress_text=progress_text,
            covered=", ".join(state.get("covered_topics") or []) or "（无）",
            weak=", ".join(state.get("weak_topics") or []) or "（无）",
            strong=", ".join(state.get("strong_topics") or []) or "（无）",
            history_summary=(state.get("qa_history_summary") or "（无）"),
            recent_qa=recent_qa,
            pending_question=state.get("pending_question") or "（无）",
            user_answer=(user_answer or "").strip() or "（候选人沉默）",
            follow_up_depth=follow_up_depth,
            max_depth=MAX_FOLLOW_UP_DEPTH,
            prior_violation_block=_prior_violation_block(violation),
        )

        try:
            response = await _mock_llm.acomplete(prompt, response_format={"type": "json_object"})
            result = _parse_director_output(str(response.text))
        except (json.JSONDecodeError, ValueError) as exc:
            violation = f"上一次输出无法解析为合规 JSON：{exc}"
            logger.warning("Director attempt %d parse failed: %s", attempt + 1, exc)
            continue

        last_result = result
        violation = validate_director(result, state)
        if violation is None:
            logger.info(
                "Director ok attempt=%d action=%s phase=%s topic=%s quality=%s",
                attempt + 1, result.action, result.phase, result.topic, result.answer_quality.level,
            )
            return result
        logger.info("Director attempt %d rejected: %s", attempt + 1, violation)

    raise DirectorRetryExhausted(
        last_violation=violation or "未知",
        last_result=last_result,
    )


async def summarize_history(state: dict) -> str:
    """LLM #3 — every SUMMARY_EVERY_N_TURNS turns, condense the older qa_history
    into a short scrolling summary. The most recent 5 turns are NOT included
    here — those keep flowing into the director prompt verbatim."""
    qa_history = state.get("qa_history") or []
    if len(qa_history) <= 5:
        return state.get("qa_history_summary") or ""

    older = qa_history[:-5]
    if not older:
        return state.get("qa_history_summary") or ""

    prefix = state.get("cacheable_prefix") or build_prefix(
        state.get("resume_context", ""),
        state.get("jd_context", ""),
        state.get("interviewer_style", "professional"),
    )
    old_history_text = "\n".join(
        f"问: {(e.get('question') or '')[:200]}\n答: {(e.get('answer') or '')[:300]}"
        for e in older
    )
    prompt = SUMMARY_PROMPT.format(
        prefix=prefix,
        previous_summary=state.get("qa_history_summary") or "（首次摘要）",
        old_history=old_history_text,
    )
    try:
        response = await _mock_llm.acomplete(prompt)
        summary = str(response.text or "").strip()
        return summary[:600]  # hard cap
    except Exception as exc:  # noqa: BLE001
        logger.warning("Summary generation failed (non-fatal): %s", exc)
        return state.get("qa_history_summary") or ""


# ── Exceptions ───────────────────────────────────────────────────────────


class DirectorRetryExhausted(RuntimeError):
    """Raised when run_director has tried MAX_DIRECTOR_RETRIES+1 times and the
    output still does not pass the validator. The API layer maps this to a 503
    so the client can offer a retry button — the server explicitly refuses to
    invent a fallback question per v6 design principles."""

    def __init__(self, *, last_violation: str, last_result: DirectorOutput | None):
        super().__init__(f"Director retry exhausted: {last_violation}")
        self.last_violation = last_violation
        self.last_result = last_result


# ── Internals ────────────────────────────────────────────────────────────


def _int_in_range(value: Any, lo: int, hi: int, *, default: int) -> int:
    try:
        v = int(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, v))


def _normalize_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """Light normalization; downstream tolerant of missing fields."""
    out: dict[str, Any] = {
        "interview_goal": str(plan.get("interview_goal") or "").strip(),
        "candidate_focus": _str_list(plan.get("candidate_focus")),
        "jd_focus": _str_list(plan.get("jd_focus")),
        "phases": [],
    }
    phases = plan.get("phases")
    if not isinstance(phases, list) or not phases:
        return _fallback_brief().interview_plan

    seen = set()
    for ph in phases:
        if not isinstance(ph, dict):
            continue
        name = str(ph.get("phase") or "").strip()
        if name not in VALID_PHASES or name in seen:
            continue
        seen.add(name)
        out["phases"].append({
            "phase": name,
            "budget": _int_in_range(ph.get("budget"), 1, 8, default=1),
            "goal": str(ph.get("goal") or "").strip(),
            "suggested_topics": _str_list(ph.get("suggested_topics")),
            "difficulty": str(ph.get("difficulty") or "core"),
        })

    # If LLM dropped phases, fill in missing ones with safe defaults so the
    # downstream state machine can still advance through the canonical
    # 5-phase order.
    missing = [p for p in VALID_PHASES if p not in seen]
    for name in missing:
        out["phases"].append({
            "phase": name,
            "budget": 1 if name in ("self_intro", "reverse_qa") else 2,
            "goal": "",
            "suggested_topics": [],
            "difficulty": "warm_up" if name in ("self_intro", "reverse_qa") else "core",
        })
    # Reorder to canonical sequence
    order_idx = {p: i for i, p in enumerate(VALID_PHASES)}
    out["phases"].sort(key=lambda p: order_idx[p["phase"]])
    return out


def _fallback_brief() -> InterviewBrief:
    """Used when LLM #1 returns garbage. Safe baseline so the user still gets
    a working interview — but should be rare."""
    plan = {
        "interview_goal": "考察候选人的技术能力和项目经验",
        "candidate_focus": [],
        "jd_focus": [],
        "phases": [
            {"phase": "self_intro", "budget": 1, "goal": "了解候选人背景", "suggested_topics": [], "difficulty": "warm_up"},
            {"phase": "resume_deep_dive", "budget": 3, "goal": "项目深挖", "suggested_topics": [], "difficulty": "core"},
            {"phase": "technical", "budget": 3, "goal": "技术基础", "suggested_topics": [], "difficulty": "core"},
            {"phase": "behavioral", "budget": 2, "goal": "协作和抗压", "suggested_topics": [], "difficulty": "core"},
            {"phase": "reverse_qa", "budget": 1, "goal": "回答候选人提问", "suggested_topics": [], "difficulty": "warm_up"},
        ],
    }
    return InterviewBrief(
        interview_plan=plan,
        # Both strings stay within the BRIEF_PROMPT caps (8 / 20 字)
        # so the fallback is byte-for-byte compatible with the
        # contract the LLM was told to follow.
        opening_spoken="你好",
        opening_question="先简单做个自我介绍吧",
        min_turns=6,
        target_turns=10,
        max_turns=14,
    )


# ── Singleton-style facade (preserves existing import paths) ────────────


class MockInterviewService:
    """Thin facade so callers can keep using `mock_interview_service.X`."""

    INTERVIEWER_STYLES = INTERVIEWER_STYLES
    DISPLAY_INTENT = DISPLAY_INTENT
    MAX_FOLLOW_UP_DEPTH = MAX_FOLLOW_UP_DEPTH
    MAX_DIRECTOR_RETRIES = MAX_DIRECTOR_RETRIES
    SUMMARY_EVERY_N_TURNS = SUMMARY_EVERY_N_TURNS
    DirectorRetryExhausted = DirectorRetryExhausted

    @staticmethod
    def build_prefix(resume_context: str, jd_context: str, style: str) -> str:
        return build_prefix(resume_context, jd_context, style)

    @staticmethod
    def prefix_hash(prefix: str) -> str:
        return prefix_hash(prefix)

    @staticmethod
    async def generate_brief(
        resume_context: str = "",
        *,
        jd_context: str = "",
        interviewer_style: str = "professional",
    ) -> InterviewBrief:
        return await generate_brief(
            resume_context=resume_context,
            jd_context=jd_context,
            interviewer_style=interviewer_style,
        )

    @staticmethod
    async def run_director(state: dict, user_answer: str) -> DirectorOutput:
        return await run_director(state, user_answer)

    @staticmethod
    async def summarize_history(state: dict) -> str:
        return await summarize_history(state)

    @staticmethod
    def apply_state_update(state: dict, update: StateUpdate) -> None:
        apply_state_update(state, update)

    @staticmethod
    def normalize_topic(t: str | None) -> str:
        return normalize_topic(t)


mock_interview_service = MockInterviewService()


__all__ = [
    "InterviewBrief",
    "DirectorOutput",
    "AnswerQuality",
    "StateUpdate",
    "DirectorRetryExhausted",
    "DISPLAY_INTENT",
    "MAX_FOLLOW_UP_DEPTH",
    "MAX_DIRECTOR_RETRIES",
    "SUMMARY_EVERY_N_TURNS",
    "DEFAULT_TURN_BUDGETS",
    "build_prefix",
    "prefix_hash",
    "generate_brief",
    "run_director",
    "summarize_history",
    "apply_state_update",
    "normalize_topic",
    "validate_director",
    "mock_interview_service",
]
