import { apiClient } from './client';
import type {
  MockAnswerResp,
  MockFinishResp,
  MockQuestion,
  MockStartResp,
} from '@/types/api';

export async function startMockInterview(payload: {
  session_id: string;
  resume_upload_id?: string;
  jd_upload_id?: string;
}): Promise<MockStartResp> {
  const res = await apiClient.post('/chat/mock-interview/start', payload);
  return res.data;
}

export async function getMockCurrentQuestion(sessionId: string): Promise<MockQuestion> {
  const res = await apiClient.get('/chat/mock-interview/question', { params: { session_id: sessionId } });
  return res.data;
}

export async function submitMockAnswer(payload: {
  session_id: string;
  answer: string;
}): Promise<MockAnswerResp> {
  const res = await apiClient.post('/chat/mock-interview/answer', payload);
  return res.data;
}

export async function finishMockInterview(sessionId: string): Promise<MockFinishResp> {
  const res = await apiClient.post(
    '/chat/mock-interview/finish',
    null,
    { params: { session_id: sessionId } },
  );
  return res.data;
}

// transcribe endpoint shipped — backend POST /chat/mock-interview/transcribe
export const TRANSCRIBE_AVAILABLE = true;

export async function transcribeAudio(blob: Blob): Promise<string> {
  const fd = new FormData();
  fd.append('file', blob, 'answer.webm');
  const res = await apiClient.post('/chat/mock-interview/transcribe', fd);
  return res.data?.text ?? '';
}
