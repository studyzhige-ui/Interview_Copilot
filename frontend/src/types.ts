export type SessionListItem = {
  session_id: string;
  title: string;
  working_state_summary: string;
  turn_count: number;
  updated_at: string;
};

export type MessageItem = {
  seq: number;
  role: "user" | "assistant" | "system";
  content: string;
  created_at: string;
};

export type ModelProfile = {
  id: string;
  provider: string;
  display_name: string;
  model: string;
  api_base: string;
  api_key_env: string;
  supports_function_calling: boolean;
  description: string;
  ready: boolean;
  selected_for: string[];
};

export type MemoryItem = {
  id: string;
  type: string;
  description: string;
  normalized_key: string;
  confidence: number;
  recall_count: number;
  source_session_id?: string;
  updated_at?: string;
};

export type AnalysisPayload = {
  interview_id: number;
  status: string;
  analysis?: {
    score: number;
    feedback: string;
    improved_answer: unknown;
  };
};
