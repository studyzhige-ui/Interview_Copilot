// All shapes mirror backend source-of-truth. See:
//   backend/app/api/interview.py
//   backend/app/api/chat/sessions.py + mock_interview.py + streaming.py
//   backend/app/api/rag.py
//   backend/app/api/model_runtime.py
// Do NOT introduce fields the backend does not return.

export interface InterviewRecordListItem {
  id: string;
  source: string;
  title: string;
  tag?: string | null;
  status: string;
  created_at: string;
}

export interface InterviewRecordDetail extends InterviewRecordListItem {
  audio_upload_id: string | null;
  resume_upload_id: string | null;
  jd_upload_id: string | null;
  transcript: string | null;
  analysis: unknown;
  updated_at: string;
}

export interface InterviewQA {
  index: number;
  phase?: string;
  question: string;
  answer: string;
  score?: number;             // 0-10 from per-question stage
  critique?: string;
  improved_answer?: string;   // LLM "优化回答" content
  tags?: string[];
}

export interface InterviewAnalysis {
  interview_metadata?: { total_questions?: number; phases?: string[] };
  overall?: {
    score?: number;
    grade?: string;
    verdict?: string;
    feedback?: string;
    strengths?: string[];
    weaknesses?: string[];
    improvement_plan?: string[];
  };
  per_question?: InterviewQA[];
  // mock-interview shape
  qa_history?: Array<{ question?: string; answer?: string; phase_id?: string }>;
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
  | { type: 'done' };

export interface MockPlanPhase {
  phase_id: string;
  phase_name: string;
  question_count: number;
}

export interface MockQuestion {
  question?: string;
  phase_id?: string;
  done?: boolean;
}

export interface MockStartResp {
  status: string;
  plan_phases: MockPlanPhase[];
  current_question: MockQuestion;
}

export interface MockAnswerResp {
  interviewer_response: string;
  is_finished: boolean;
  phase_progress: {
    current_phase: string;
    question_idx: number;
    total_answered: number;
  };
}

export interface MockFinishResp {
  status: string;
  record_id: string;
  debrief_session_id: string;
  summary: unknown;
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

export type ModelRole = 'primary' | 'fast' | 'agent';

export interface ModelRuntime {
  selection: Record<ModelRole, string>;
  resolved: Record<
    ModelRole,
    { profile_id: string; provider: string; model: string; display_name: string }
  >;
}

export interface AnalyzeStatus {
  interview_id: number;
  status: string;
  analysis?: {
    score?: number;
    feedback?: string;
    per_question?: unknown;
  };
}
