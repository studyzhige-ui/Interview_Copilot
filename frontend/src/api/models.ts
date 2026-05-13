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
