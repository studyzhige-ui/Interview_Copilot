// All shapes mirror backend source-of-truth. See:
//   backend/app/api/interview.py
//   backend/app/api/chat/sessions.py + mock_interview.py + streaming.py
//   backend/app/api/rag.py
//   backend/app/api/model_runtime.py
// Do NOT introduce fields the backend does not return.

// status values written by backend (lower-case in v2 schema)
export type InterviewRecordStatus =
  | 'pending'
  | 'transcribing'
  | 'extracting'
  | 'analyzing'
  | 'completed'
  | 'failed';

export interface InterviewRecordListItem {
  id: string;
  // backend writes 'upload' | 'mock'; frontend may also synthesize 'draft' for
  // local-only entries that haven't been persisted yet.
  source: 'upload' | 'mock' | 'draft';
  title: string;
  tag?: string | null;
  status: InterviewRecordStatus | string;
  created_at: string;
}

export interface InterviewQA {
  id: string;
  order_idx: number;
  phase: string;
  phase_label?: string | null;
  question: string;
  answer: string;
  question_summary?: string | null;
  is_follow_up: boolean;
  follow_up_depth: number;
  grounding_refs: string[];
  score?: number | null;
  critique?: string | null;
  improved_answer?: string | null;
  key_points: string[];
  answer_input_mode: 'text' | 'voice' | 'voice_transcribed';
  question_audio_url?: string | null;
  answer_audio_url?: string | null;
  source_segment_start?: number | null;
  source_segment_end?: number | null;
  analyzed_at?: string | null;
}

export interface InterviewAnalysis {
  schema_version?: number;
  overall?: {
    score?: number;
    grade?: string;
    summary?: string;
    feedback?: string;          // legacy alias retained by backend renderer
    verdict?: string;
    strengths?: string[];
    weaknesses?: string[];
    improvement_plan?: Array<string | { area?: string; actions?: string[]; resources?: string[] }>;
  };
  phase_summary?: Record<string, { score?: number; feedback?: string }>;
  meta?: { model?: string; analyzed_at?: string; qa_count?: number; duration_sec?: number };
}

export interface InterviewRecordDetail extends InterviewRecordListItem {
  analyzed_qa_count: number;
  category: string | null;
  audio_file_asset_id: string | null;
  resume_id: string | null;
  resume_file_asset_id: string | null;
  resume_source: string | null;
  jd_file_asset_id: string | null;
  transcript: string | null;
  transcript_segments: unknown;
  interview_plan: unknown;
  analysis: InterviewAnalysis | null;
  qa: InterviewQA[];
  error_message: string | null;
  updated_at: string;
  completed_at: string | null;
}

export interface ChatSessionListItem {
  session_id: string;
  title: string;
  session_type: string;
  state_summary: string;
  turn_count: number;
  updated_at: string;
}

export interface ChatSessionCreateResp {
  session_id: string;
  title: string;
  session_type: string;
}

/**
 * Anthropic-style content block. Mirrors the persisted shape in
 * ``chat_messages.content_blocks_json`` (backend Stage-G refactor).
 *
 * Both L1 chat turns and L2 agent turns now persist this structure:
 *   - L1 chat persists a single ``text`` block per assistant turn.
 *   - L2 agent persists an interleaved chain like
 *     ``[text, tool_use, tool_result, text, tool_use, tool_result, ...]``
 *     so a folded-card replay UI can reconstruct the ReAct loop.
 *
 * The backend ALWAYS returns ``blocks`` from ``/chat/transcript`` —
 * legacy rows with no JSON column are synthesised into a single text
 * block at read-time (chat_history_service._message_to_dict).
 */
export type ContentBlock =
  | TextBlock
  | ToolUseBlock
  | ToolResultBlock;

export interface TextBlock {
  type: 'text';
  text: string;
}

export interface ToolUseBlock {
  type: 'tool_use';
  /** Tool call id assigned by the LLM (empty when synthesised during
   *  live streaming, since the SSE ``tool_start`` event doesn't carry it). */
  id: string;
  name: string;
  /** Parsed JSON args. Free-form per tool — render as inspectable JSON. */
  input: Record<string, unknown>;
}

export interface ToolResultBlock {
  type: 'tool_result';
  /** Matches a preceding ``ToolUseBlock.id``. Empty during streaming. */
  tool_use_id: string;
  is_error: boolean;
  latency_ms: number;
  /** Always-visible folded label, e.g. "topic_count=8". */
  summary: string;
  /** Full LLM-visible result text — may be a ``<persisted-output ...>``
   *  pointer string for results too large to inline. Expanded on demand. */
  content: string;
}

export interface ChatMessageItem {
  seq: number;
  role: string;
  /** Flat-text fallback. For agent turns this is the LAST text block
   *  joined; ``blocks`` is the source of truth when present. */
  content: string;
  /** Anthropic-style content blocks. Always populated by
   *  ``/chat/transcript``; legacy ``/chat/history`` omits this. */
  blocks?: ContentBlock[];
  /** Planner's rewritten query for the turn — agent-mode only. */
  rewritten_query?: string | null;
  created_at: string | null;
}

export interface ChatTranscriptResp {
  status: 'success';
  session_id: string;
  session_type: string;
  turn_count: number;
  compaction_cursor: number;
  /** Mock-interview runtime state; ``{}`` for general / debrief sessions. */
  mock_interview_state: Record<string, unknown>;
  messages: ChatMessageItem[];
  total_messages: number;
}

export interface MockPlanPhase {
  phase_id: string;
  phase_name: string;
  question_count: number;
}

export interface MockQuestion {
  // ``done`` is set on EVERY return path (start, /question both
  // branches) so it's required. Everything else is gated by the
  // ``done`` flag: when ``done === true`` the backend returns just
  // ``{done, message}``; when ``done === false`` all the live-question
  // fields are present. Callers should branch on ``done`` first (see
  // ``MockPage.resumeInProgress``) — TypeScript would let us model
  // this as a discriminated union, but the existing
  // ``q.done ? ... : ...`` consumer pattern works fine with
  // optional fields and avoids the union-narrowing boilerplate.
  done: boolean;
  /** Set when ``done === true`` — the human-readable "interview
   *  finished" message. Empty / absent otherwise. */
  message?: string;
  // Live-question fields — all present when ``done === false``,
  // absent when ``done === true``.
  question?: string;
  phase_id?: string;
  phase_name?: string;
  question_idx?: number;
  total_questions_in_phase?: number;
  // v6 director attaches the spoken pre-amble for the upcoming
  // question so the TTS layer can speak it alongside the question.
  spoken_response?: string;
}

export interface MockStartResp {
  status: string;
  plan_phases: MockPlanPhase[];
  current_question: MockQuestion;
}

export type MockDirectorAction =
  | 'follow_up'
  | 'new_question'
  | 'transition'
  | 'hint'
  | 'clarify'
  | 'reverse_answer'
  | 'finish';

export interface MockAnswerResp {
  // Concatenated spoken_response + next_question for the TTS layer and
  // any existing single-bubble UI. New code should prefer the split
  // fields below.
  interviewer_response: string;
  // v6 Runtime Director output. The backend emits all four
  // unconditionally on every successful answer turn (see
  // ``mock_interview.py`` answer endpoint). Pre-fix the type lied
  // about this with ``?`` markers; tightening so callers don't have
  // to optional-chain through known-present fields.
  spoken_response: string;
  next_question: string;
  action: MockDirectorAction;
  display_intent: string;
  is_finished: boolean;
  phase_progress: {
    current_phase: string;
    // v6 renamed: turn_count + max_turns + follow_up_depth. Old keys
    // (question_idx / total_answered) are gone — see Mock UI for the
    // new progress chip. The backend writes all three on every turn,
    // so they're required here.
    turn_count: number;
    max_turns: number;
    follow_up_depth: number;
  };
}

export interface MockFinishResp {
  status: 'analyzing';
  record_id: string;
  debrief_session_id: string;
  task_id: string;
}

export interface KnowledgeDoc {
  id: string;
  upload_id: string;
  title: string;
  category: string;
  source_kind: string;
  status: string;
  task_id: string | null;
  chunk_count: number | null;
  content_type: string | null;
  size_bytes: number | null;
  error_message: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface KnowledgeCategory {
  category: string;
  count: number;
}

export interface ModelProfile {
  id: string;
  provider: string;
  display_name: string;
  model: string;
  api_base: string;
  api_key_env: string;
  supports_function_calling: boolean;
  description: string;
  context_window: number;
  max_output_tokens: number;
  ready: boolean;
  selected_for: string[];
  /** True when the entry came from a vendor /v1/models call rather than the curated registry. */
  auto_discovered?: boolean;
}

export type ModelRole = 'primary' | 'fast' | 'agent' | 'mock_interview';

export interface ModelRuntime {
  selection: Record<ModelRole, string>;
  resolved: Record<
    ModelRole,
    { profile_id: string; provider: string; model: string; display_name: string }
  >;
}

export interface AnalyzeDispatchResp {
  status: 'processing';
  message: string;
  record_id: string;
  task_id: string;
}

// ── v3 memory ──────────────────────────────────────────────────────────
// Mirrors backend/app/api/memory.py. The four v3 doc types
// (user_profile, knowledge, strategy, habit) replace the retired
// ``memory_items`` table.

export type MasteryLevel = 'weak' | 'progressing' | 'strong' | 'unknown';

export interface KnowledgeTopicSummary {
  topic: string;
  one_liner: string | null;
  mastery_level: MasteryLevel | null;
  /** Number of bullet-list "- ..." lines in the body. Use as a
   *  "richness" hint when listing topics. */
  fact_count: number;
  last_discussed_at: string | null;
  updated_at: string | null;
}

export interface KnowledgeTopicDetail extends KnowledgeTopicSummary {
  body: string;
  created_at: string | null;
}

export interface MemoryOverviewResp {
  /** User profile doc body (markdown). Empty string when not yet seeded. */
  user_profile_body: string;
  knowledge_topics: KnowledgeTopicSummary[];
  strategy_body: string;
  habit_body: string;
}

export type MemoryDocType = 'user_profile' | 'knowledge' | 'strategy' | 'habit';

export type MemoryChangeType =
  | 'patch_realtime'
  | 'patch_dreaming'
  | 'user_edit'
  | 'user_delete'
  | 'migration';

export interface MemoryAuditEntry {
  id: string;
  doc_type: MemoryDocType;
  topic: string | null;
  change_type: MemoryChangeType;
  summary: string;
  source_record_id: string | null;
  source_session_id: string | null;
  created_at: string | null;
}

export interface MemoryAuditDetail extends MemoryAuditEntry {
  before_body: string;
  after_body: string;
}

export interface MemoryAuditListResp {
  total: number;
  limit: number;
  offset: number;
  entries: MemoryAuditEntry[];
}
