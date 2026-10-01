import { expect, it, vi } from 'vitest';
const { get } = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock('./client', () => ({ apiClient: { get } }));
import { getStorageUsage } from './storage';
it('uses the authenticated owner-scoped API and propagates cancellation', async () => {
  const data = { backend: 'filesystem', used_bytes: 123, asset_count: 1, free_bytes: 1024, total_bytes: 2048 };
  get.mockResolvedValue({ data });
  const signal = new AbortController().signal;
  expect(await getStorageUsage(signal)).toEqual(data);
  expect(get).toHaveBeenCalledWith('/file-assets/storage-usage', { signal });
});
