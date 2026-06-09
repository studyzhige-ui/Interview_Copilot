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
  /** knowledge_documents.id when this QA's improved answer was saved (else null). */
  saved_document_id?: string | null;
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
  type: string;
  state_summary: string;
  turn_count: number;
  updated_at: string;
}

export interface ChatSessionCreateResp {
  session_id: string;
  title: string;
  type: string;
}

/**
 * Anthropic-style content block. Mirrors the persisted shape in
 * ``conversation_messages.content_blocks_json`` (backend Stage-G refactor).
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
  type: string;
  turn_count: number;
  compaction_cursor: number;
  messages: ChatMessageItem[];
  total_messages: number;
}

/** One business stage of the (frozen) interview plan, for the progress UI.
 *  Mirrors ``app.schemas.chat.MockStage``. */
export interface MockStage {
  key: string;
  title: string;
}

/** ``POST /mock-interviews/start``. The start endpoint owns creation of the
 *  record + conversation + runtime and returns the opening interviewer line. */
export interface MockStartResp {
  interview_record_id: string;
  conversation_id: string;
  runtime_id: string;
  current_stage_key: string;
  /** The opening interviewer message (greeting + first question), one string. */
  current_question: string;
  plan_phases: MockStage[];
}

/** ``POST /mock-interviews/{record_id}/answer`` — one interviewer line.
 *  No Runtime Director: the server generates the next turn from the plan +
 *  current stage + message history in a single LLM call. */
export interface MockAnswerResp {
  interviewer_message: string;
  current_stage_key: string;
  is_ready_to_finish: boolean;
}

/** ``POST /mock-interviews/{record_id}/finish`` and ``/retry-review`` — the
 *  record enters review; it appears in the review list only at review_ready. */
export interface MockFinishResp {
  status: 'processing_review';
  record_id: string;
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
