import { afterEach, beforeEach, expect, it, vi } from 'vitest';
const { post } = vi.hoisted(() => ({ post: vi.fn() }));
vi.mock('./client', () => ({ apiClient: { post, get: vi.fn(), delete: vi.fn() } }));
import { uploadFileAsset } from './fileAssets';
beforeEach(() => post.mockReset());
afterEach(() => vi.unstubAllGlobals());
it('confirms an asset only after its provider-neutral capability PUT succeeds', async () => {
  post.mockResolvedValueOnce({ data: { file_asset_id: 'asset-1', upload_url: '/api/v1/file-assets/content?capability=synthetic', filename: 'recording.wav' } }).mockResolvedValueOnce({ data: {} });
  const fetch = vi.fn().mockResolvedValue({ ok: true });
  vi.stubGlobal('fetch', fetch);
  const file = new File(['synthetic'], 'recording.wav', { type: 'audio/wav' });
  expect(await uploadFileAsset(file, 'interview_audio')).toBe('asset-1');
  expect(post.mock.calls).toEqual([
    ['/file-assets/upload-url', { purpose: 'interview_audio', filename: 'recording.wav', content_type: 'audio/wav', size_bytes: file.size }],
    ['/file-assets/asset-1/confirm'],
  ]);
  expect(fetch.mock.calls[0][1].headers).toEqual({ 'Content-Type': 'audio/wav' });
});
it('does not confirm a reserved asset after insufficient-space rejection', async () => {
  post.mockResolvedValue({ data: { file_asset_id: 'asset-2', upload_url: '/signed-local-upload' } });
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 507 }));
  await expect(uploadFileAsset(new File(['x'], 'resume.txt'), 'resume')).rejects.toThrow('存储空间不足');
  expect(post).toHaveBeenCalledTimes(1);
});
