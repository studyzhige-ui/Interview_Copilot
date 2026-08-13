export type PersistentTaskState = 'active' | 'paused';

export type PersistentTaskTriggerSpec =
  | { kind: 'scheduled'; schedule: string; timezone: string }
  | { kind: 'event'; connector: string; event_types: string[] };

export interface PersistentTask {
  id: string;
  user_id: number;
  conversation_id: string;
  title: string;
  instruction: string;
  state: PersistentTaskState;
  version: number;
  trigger_kind: PersistentTaskTriggerSpec['kind'];
  trigger_spec_json: PersistentTaskTriggerSpec;
  read_scope_json: string[];
  action_scope_json: string[];
  allowed_tool_names_json: string[];
  user_request_identity: string;
  user_request_version: string | null;
  compensation_blocked_at: string | null;
  next_due_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface PersistentTaskDefinitionInput {
  title: string;
  instruction: string;
  trigger: PersistentTaskTriggerSpec;
  readScope: string[];
  actionScope: string[];
  allowedToolNames: string[];
}

export interface PersistentTaskEligibleTool {
  name: string;
  description: string;
}

export interface PersistentTaskTriggerAdmission {
  trigger_id: string | null;
  status: 'admitted' | 'pending' | 'already_admitted' | 'empty';
  reason: string | null;
  turn_id: string | null;
  merged_trigger_ids: string[];
  pending_trigger_count: number;
}

export type PersistentTaskTriggerKind = 'scheduled' | 'event' | 'manual';

/** A retained trigger fact. Admission fields describe whether it became a Turn;
 *  this is deliberately not presented as an execution result. */
export interface PersistentTaskTrigger {
  id: string;
  persistent_task_id: string;
  kind: PersistentTaskTriggerKind;
  occurred_at: string;
  observed_at: string;
  source_identity: string;
  source_version: string | null;
  summary: string;
  cursor_after: string | null;
  admitted_turn_id: string | null;
  admitted_at: string | null;
  created_at: string;
}

export interface PersistentTaskDeleteResponse {
  status: 'success';
  id: string;
}
