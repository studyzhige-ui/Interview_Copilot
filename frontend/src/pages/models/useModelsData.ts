/**
 * Server state + actions for the Models page.
 *
 * React Query owns the catalog / providers / api-key queries (keys under
 * ['models', ...]); role selection stays local component state seeded from
 * the catalog (it changes optimistically on click and rolls back on save
 * failure), and ping results are plain action output, not a query.
 */
import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from '@/store/uiStore';
import {
  deleteMyApiKey,
  deleteProviderSettings,
  getModelsCatalog,
  listMyApiKeys,
  listProviders,
  pingAllModels,
  refreshModelCatalog,
  saveMyApiKey,
  updateModelsRuntime,
  updateProviderSettings,
  type ModelPingResult,
  type ProviderInfo,
  type UserApiKeyStatus,
} from '@/api/models';
import type { ModelRole } from '@/types/api';
import { ROLE_DESC } from './constants';

export function useModelsData() {
  const queryClient = useQueryClient();

  const catalogQuery = useQuery({
    queryKey: ['models', 'catalog'],
    queryFn: getModelsCatalog,
  });
  const providersQuery = useQuery({
    queryKey: ['models', 'providers'],
    queryFn: listProviders,
  });
  const apiKeysQuery = useQuery({
    queryKey: ['models', 'apiKeys'],
    queryFn: listMyApiKeys,
  });

  useEffect(() => {
    if (catalogQuery.isError || providersQuery.isError) {
      toast.error('模型目录加载失败');
    }
  }, [catalogQuery.isError, providersQuery.isError]);

  const profiles = catalogQuery.data?.profiles ?? [];
  const providers = providersQuery.data ?? [];
  const apiKeys: UserApiKeyStatus = apiKeysQuery.data ?? {};
  const loading = catalogQuery.isPending || providersQuery.isPending;

  // Role selection: seeded from the catalog, then locally owned so assigns
  // are optimistic (rollback on save failure).
  const [selection, setSelection] = useState<Record<ModelRole, string>>({
    primary: '', fast: '', agent: '', mock_interview: '',
  });
  useEffect(() => {
    const sel = catalogQuery.data?.selection;
    if (!sel) return;
    setSelection({
      primary: sel.primary ?? '',
      fast: sel.fast ?? '',
      agent: sel.agent ?? '',
      mock_interview: sel.mock_interview ?? sel.fast ?? '',
    });
  }, [catalogQuery.data]);

  const [pingResults, setPingResults] = useState<Record<string, ModelPingResult>>({});

  /** Refresh both the per-user provider settings AND the catalog. */
  const refresh = () => Promise.all([
    queryClient.invalidateQueries({ queryKey: ['models', 'catalog'] }),
    queryClient.invalidateQueries({ queryKey: ['models', 'providers'] }),
  ]);

  const onSaveKey = async (provider: string, key: string) => {
    try {
      const { masked } = await saveMyApiKey(provider, key);
      queryClient.setQueryData<UserApiKeyStatus>(
        ['models', 'apiKeys'],
        (k) => ({ ...(k ?? {}), [provider]: { set: true, masked } }),
      );
      refresh();
      toast.success(`${provider} 密钥已加密保存`);
      return true;
    } catch (e) {
      const detail = (e as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      toast.error(detail ?? '保存密钥失败');
      return false;
    }
  };

  const onDeleteKey = async (provider: string) => {
    try {
      await deleteMyApiKey(provider);
      queryClient.setQueryData<UserApiKeyStatus>(
        ['models', 'apiKeys'],
        (k) => {
          const { [provider]: _, ...rest } = k ?? {};
          return rest;
        },
      );
      refresh();
      toast.success(`${provider} 密钥已删除`);
    } catch {
      toast.error('删除密钥失败');
    }
  };

  /** Save api_base / organization_id overrides for one provider. */
  const onSaveProviderSettings = async (
    provider: string,
    patch: { api_base_override?: string; organization_id?: string },
  ): Promise<boolean> => {
    try {
      const updated = await updateProviderSettings(provider, patch);
      queryClient.setQueryData<ProviderInfo[]>(
        ['models', 'providers'],
        (cur) => (cur ?? []).map((p) => (p.provider === provider ? updated : p)),
      );
      toast.success(`${provider} 设置已保存`);
      return true;
    } catch (e) {
      // FastAPI 422 from Pydantic returns ``detail`` as an array of
      // validation errors. Surface the first one's message so the user
      // sees "api_base rejected: scheme not allowed" etc.
      const data = (e as { response?: { data?: { detail?: unknown } } }).response?.data?.detail;
      let msg = '保存设置失败';
      if (typeof data === 'string') msg = data;
      else if (Array.isArray(data) && data[0] && typeof data[0] === 'object') {
        msg = (data[0] as { msg?: string }).msg ?? msg;
      }
      toast.error(msg);
      return false;
    }
  };

  /** Toggle whether a provider's card shows on the Models page. */
  const onToggleProvider = async (provider: string, enabled: boolean) => {
    const setEnabled = (value: boolean) =>
      queryClient.setQueryData<ProviderInfo[]>(
        ['models', 'providers'],
        (cur) => (cur ?? []).map((p) => (p.provider === provider ? { ...p, enabled: value } : p)),
      );
    // Optimistic update so the picker feels snappy.
    setEnabled(enabled);
    try {
      await updateProviderSettings(provider, { enabled });
    } catch {
      // Rollback on failure.
      setEnabled(!enabled);
      toast.error('设置失败');
    }
  };

  /** Wipe ALL per-user overrides for a provider (api_base + org_id + enabled).
   * Does NOT delete the encrypted API key. */
  const onResetProvider = async (provider: string) => {
    try {
      await deleteProviderSettings(provider);
      // After reset, the provider returns to its default settings.
      // Reload providers to pick up the new effective state.
      refresh();
      toast.success(`${provider} 设置已重置`);
    } catch {
      toast.error('重置失败');
    }
  };

  const pingMutation = useMutation({
    mutationFn: pingAllModels,
    onSuccess: (results) => {
      const map: Record<string, ModelPingResult> = {};
      for (const r of results) map[r.profile_id] = r;
      setPingResults(map);
      const reachable = results.filter((r) => r.ok).length;
      toast.success(`已 ping ${results.length} 个模型，${reachable} 个可达`);
    },
    onError: () => toast.error('Ping 失败'),
  });

  const refreshCatalogMutation = useMutation({
    mutationFn: refreshModelCatalog,
    onSuccess: async (result) => {
      await refresh();
      toast.success(
        `已从各厂商官方 /v1/models 拉取 ${result.profiles_total} 个模型 ` +
        `（${result.providers_refreshed} 家厂商）`,
      );
    },
    onError: (err) => {
      const detail = (err as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      toast.error(detail ?? '刷新模型库失败');
    },
  });

  const assign = async (role: ModelRole, profileId: string) => {
    const prev = selection[role];
    if (prev === profileId) return;
    setSelection((s) => ({ ...s, [role]: profileId }));
    try {
      await updateModelsRuntime({ [role]: profileId });
      toast.success(`${ROLE_DESC[role].label}：${profileId}`);
      // The chat header reads ['models','runtime'] and re-seeds from the
      // catalog's ``selection`` — refresh both so a pick here shows up
      // there without waiting out staleTime.
      queryClient.invalidateQueries({ queryKey: ['models', 'runtime'] });
      queryClient.invalidateQueries({ queryKey: ['models', 'catalog'] });
    } catch (err) {
      setSelection((s) => ({ ...s, [role]: prev }));
      const detail = (err as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      toast.error(detail ?? '保存失败');
    }
  };

  return {
    loading,
    profiles,
    providers,
    apiKeys,
    selection,
    pingResults,
    pinging: pingMutation.isPending,
    refreshingCatalog: refreshCatalogMutation.isPending,
    refresh,
    assign,
    pingAll: () => pingMutation.mutate(),
    refreshCatalog: () => refreshCatalogMutation.mutate(),
    onSaveKey,
    onDeleteKey,
    onSaveProviderSettings,
    onToggleProvider,
    onResetProvider,
  };
}
