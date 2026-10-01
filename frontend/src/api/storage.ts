import { apiClient } from './client';

/** Owner-scoped readable file totals; local capacity is device-wide, not a quota. */
export interface StorageUsage {
  backend: 'filesystem' | 's3';
  used_bytes: number;
  asset_count: number;
  free_bytes: number | null;
  total_bytes: number | null;
}

export async function getStorageUsage(signal?: AbortSignal): Promise<StorageUsage> {
  return (await apiClient.get<StorageUsage>('/file-assets/storage-usage', { signal })).data;
}
