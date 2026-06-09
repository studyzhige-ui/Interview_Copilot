import { apiClient } from './client';
import type { MockAnswerResp, MockFinishResp, MockStartResp } from '@/types/api';

export async function startMockInterview(payload: {
  /** Personal resume entity (resumes.id) to use as context. */
  resume_id?: string;
  /** Freshly-uploaded resume file asset (file_assets.id). */
  resume_file_asset_id?: string;
  /** JD text — pasted or parsed inline. JD is never a knowledge document. */
  jd_text?: string;
  jd_file_asset_id?: string;
  plan_template_key?: string;
  interviewer_style?: 'friendly' | 'professional' | 'rigorous' | 'pressure';
  voice_mode?: 'text' | 'voice' | 'hybrid';
}): Promise<MockStartResp> {
  const res = await apiClient.post('/mock-interviews/start', payload);
  return res.data;
}

export async function submitMockAnswer(
  recordId: string,
  payload: { answer_text: string; answer_audio_file_asset_id?: string },
): Promise<MockAnswerResp> {
  const res = await apiClient.post(
    `/mock-interviews/${encodeURIComponent(recordId)}/answer`,
    payload,
  );
  return res.data;
}

export async function finishMockInterview(recordId: string): Promise<MockFinishResp> {
  const res = await apiClient.post(`/mock-interviews/${encodeURIComponent(recordId)}/finish`);
  return res.data;
}

export async function retryMockReview(recordId: string): Promise<MockFinishResp> {
  const res = await apiClient.post(
    `/mock-interviews/${encodeURIComponent(recordId)}/retry-review`,
  );
  return res.data;
}

// transcribe endpoint shipped — backend POST /mock-interviews/transcribe
export const TRANSCRIBE_AVAILABLE = true;

export async function transcribeAudio(blob: Blob): Promise<string> {
  const fd = new FormData();
  fd.append('file', blob, 'answer.webm');
  const res = await apiClient.post('/mock-interviews/transcribe', fd);
  return res.data?.text ?? '';
}

export interface InProgressMock {
  has_in_progress: boolean;
  record_id?: string;
  conversation_id?: string;
  runtime_id?: string;
  title?: string;
  current_stage_key?: string | null;
  /** The last interviewer line — what the candidate is answering. */
  current_question?: string | null;
  last_activity_at?: string | null;
}

export async function getInProgressMock(): Promise<InProgressMock> {
  const res = await apiClient.get('/mock-interviews/in-progress');
  return res.data;
}

/** ``MockAbandonResp`` from the backend (``DELETE /mock-interviews/{id}``). */
export interface AbandonMockResp {
  status: 'deleted';
  record_id: string;
}

export async function abandonMockInterview(recordId: string): Promise<AbandonMockResp> {
  const res = await apiClient.delete(`/mock-interviews/${encodeURIComponent(recordId)}`);
  return res.data;
}

// JD parsing for mock interview — stateless, does NOT persist to knowledge library.
export async function parseJdForMock(file: File): Promise<{ text: string; filename: string }> {
  const fd = new FormData();
  fd.append('file', file);
  const res = await apiClient.post('/mock-interviews/parse-jd', fd);
  return { text: res.data?.text ?? '', filename: res.data?.filename ?? file.name };
}
