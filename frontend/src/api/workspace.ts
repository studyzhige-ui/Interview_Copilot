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
