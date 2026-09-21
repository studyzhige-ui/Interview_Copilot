import { beforeEach, expect, it, vi } from 'vitest';
import { readAnswerIntent, rememberAnswerIntent, clearAnswerIntent } from './answerIntent';
import { getMockAnswerReceipt, submitMockAnswer } from './mock';
import { apiClient } from './client';

vi.mock('./client', () => ({ apiClient: { post: vi.fn(), get: vi.fn() } }));
const id = '00000000-0000-4000-8000-000000000001';
const other = '00000000-0000-4000-8000-000000000002';
beforeEach(() => { vi.clearAllMocks(); sessionStorage.clear(); });

it('persists only scoped identity and never removes a newer pending intent', () => {
  rememberAnswerIntent('record-a', id, 1);
  expect(readAnswerIntent('record-b')).toBeNull();
  expect(readAnswerIntent('record-a')).toEqual({ requestId: id, questionMessageId: 1 });
  rememberAnswerIntent('record-a', other, 2); clearAnswerIntent('record-a', id);
  expect(readAnswerIntent('record-a')?.requestId).toBe(other);
  clearAnswerIntent('record-a', other); expect(readAnswerIntent('record-a')).toBeNull();
});
it('ignores malformed recovery metadata without a fallback write', () => {
  for (const raw of ['{', JSON.stringify({ requestId: 'bad', questionMessageId: 1 }), JSON.stringify({ requestId: id, questionMessageId: true })]) {
    sessionStorage.setItem('mock-answer-intent:r', raw);
    expect(readAnswerIntent('r')).toBeNull();
  }
});
it('keeps the request ID after response loss without persisting answer contents', async () => {
  vi.mocked(apiClient.post).mockRejectedValueOnce(new Error('lost response'));
  await expect(submitMockAnswer('r', { request_id: id, question_message_id: 3, answer_text: 'private answer' })).rejects.toThrow('lost');
  expect(readAnswerIntent('r')?.requestId).toBe(id);
  expect(sessionStorage.getItem('mock-answer-intent:r')).not.toContain('private answer');
  expect(apiClient.post).toHaveBeenCalledTimes(1);
});
it('receipt mismatch fails and never retries the model call', async () => {
  vi.mocked(apiClient.get).mockResolvedValueOnce({ data: { request_id: other } });
  await expect(getMockAnswerReceipt('r', id)).rejects.toThrow('编号不匹配');
  expect(apiClient.post).not.toHaveBeenCalled();
});
