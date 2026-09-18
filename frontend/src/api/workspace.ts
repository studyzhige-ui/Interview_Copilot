import { apiClient } from './client';

export interface WorkspaceOverview {
  has_resume: boolean;
  active_opportunities: number;
  open_actions: number;
  recent_work: Array<{
    session_id: string;
    title: string;
    status: 'not_started' | 'pending' | 'running' | 'waiting' | 'completed' | 'blocked' | 'failed' | 'cancelled' | 'unknown';
    updated_at: string | null;
  }>;
}

export async function getWorkspaceOverview(): Promise<WorkspaceOverview> {
  return (await apiClient.get('/workspace')).data;
}


export interface PrimaryModelUsage {
  scope: 'primary_chat_agent';
  unit: 'logical_tokens_not_currency';
  window_date: string;
  timezone: 'UTC';
  call_limit: number;
  token_limit: number;
  calls_admitted: number;
  tokens_used: number;
  tokens_reserved: number;
  excluded: string[];
}

export async function getPrimaryModelUsage(): Promise<PrimaryModelUsage> {
  return (await apiClient.get('/workspace/model-usage')).data;
}
