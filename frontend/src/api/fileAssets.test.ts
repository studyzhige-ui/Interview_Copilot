import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const { get } = vi.hoisted(() => ({ get: vi.fn() }));

vi.mock('./client', () => ({
  apiClient: { get, post: vi.fn(), delete: vi.fn() },
}));

import { downloadFileAsset } from './fileAssets';

describe('downloadFileAsset', () => {
  beforeEach(() => {
    get.mockReset();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('reads through the authenticated API and uses its safe filename', async () => {
    const blob = new Blob(['export']);
    get.mockResolvedValue({
      data: blob,
      headers: { 'content-disposition': "attachment; filename*=UTF-8''%E6%8A%A5%E5%91%8A.md" },
    });
    const createObjectURL = vi.fn(() => 'blob:download');
    const revokeObjectURL = vi.fn();
    vi.stubGlobal('URL', { createObjectURL, revokeObjectURL });
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined);

    await downloadFileAsset('fa/export 1', 'fallback.md');

    expect(get).toHaveBeenCalledWith(
      '/file-assets/fa%2Fexport%201/download',
      { responseType: 'blob' },
    );
    expect(createObjectURL).toHaveBeenCalledWith(blob);
    expect(click).toHaveBeenCalledOnce();
    expect((click.mock.instances[0] as HTMLAnchorElement).download).toBe('报告.md');
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:download');
    expect(document.querySelector('a[href="blob:download"]')).toBeNull();
  });
});
