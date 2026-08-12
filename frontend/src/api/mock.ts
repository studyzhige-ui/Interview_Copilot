import { apiClient } from './client';
import type {
  MockAnswerResp,
  MockAnswerAudioResp,
  MockFinishResp,
  MockLiveMessage,
  MockStartResp,
} from '@/types/api';

export async function startMockInterview(payload: {
  resume_id: string;
  jd_text: string;
  interviewer_style: 'friendly' | 'professional' | 'rigorous' | 'pressure';
  target_question_count: 15 | 20 | 30;
}): Promise<MockStartResp> {
  const res = await apiClient.post('/mock-interviews/start', payload);
  return res.data;
}

export async function submitMockAnswer(
  recordId: string,
  payload: {
    answer_text: string;
    answer_audio_file_asset_id?: string;
    /** Concurrency token (MOCK-3): id of the question being answered. */
    question_message_id: number;
  },
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
  return res.data;
}

// JD parsing for mock interview — stateless, does NOT persist to knowledge library.
export async function parseJdForMock(file: File): Promise<{ text: string; filename: string }> {
  const fd = new FormData();
  fd.append('file', file);
  const res = await apiClient.post('/mock-interviews/parse-jd', fd);
  return { text: res.data?.text ?? '', filename: res.data?.filename ?? file.name };
}
