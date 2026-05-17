import { apiClient } from './client';
import type { ModelProfile, ModelRole, ModelRuntime } from '@/types/api';

export async function getModelsCatalog(): Promise<{
  selection: Record<ModelRole, string>;
  profiles: ModelProfile[];
}> {
  const res = await apiClient.get('/models/catalog');
  return {
    selection: res.data?.selection ?? {},
    profiles: res.data?.profiles ?? [],
  };
}

export async function getModelsRuntime(): Promise<ModelRuntime> {
  const res = await apiClient.get('/models/runtime');
  return {
    selection: res.data?.selection ?? {},
    resolved: res.data?.resolved ?? {},
  };
}

export async function updateModelsRuntime(
  patch: Partial<Record<ModelRole, string>>,
): Promise<Record<ModelRole, string>> {
  const res = await apiClient.put('/models/runtime', patch);
  return res.data?.selection ?? {};
}

export interface ModelPingResult {
  profile_id: string;
  ok: boolean;
  latency_ms: number;
  error?: string;
}

export async function pingAllModels(): Promise<ModelPingResult[]> {
  const res = await apiClient.post('/models/ping', null, { timeout: 60_000 });
  return res.data?.results ?? [];
}

export interface RefreshCatalogResult {
  status: string;
  discovery_cache_dropped: number;
  profiles_total: number;
  profiles_auto_discovered: number;
  profiles: ModelProfile[];
}

/** Force the backend to re-discover models from each vendor's /v1/models endpoint. */
export async function refreshModelCatalog(): Promise<RefreshCatalogResult> {
  const res = await apiClient.post('/models/refresh-catalog', null, { timeout: 60_000 });
  return res.data;
}

export interface UserApiKeyStatus {
  [provider: string]: { set: boolean; masked: string };
}

export async function listMyApiKeys(): Promise<UserApiKeyStatus> {
  const res = await apiClient.get('/models/api-keys');
  return res.data?.keys ?? {};
}

export async function saveMyApiKey(provider: string, apiKey: string): Promise<{ masked: string }> {
  const res = await apiClient.put(
    `/models/api-keys/${encodeURIComponent(provider)}`,
    { api_key: apiKey },
  );
  return { masked: res.data?.masked ?? '' };
}

export async function deleteMyApiKey(provider: string): Promise<void> {
  await apiClient.delete(`/models/api-keys/${encodeURIComponent(provider)}`);
}
