import { apiClient } from './client';
export interface CareerActivity {
  event_id: string; event_kind: string; event_category: 'domain' | 'harness' | 'experience';
  schema_version: number; occurred_at: string; operation_id: string | null;
  conversation_id: string | null; interaction_id: string | null; replayable: boolean;
  payload: Record<string, unknown>;
}
export async function listCareerActivity(): Promise<CareerActivity[]> {
  return (await apiClient.get('/career/activity', { params: { limit: 100 } })).data;
}
