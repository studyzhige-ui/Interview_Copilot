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
  audio_upload_id: string | null;
  resume_upload_id: string | null;
  jd_upload_id: string | null;
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

export interface ChatMessageItem {
  seq: number;
  role: string;
  content: string;
  created_at: string;
}

export type WSEvent =
  | { type: 'chunk'; content: string }
  | { type: 'status'; content: string }
  | { type: 'done' };

export interface MockPlanPhase {
  phase_id: string;
  phase_name: string;
  question_count: number;
}

export interface MockQuestion {
  question?: string;
  phase_id?: string;
  phase_name?: string;
  done?: boolean;
  // v6 director may attach the cached spoken_response from the previous turn
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
  // Concatenated spoken_response + next_question for the TTS layer and any
  // existing single-bubble UI. New code should prefer the split fields below.
  interviewer_response: string;
  // v6 Runtime Director output. Optional so a stale frontend stays happy.
  spoken_response?: string;
  next_question?: string;
  action?: MockDirectorAction;
  display_intent?: string;
  is_finished: boolean;
  phase_progress: {
    current_phase: string;
    // v6 renamed: turn_count + max_turns + follow_up_depth. Old keys
    // (question_idx / total_answered) are gone — see Mock UI for the new
    // progress chip.
    turn_count?: number;
    max_turns?: number;
    follow_up_depth?: number;
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
  source_type: string;
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
