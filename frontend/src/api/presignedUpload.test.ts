import { afterEach, expect, it, vi } from 'vitest';
import { putFileToPresignedUrl } from './presignedUpload';

afterEach(() => vi.unstubAllGlobals());
it.each(['/api/v1/file-assets/local-content?capability=synthetic', 'https://storage.example.test/signed-object?signature=synthetic'])(
  'uploads unchanged to capability URL %s without account credentials', async (url) => {
    const fetch = vi.fn().mockResolvedValue({ ok: true });
    vi.stubGlobal('fetch', fetch);
    const file = new File(['synthetic bytes'], 'resume.txt', { type: 'text/plain' });
    await putFileToPresignedUrl(url, file);
    expect(fetch).toHaveBeenCalledWith(url, { method: 'PUT', body: file, headers: { 'Content-Type': 'text/plain' } });
  },
);
it('reports capacity failure without disclosing capability URLs', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 507 }));
  await expect(putFileToPresignedUrl('/signed?secret=synthetic', new File(['x'], 'x'))).rejects.toThrow('存储空间不足');
});
it('uses a neutral content type and reports rejected size', async () => {
  const fetch = vi.fn().mockResolvedValue({ ok: false, status: 413 });
  vi.stubGlobal('fetch', fetch);
  await expect(putFileToPresignedUrl('/signed', new File(['x'], 'x'))).rejects.toThrow('文件超过');
  expect(fetch.mock.calls[0][1].headers).toEqual({ 'Content-Type': 'application/octet-stream' });
});
