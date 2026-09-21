import { apiClient } from './client';
import { isAxiosError } from 'axios';
import type { components } from '@/types/generated/shared-protocols';
import { clearAnswerIntent, rememberAnswerIntent } from './answerIntent';

export type MockAnswerReceipt = components['schemas']['MockAnswerReceiptResponseContract'];
type MockAnswerCommand = components['schemas']['MockAnswerRequestRequestContract'];
import type {
  MockAnswerResp,
  MockAnswerAudioResp,
  MockFinishResp,
  MockLiveMessage,
  MockStartResp,
} from '@/types/api';

export async function startMockInterview(payload: {
  resume_id?: string | null;
  purpose?: 'full' | 'project_deep_dive' | 'focused_practice';
  focus?: string;
  jd_text?: string;
  jd_snapshot_id?: string;
  jd_snapshot_version?: number;
  input_mode?: 'text' | 'voice';
  interviewer_style: 'friendly' | 'professional' | 'rigorous' | 'pressure';
  target_question_count: 15 | 20 | 30;
  job_opportunity_id?: string;
}): Promise<MockStartResp> {
  const res = await apiClient.post('/mock-interviews/start', payload);
  return res.data;
}

export async function submitMockAnswer(
  recordId: string,
  payload: MockAnswerCommand,
): Promise<MockAnswerResp> {
  rememberAnswerIntent(recordId, payload.request_id, payload.question_message_id);
  const res = await apiClient.post(
    `/mock-interviews/${encodeURIComponent(recordId)}/answer`,
    payload,
  );
  clearAnswerIntent(recordId, payload.request_id);
  return res.data;
}

/** Read-only reconciliation. A missing receipt never triggers a POST. */
export async function getMockAnswerReceipt(recordId: string, requestId: string): Promise<MockAnswerReceipt | null> {
  try {
    const response = await apiClient.get<MockAnswerReceipt>(
      `/mock-interviews/${encodeURIComponent(recordId)}/answer-receipts/${encodeURIComponent(requestId)}`,
    );
    if (response.data.request_id !== requestId) throw new Error('回答收据编号不匹配');
    return response.data;
  } catch (error) {
    if (isAxiosError(error) && error.response?.status === 404) return null;
    throw error;
  }
}

export async function finishMockInterview(recordId: string): Promise<MockFinishResp> {
  const res = await apiClient.post(`/mock-interviews/${encodeURIComponent(recordId)}/finish`);
  clearAnswerIntent(recordId);
  return res.data;
}

export async function retryMockReview(recordId: string): Promise<MockFinishResp> {
  const res = await apiClient.post(
    `/mock-interviews/${encodeURIComponent(recordId)}/retry-review`,
  );
  return res.data;
}

export async function prepareMockAnswerAudio(
  recordId: string,
  blob: Blob,
): Promise<MockAnswerAudioResp> {
  const fd = new FormData();
  const extension = blob.type.includes('ogg') ? 'ogg' : 'webm';
  fd.append('file', blob, `answer.${extension}`);
  const res = await apiClient.post(
    `/mock-interviews/${encodeURIComponent(recordId)}/answer-audio`,
    fd,
  );
  return res.data;
}

interface InProgressMock {
  has_in_progress: boolean;
  record_id?: string;
  title?: string;
  last_activity_at?: string | null;
}

export async function getInProgressMock(): Promise<InProgressMock> {
  const res = await apiClient.get('/mock-interviews/in-progress');
  return res.data;
}

export async function getMockLiveState(
  recordId: string,
): Promise<{ messages: MockLiveMessage[] }> {
  const res = await apiClient.get(
    `/mock-interviews/${encodeURIComponent(recordId)}/live-state`,
  );
  return res.data;
}

/** ``MockAbandonResp`` from the backend (``DELETE /mock-interviews/{id}``). */
interface AbandonMockResp {
  status: 'deleted';
  record_id: string;
}

export async function abandonMockInterview(recordId: string): Promise<AbandonMockResp> {
  const res = await apiClient.delete(`/mock-interviews/${encodeURIComponent(recordId)}`);
  clearAnswerIntent(recordId);
  return res.data;
}

// JD parsing for mock interview — stateless, does NOT persist to knowledge library.
export async function parseJdForMock(file: File): Promise<{ text: string; filename: string }> {
  const fd = new FormData();
  fd.append('file', file);
  const res = await apiClient.post('/mock-interviews/parse-jd', fd);
  return { text: res.data?.text ?? '', filename: res.data?.filename ?? file.name };
}
