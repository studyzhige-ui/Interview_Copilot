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
  providers_refreshed: number;
  profiles_total: number;
  profiles: ModelProfile[];
}

/** Force the backend to re-fetch each vendor's /v1/models (P7-A). */
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


// ── Per-user provider settings (P6-M) ─────────────────────────────────

/** One row of GET /models/providers. */
export interface ProviderInfo {
  provider: string;                  // PROVIDERS dict id, e.g. "openai"
  display_label: string;
  icon_slug: string | null;
  enabled: boolean;                  // shown on the Models page for THIS user
  has_user_row: boolean;             // user has overridden any field
  api_base: string;                  // effective (override if set, else default)
  api_base_override: string | null;  // null = using default
  organization_id: string | null;
  extra_headers_json: string | null; // raw JSON string; v1 UI doesn't expose
  api_key_env: string;               // env-var name to surface in placeholders
  has_user_api_key: boolean;         // user has saved an encrypted key
}

export async function listProviders(): Promise<ProviderInfo[]> {
  const res = await apiClient.get('/models/providers');
  return res.data?.providers ?? [];
}

export async function getProviderSettings(provider: string): Promise<ProviderInfo> {
  const res = await apiClient.get(
    `/models/providers/${encodeURIComponent(provider)}`,
  );
  return res.data?.provider;
}

export interface ProviderSettingsPatch {
  enabled?: boolean;
  api_base_override?: string;     // pass "" to clear
  organization_id?: string;       // pass "" to clear
  extra_headers_json?: string;    // v1 only via direct PATCH; no UI
}

export async function updateProviderSettings(
  provider: string,
  patch: ProviderSettingsPatch,
): Promise<ProviderInfo> {
  const res = await apiClient.patch(
    `/models/providers/${encodeURIComponent(provider)}`,
    patch,
  );
  return res.data?.provider;
}

export async function deleteProviderSettings(provider: string): Promise<void> {
  await apiClient.delete(`/models/providers/${encodeURIComponent(provider)}`);
}
