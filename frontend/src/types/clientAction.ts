export type MockClientActionName =
  | 'mock_interview.prefill'
  | 'mock_interview.check_readiness'
  | 'mock_interview.enter_live'
  | 'interview.preparation.open';

export interface MockPrefillPayload {
  kind: 'mock_prefill';
  input_mode?: 'text' | 'voice';
  jd_snapshot_id?: string | null;
  jd_snapshot_version?: number | null;
  purpose?: 'full' | 'project_deep_dive' | 'focused_practice';
  focus?: string | null;
  resume_id?: string | null;
  jd_text: string;
  interviewer_style: 'friendly' | 'professional' | 'rigorous' | 'pressure';
  target_question_count: 15 | 20 | 30;
  job_opportunity_id?: string | null;
}

export interface MockReadinessPayload {
  kind: 'mock_readiness';
  requirements: ['microphone'];
}

export interface MockEnterLivePayload {
  kind: 'mock_enter_live';
  input_mode?: 'text' | 'voice';
  record_id: string;
  conversation_id: string;
  runtime_status: 'mock_in_progress';
}

export interface InterviewPreparationOpenPayload {
  kind: 'interview_preparation_open';
  interview_id: string;
  opportunity_id: string;
  expected_interview_version: number;
  expected_opportunity_version: number;
  source_operation_id: string;
  preferred_surface: 'interviews';
}

export type MockClientActionPayload =
  | MockPrefillPayload
  | MockReadinessPayload
  | MockEnterLivePayload
  | InterviewPreparationOpenPayload;

export interface MockClientAction {
  interaction_id: string;
  turn_id: string;
  tool_call_id: string;
  version: number;
  action_id: string;
  action: MockClientActionName;
  payload: MockClientActionPayload;
  takeover_generation: number;
  created_at: string;
}

export interface MockClientActionNotice {
  sessionId: string;
  turnId: string;
  interactionId: string;
  version: number;
  actionId: string;
  action: MockClientActionName;
}

export interface MockClientActionResolution {
  action_id: string;
  interaction_id: string;
  accepted: boolean;
  replayed: boolean;
  turn_status: 'pending' | 'running' | 'waiting' | 'completed' | 'blocked' | 'failed' | 'cancelled';
  dispatch_generation: number;
}

export interface MockClientUiResult {
  outcome: 'acknowledged' | 'refused' | 'failed';
  readiness?: 'ready';
  fallback_mode?: 'text';
  reason?: string;
}

export interface MockRouteActionState {
  mockClientAction: MockClientAction;
}
