import { apiClient } from './client';

export interface CareerActivity {
  event_id: string;
  event_category: 'domain' | 'harness' | 'experience';
  occurred_at: string;
  conversation_id: string | null;
  payload: { title?: string; detail?: string; status?: string };
}

export async function listCareerActivity(): Promise<CareerActivity[]> {
  return (await apiClient.get('/career/activity', { params: { limit: 20 } })).data;
}
