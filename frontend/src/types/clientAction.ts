export type MockClientActionName =
  | 'mock_interview.prefill'
  | 'mock_interview.check_readiness'
  | 'mock_interview.enter_live';

export interface MockPrefillPayload {
  kind: 'mock_prefill';
  resume_id: string;
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
  record_id: string;
  conversation_id: string;
  runtime_status: 'mock_in_progress';
}

export type MockClientActionPayload =
  | MockPrefillPayload
  | MockReadinessPayload
  | MockEnterLivePayload;

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
  reason?: string;
}

export interface MockRouteActionState {
  mockClientAction: MockClientAction;
}
