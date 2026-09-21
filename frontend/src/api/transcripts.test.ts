import { beforeEach, expect, it, vi } from 'vitest';
import { apiClient } from './client';
import { getTranscriptAudio } from './transcripts';
vi.mock('./client', () => ({ apiClient: { post: vi.fn(), get: vi.fn() } }));
beforeEach(() => vi.resetAllMocks());
it('rejects wrong transcript/hash/content type before playback can create a URL', async () => {
  const selection = { transcript_id: 'tr1', first_word_id: 'w000001', last_word_id: 'w000001' };
  for (const [id, hash, type] of [['tr2', 'hash', 'audio/wav'], ['tr1', 'wrong', 'audio/wav'], ['tr1', 'hash', 'text/html']]) {
    vi.mocked(apiClient.post).mockResolvedValue({ headers: { 'x-transcript-id': id, 'x-audio-source-sha256': hash }, data: new Blob(['x'], { type }) });
    await expect(getTranscriptAudio('r1', selection, 'hash', new AbortController().signal)).rejects.toThrow('不一致');
  }
});
it('accepts only the verified bounded clip and does not change its bytes', async () => {
  const blob = new Blob(['wav'], { type: 'audio/wav' });
  vi.mocked(apiClient.post).mockResolvedValue({ headers: { 'x-transcript-id': 'tr1', 'x-audio-source-sha256': 'hash' }, data: blob });
  expect(await getTranscriptAudio('r1', { transcript_id: 'tr1', first_word_id: 'w000001', last_word_id: 'w000001' }, 'hash', new AbortController().signal)).toBe(blob);
});
