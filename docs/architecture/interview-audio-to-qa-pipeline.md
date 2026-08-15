# 面试录音到可审计 QA 的证据流水线

状态：已确认设计，替代旧的“长文本分块后让模型生成 QA 文本”实现。

## 1. 目标与非目标

上传录音的复盘链必须同时满足三件事：

1. 尽可能完整保留候选人的原始回答；
2. 把 ASR 的停顿词、环境噪声、立即重复和说话人交叉整理成可读问答；
3. 任何展示内容都能回到真实录音对应的词级证据，不允许模型悄悄改写。

本流水线不把“润色答案”混进原始 QA。改进建议和示范答案仍属于后续分析结果，必须与来源回答分栏显示。

## 2. 权威依据

- WhisperX 使用 VAD、强制对齐和词级时间戳处理长音频，说明 ASR 文本和词级对齐应当是两个明确步骤，而不是只保存一段 Markdown。
- pyannote Community-1 同时提供普通 diarization 与 exclusive diarization。普通轨保留重叠语音事实；exclusive 轨为每一时刻选择一个主要说话人，适合与转写词时间戳对齐。
- meeting recognition 研究表明说话人变化可能发生在句中，不能把整段 ASR segment 的多数说话人直接赋给每个词。
- MRDA 等会议语料将 dialogue act 与 adjacency pair 分开标注。因此“这句话是什么行为”和“它属于哪个问答”必须是两个层次。
- ASR 标点恢复、口语不流利识别和正文编辑是下游变换。变换不能覆盖原始识别证据。

权威实现参考：WhisperX、pyannote.audio Community-1、NVIDIA NeMo diarization、ICSI MRDA。具体链接记录在本文末尾。

## 3. 单一事实所有权

```text
FileAsset(audio)
  -> InterviewTranscript.evidence_json       # 不可变词级证据
  -> InterviewTranscript.structure_json      # 可重算结构投影
  -> InterviewQA.source_provenance_json       # 冻结的 QA 证据范围
  -> InterviewQA.question / answer            # 由程序从证据渲染
  -> scoring / synthesis / AbilitySignal      # 下游分析，不反写来源
```

- `InterviewTranscript` 是录音转写的唯一 owner。
- `InterviewQA` 只保存该 transcript 的确定性投影和精确 provenance。
- LLM 不拥有问题或答案正文。
- `segments_json` 旧字符串格式退出生产读取；升级后的上传录音必须存在 v2 evidence。
- Mock Interview 已经有结构化 ConversationMessage，不经过音频 evidence 流水线。

## 4. 冻结不变量

1. ASR 词一旦写入 evidence，不得由结构化或分析阶段修改、删除或替换。
2. 每个词有稳定 `word_id`、时间区间、ASR 置信度和说话人归属证据。
3. 普通 diarization 保留重叠；exclusive diarization 只用于确定主说话人，不覆盖重叠事实。
4. 结构模型只能返回已存在的 ID、枚举和置信度，不能返回问题或答案文本。
5. QA 正文只能由服务端按 `word_id` 拼接；任何隐藏词都记录 `word_id + reason`。
6. 允许的 display edit 只有：插入标点、隐藏明确噪声/填充词、隐藏紧邻的完全重复口吃。禁止同义改写、概括和重排。
7. 面试官的短确认、追问插话不能截断候选人的长回答；下一个真实问题或会话终止才关闭回答窗口。
8. 候选人的实质性词覆盖率必须被计算。未进入 QA 的内容要么归类为非回答行为并可审计，要么使结果进入 `needs_review`，不能静默成功。
9. 说话人角色不确定、词级对齐缺失、结构 ID 非法或覆盖率不足时，分析报告不得继续生成。
10. 重新结构化可以生成新 projection revision，但不能改变 evidence revision。

## 5. Stage A：音频标准化

输入是 owner 已验证的 `FileAsset`。运行时生成临时 WAV：单声道、16 kHz、float/PCM 规范化；不覆盖原文件。记录：

- 原文件 identity/version；
- 音频 SHA-256、时长、采样率和声道数；
- ASR、alignment、diarization 模型及版本；
- pipeline schema version。

解码失败、空音频、时长越界为 typed failure。

## 6. Stage B：词级 ASR 与强制对齐

本地路径使用 WhisperX：

1. VAD 切分语音区域；
2. ASR 生成词序列；
3. language-specific align model 生成词级 `start/end`；
4. 无法对齐的 token 保留并标记 `alignment_status=missing`，不得凭空制造时间。

生产 QA 要求实质性词具备可用时间范围。仅有段级文本的旧 transcript 不能重新提取 QA，用户必须选择“从录音重新转写”。

## 7. Stage C：说话人分离与重叠语音

面试默认以两位说话人为约束运行 Community-1：

- regular diarization：保留重叠区间；
- exclusive diarization：为转写对齐提供单一主说话人；
- 每个词按时间重叠面积分配 exclusive speaker；
- 同时计算该词与 regular tracks 的重叠比例和 `overlap=true/false`；
- 没有足够重叠时使用 `speaker_id=null`，而不是继承上一句。

角色映射是独立步骤。模型依据有界的 acoustic turns 判定 `interviewer/candidate/unknown`，并只返回 speaker ID。若两者无法可靠区分则进入人工确认，不继续生成报告。

## 8. Canonical Evidence JSON v2

```json
{
  "schema_version": 2,
  "audio": {
    "file_asset_id": "...",
    "file_asset_version": "...",
    "sha256": "...",
    "duration_seconds": 123.4
  },
  "models": {
    "asr": "...",
    "alignment": "...",
    "diarization": "pyannote/speaker-diarization-community-1"
  },
  "words": [
    {
      "word_id": "w000001",
      "text": "您好",
      "start": 1.02,
      "end": 1.31,
      "asr_confidence": 0.94,
      "alignment_status": "aligned",
      "speaker_id": "SPEAKER_00",
      "speaker_confidence": 0.91,
      "overlap": false
    }
  ],
  "diarization": {
    "regular": [{"start": 1.0, "end": 1.4, "speaker_id": "SPEAKER_00"}],
    "exclusive": [{"start": 1.0, "end": 1.4, "speaker_id": "SPEAKER_00"}]
  },
  "acoustic_turns": [
    {
      "turn_id": "t0001",
      "speaker_id": "SPEAKER_00",
      "start_word_id": "w000001",
      "end_word_id": "w000020"
    }
  ]
}
```

Evidence 在写入前执行完整校验：ID 唯一、词序单调、时间不倒退、turn 范围连续且同 speaker、所有引用存在。

## 9. Stage D：对话结构投影

结构模型接收 acoustic turn、词 ID 和原词，但输出严格 JSON：

```json
{
  "speaker_roles": [
    {"speaker_id": "SPEAKER_00", "role": "interviewer", "confidence": 0.97}
  ],
  "utterances": [
    {
      "utterance_id": "u0001",
      "speaker_id": "SPEAKER_00",
      "start_word_id": "w000001",
      "end_word_id": "w000020",
      "dialogue_act": "question",
      "confidence": 0.95,
      "punctuation": [{"after_word_id": "w000020", "mark": "？"}],
      "hidden_words": [{"word_id": "w000002", "reason": "filled_pause"}]
    }
  ]
}
```

允许的 `dialogue_act`：`question | answer | acknowledgement | context | interruption | closing | noise`。

服务端拒绝以下输出：不存在的 ID、跨 speaker 范围、重叠/倒序 utterance、非法标点、隐藏实质性词、超过原 acoustic turn 边界。未覆盖词会自动形成 `context/unknown` utterance，因此模型不能让词消失。

## 10. Stage E：确定性 QA episode

模型最多只标记问题 utterance 的关系：

```json
{
  "episodes": [
    {
      "question_utterance_ids": ["u0003", "u0004"],
      "phase": "technical",
      "is_follow_up": true,
      "parent_episode_index": 1,
      "confidence": 0.92
    }
  ]
}
```

答案范围由程序生成：

1. 从问题结束后开始；
2. 收集 candidate 的 `answer/context` utterance；
3. interviewer 的 acknowledgement/interruption 作为交叉对话保留在 provenance，但不截断回答；
4. 遇到下一个有效 question 或 closing 结束；
5. 没有候选回答的提问不生成已回答 QA，可作为 `unanswered` 结构项展示。

问题和回答都从 evidence 重新渲染，绝不使用模型返回正文。

## 11. Display cleanup

原始 transcript 与整理后的 QA 同时可读：

- 原始转写：按 acoustic turns 展示全部原词；
- 整理 QA：隐藏审计允许的非语义 token，插入标点和段落；
- 改进回答：分析层单独展示，不得标成原话。

默认允许隐藏：`嗯/呃/额/啊` 等孤立填充词、显式 `[noise]`、相邻且内容完全相同的口吃 token。诸如“然后”“就是”“我觉得”可能承载语义，不得仅凭词表删除。

## 12. 覆盖率与完成门

保存以下指标：

- `aligned_word_ratio`；
- `known_speaker_word_ratio`；
- `role_resolved_substantive_word_ratio`：声学轨缺口可由模型只引用词 ID
  做保守角色恢复；原始 `speaker_id=null` 保持不变，来源标为
  `semantic_recovery`，不得把语义判断伪装成声学事实；
- `candidate_substantive_word_coverage`；
- `question_word_coverage`；
- `hidden_word_ratio`；
- `overlap_word_ratio`；
- `low_confidence_episode_count`。

默认完成门：候选人实质性词覆盖率不低于 95%，隐藏实质性词为 0，所有 QA provenance 可回读。低于门槛时状态为 `needs_review`，报告和 AbilitySignal 不得标记完整生成。

## 13. 持久层

`interview_transcripts` 新增：

- `evidence_schema_version`；
- `evidence_json` JSONB；
- `structure_schema_version`；
- `structure_json` JSONB；
- `quality_json` JSONB。

`interview_qa` 新增：

- `source_transcript_id` FK；
- `source_provenance_json` JSONB，其中保存 question/answer word IDs、交叉 utterance、隐藏词、标点和 projection revision。

旧 `segments_json` 不再被新运行时写入或读取。迁移保留旧列仅用于历史审计；后续数据保留期结束后再单独物理删除，避免部署升级直接丢历史。

## 14. 失败与恢复

| code | 语义 | 恢复 |
| --- | --- | --- |
| `transcript_evidence_required` | 只有旧文本，没有词级证据 | 从原录音重新转写 |
| `word_alignment_incomplete` | 实质性词无法对齐 | 重试 ASR/align 或人工复核 |
| `speaker_roles_ambiguous` | 无法可靠区分面试官和候选人 | 用户确认角色 |
| `structure_projection_invalid` | 模型返回非法 ID/范围 | 同 evidence 重试结构投影 |
| `qa_coverage_insufficient` | 回答覆盖不足 | 人工复核结构，不生成完整报告 |
| `audio_overlap_requires_review` | 关键问题位于严重重叠区 | 展示音频窗口并人工确认 |

重试分层执行：ASR 失败才重做 evidence；结构失败只重做 structure；评分失败只重做分析。任何后层重试都不修改前层 owner。

## 15. 替换与删除清单

实现时必须一次性完成：

1. 删除 analysis service 中旧的文本分块、speaker 行正则、关键词角色投票、问题结尾启发式、chunk overlap 去重和二次配对实现；
2. 删除旧 QA extraction/pairing prompts；
3. 上传录音 orchestrator 只调用新 evidence/structure/QA projection services；
4. 文档音频摄取仍可使用返回纯文本的通用 transcription API，两条路径不混用；
5. 旧 transcript 无 v2 evidence 时 fail closed，不偷偷回退旧 extractor；
6. 删除只服务旧 extractor 的测试，新增 evidence、validator、coverage、重叠语音、长回答不中断和真实录音回归测试。

## 16. 验收场景

- 候选人连续回答数分钟，中间有面试官“嗯/好的”插话：回答保持完整；
- 面试官连续追问两个独立技术问题：形成两个 QA，不合并；
- 候选人反问、面试官解释：不把面试官解释写入候选人答案；
- 两人重叠讲话：regular track 保留 overlap，exclusive track 用于主 speaker，低置信度标记复核；
- 结尾寒暄和“服务”等 ASR 碎片：不伪造成问题；
- 任意结构模型尝试返回改写正文：schema 拒绝；
- 展示答案逐词来自 evidence，隐藏项可展开审计；
- APUS 真实录音中项目动机、workflow 失败和架构取舍分别成题，候选人长回答字符覆盖达到门槛。

## 17. 参考

- WhisperX paper: https://arxiv.org/abs/2303.00747
- WhisperX repository: https://github.com/m-bain/whisperX
- pyannote Community-1: https://huggingface.co/pyannote-community/speaker-diarization-community-1
- pyannote diarization pipeline: https://github.com/pyannote/pyannote-audio/blob/main/src/pyannote/audio/pipelines/speaker_diarization.py
- NVIDIA NeMo speaker diarization: https://docs.nvidia.com/nemo-framework/user-guide/24.12/nemotoolkit/asr/speaker_diarization/intro.html
- Word-level speaker segmentation: https://arxiv.org/abs/2309.16482
- ICSI MRDA corpus: https://aclanthology.org/W/W04/W04-2319.pdf
- Disfluency unediting: https://aclanthology.org/N15-1161.pdf
- Punctuation restoration: https://aclanthology.org/2021.wnut-1.19/
