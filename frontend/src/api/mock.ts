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
  jd_text?: string;
  interviewer_style?: 'friendly' | 'professional' | 'rigorous' | 'pressure';
  voice_mode?: 'text' | 'voice' | 'hybrid';
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

export interface InProgressMock {
  has_in_progress: boolean;
  session_id?: string;
  title?: string;
  current_phase?: string | null;
  current_question_idx?: number;
  qa_count?: number;
  last_activity_at?: string | null;
}

export async function getInProgressMock(): Promise<InProgressMock> {
  const res = await apiClient.get('/chat/mock-interview/in-progress');
  return res.data;
}

export async function abandonMockInterview(sessionId: string): Promise<void> {
  await apiClient.post('/chat/mock-interview/abandon', null, {
    params: { session_id: sessionId },
  });
}

// JD parsing for mock interview — stateless, does NOT persist to knowledge library.
export async function parseJdForMock(file: File): Promise<{ text: string; filename: string }> {
  const fd = new FormData();
  fd.append('file', file);
  const res = await apiClient.post('/chat/mock-interview/parse-jd', fd);
  return { text: res.data?.text ?? '', filename: res.data?.filename ?? file.name };
}
