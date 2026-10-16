import { apiClient } from './client';

export interface WorkspaceOverview {
  has_resume: boolean;
  active_opportunities: number;
  open_actions: number;
  recent_work: Array<{
    session_id: string;
    title: string;
    status: 'pending' | 'running' | 'waiting' | 'blocked' | 'failed';
    updated_at: string | null;
  }>;
  upcoming_interviews: Array<{
    id: string; opportunity_id: string; company_name: string; job_title: string; starts_at: string;
  }>;
}

export async function getWorkspaceOverview(): Promise<WorkspaceOverview> {
  return (await apiClient.get('/workspace')).data;
}
