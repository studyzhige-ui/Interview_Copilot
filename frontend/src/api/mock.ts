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

export async function startMockInterview(payload: components['schemas']['MockPreparationRequestRequestContract']): Promise<MockStartResp> {
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
  questionMessageId: number,
  options: { signal: AbortSignal; requestId: string },
): Promise<MockAnswerAudioResp> {
  const fd = new FormData();
  const mime = blob.type.toLowerCase().split(';', 1)[0].trim();
  const extension = ({ 'audio/ogg': 'ogg', 'audio/mp4': 'm4a', 'audio/wav': 'wav', 'audio/webm': 'webm' } as Record<string, string>)[mime];
  if (!extension || !blob.size) throw new Error('录音格式不受支持或录音为空，请重新录制。');
  fd.append('file', blob, `answer.${extension}`);
  fd.append('request_id', options.requestId);
  fd.append('question_message_id', String(questionMessageId));
  const res = await apiClient.post(
    `/mock-interviews/${encodeURIComponent(recordId)}/answer-audio`,
    fd,
    { signal: options.signal },
  );
  return res.data;
}

export async function readMockAnswerAudio(recordId: string, params: { request_id?: string; question_message_id?: number }, signal?: AbortSignal): Promise<MockAnswerAudioResp | null> {
  return (await apiClient.get(`/mock-interviews/${encodeURIComponent(recordId)}/answer-audio`, { params, signal })).data;
}

export async function retryMockAnswerAudio(recordId: string, requestId: string, newRequestId: string, signal: AbortSignal): Promise<MockAnswerAudioResp> {
  return (await apiClient.post(`/mock-interviews/${encodeURIComponent(recordId)}/answer-audio/${encodeURIComponent(requestId)}/retry`, { new_request_id: newRequestId }, { signal })).data;
}

/** Reads the admitted task only; refresh or reconnect never starts recognition. */
export async function waitForMockAnswerAudio(recordId: string, initial: MockAnswerAudioResp, signal: AbortSignal, onState: (state: MockAnswerAudioResp) => void): Promise<MockAnswerAudioResp> {
  let state = initial;
  while (!signal.aborted) {
    onState(state);
    if (state.status === 'completed' || state.status === 'failed') return state;
    await new Promise<void>((resolve, reject) => {
      const abort = () => { clearTimeout(timer); reject(signal.reason); };
      const timer = setTimeout(() => { signal.removeEventListener('abort', abort); resolve(); }, 1000);
      signal.addEventListener('abort', abort, { once: true });
    });
    const next = await readMockAnswerAudio(recordId, { request_id: initial.request_id }, signal);
    if (!next || next.request_id !== initial.request_id) throw new Error('录音任务已不可用');
    state = next;
  }
  throw signal.reason;
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
