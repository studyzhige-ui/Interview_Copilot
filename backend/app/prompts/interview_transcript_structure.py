"""Prompts for ID-only interview transcript structure projection."""

SPEAKER_ROLE_PROMPT = """\
你在标注一次一对一求职面试。输入是按声学切分的原始 ASR 轮次。
只判断稳定 speaker_id 对应的角色，不要改写或概括内容。

必须返回 JSON：
{{"speaker_roles":[{{"speaker_id":"SPEAKER_00","role":"interviewer|candidate|unknown","confidence":0.0}}]}}

约束：
- 必须且只能为 REQUIRED_SPEAKERS 中每个 speaker_id 返回一项；
- 一对一面试必须恰有一个 interviewer 和一个 candidate；
- 无法可靠判断时返回 unknown，禁止猜测；
- 不返回任何新文本。

REQUIRED_SPEAKERS：
{required_speakers}

轮次：
{turns}
"""


UTTERANCE_STRUCTURE_PROMPT = """\
你在为面试录音标注对话行为。输入词的正文不可修改，输出只能引用词 ID。
speaker 角色已经确定。请在每个 WINDOW 内把词划分成有意义的 utterance。

必须返回 JSON：
{{"utterances":[{{
  "start_word_id":"w000001",
  "end_word_id":"w000010",
  "role":null,
  "dialogue_act":"question|answer|acknowledgement|context|interruption|closing|noise",
  "confidence":0.0,
  "punctuation":[{{"after_word_id":"w000010","mark":"，|。|？|！|：|；"}}]
}}]}}

约束：
- 只使用输入里的词 ID；范围不得跨 WINDOW、不得重叠或倒序；
- 一个 utterance 不得跨越已知 speaker 边界；短暂停顿可以合并，但问题和
  对方的回答必须拆成两个 utterance；
- 不返回问题/答案正文，不概括、不改写、不删除词；
- speaker 已知时 role 必须为 null；speaker=UNKNOWN 时必须按上下文返回
  interviewer 或 candidate；确属杂音且无法归属时 role 可以为 null；
- 面试官的“嗯、好的、明白”通常是 acknowledgement，不是新问题；
- 候选人的长回答即使包含停顿或被短暂插话，也仍是 answer/context；
- 反向提问阶段，面试官对公司的长篇解释属于 context；其中用于说明观点的
  反问句不是向候选人索取回答，不得标成新的 question；
- 结尾寒暄是 closing；ASR 碎片或纯杂音是 noise；
- 标点只是插入位置，不得替换原词。

角色：
{roles}

WINDOW：
{window}
"""


QA_EPISODE_PROMPT = """\
你在给已经验证的面试 utterance 标注问答 episode。正文由系统持有，输出只能引用 utterance_id。
每一个 role=interviewer 且 dialogue_act=question 的 utterance 必须恰好出现在一个 episode 中。

必须返回 JSON：
{{"episodes":[{{
  "question_utterance_ids":["u0001"],
  "phase":"opening|resume|project|technical|behavioral|career|reverse_qa|closing|general",
  "is_follow_up":false,
  "parent_episode_index":null,
  "confidence":0.0
}}]}}

约束：
- 只能使用输入里的 interviewer/question utterance_id；
- 同一句被声学停顿拆开的连续问题可以合为一个 episode；两个独立问题必须分开；
- 不返回问题或回答正文；
- 候选人反问属于 reverse_qa；面试官的解释不能成为候选人答案；
- parent_episode_index 是本输出中 1-based 的前序 episode，不能指向自己或未来。

utterances：
{utterances}
"""


__all__ = ["QA_EPISODE_PROMPT", "SPEAKER_ROLE_PROMPT", "UTTERANCE_STRUCTURE_PROMPT"]
