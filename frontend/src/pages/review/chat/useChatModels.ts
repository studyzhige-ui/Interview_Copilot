import { useCallback, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from '@/store/uiStore';
import { getModelsCatalog, getModelsRuntime, updateModelsRuntime } from '@/api/models';
import type { ModelProfile, ModelRole } from '@/types/api';
import type { Mode } from './types';

/**
 * Model picker state for the chat header.
 *
 * The catalog query shares its key (['models', 'catalog']) with the
 * Models page, so a profile list fetched on either page serves both.
 * ``refetchOnWindowFocus`` restores the old focus-refresh behavior:
 * picking a model on the Models page in another tab reflects here on
 * return.
 */
export function useChatModels(mode: Mode) {
  const queryClient = useQueryClient();

  const catalogQuery = useQuery({
    queryKey: ['models', 'catalog'],
    queryFn: getModelsCatalog,
    refetchOnWindowFocus: true,
  });
  const runtimeQuery = useQuery({
    queryKey: ['models', 'runtime'],
    queryFn: getModelsRuntime,
    refetchOnWindowFocus: true,
  });
  const catalog = catalogQuery.data;
  const runtime = runtimeQuery.data;
  const profiles = catalog?.profiles ?? [];

  // Local optimistic override on top of the server-resolved selection —
  // rolls back on save failure, exactly like the pre-split setState flow.
  const [localSelection, setLocalSelection] = useState<Partial<Record<ModelRole, string>>>({});
  const selection = {
    primary: localSelection.primary ?? runtime?.resolved?.primary?.profile_id ?? '',
  };

  const activeProfileId = selection.primary;
  const activeProfile = profiles.find((p) => p.id === activeProfileId);
  const activeModelName = activeProfile?.display_name ?? '未配置';

  const pickModel = useCallback(async (p: ModelProfile): Promise<boolean> => {
    if (!p.ready) { toast.warn(`需先配置 ${p.api_key_env}`); return false; }
    if (mode === 'AGENT' && !p.supports_function_calling) {
      toast.warn('AGENT 角色需要支持函数调用的模型');
      return false;
    }
    const prev = activeProfileId;
    setLocalSelection((s) => ({ ...s, primary: p.id }));
    try {
      await updateModelsRuntime({ primary: p.id });
      toast.success(`已切换回答模型：${p.display_name}`);
      // The catalog carries ``selection`` too — refresh both so the
      // Models page reflects the pick without waiting out staleTime.
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['models', 'runtime'] }),
        queryClient.invalidateQueries({ queryKey: ['models', 'catalog'] }),
      ]);
      setLocalSelection({});
      return true;
    } catch {
      setLocalSelection((s) => ({ ...s, primary: prev }));
      toast.error('切换模型失败');
      return false;
    }
  }, [activeProfileId, mode, queryClient]);

  const modelBlocker = catalogQuery.isError || runtimeQuery.isError
    ? '暂时无法读取回答模型配置，请重新检查连接。'
    : catalogQuery.isPending || runtimeQuery.isPending ? '正在检查回答模型…'
      : !activeProfile?.ready ? '需要先配置一个回答模型，才能开始协作。'
        : mode === 'AGENT' && !activeProfile.supports_function_calling ? '当前模型不能执行协作工具，请选择支持工具调用的模型。' : null;
  const retryModels = () => { void catalogQuery.refetch(); void runtimeQuery.refetch(); };
  return { profiles, activeProfileId, activeModelName, pickModel, modelBlocker, retryModels };
}
