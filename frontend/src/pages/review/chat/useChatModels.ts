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

  const { data: catalog } = useQuery({
    queryKey: ['models', 'catalog'],
    queryFn: getModelsCatalog,
    refetchOnWindowFocus: true,
  });
  const { data: runtime } = useQuery({
    queryKey: ['models', 'runtime'],
    queryFn: getModelsRuntime,
    refetchOnWindowFocus: true,
  });
  const profiles = catalog?.profiles ?? [];

  // Local optimistic override on top of the server-resolved selection —
  // rolls back on save failure, exactly like the pre-split setState flow.
  const [localSelection, setLocalSelection] = useState<Partial<Record<ModelRole, string>>>({});
  const selection = {
    primary: localSelection.primary ?? runtime?.resolved?.primary?.profile_id ?? '',
    agent: localSelection.agent ?? runtime?.resolved?.agent?.profile_id ?? '',
  };

  const activeRole: ModelRole = mode === 'AGENT' ? 'agent' : 'primary';
  const activeProfileId = selection[activeRole as 'primary' | 'agent'];
  const activeProfile = profiles.find((p) => p.id === activeProfileId);
  const activeModelName = activeProfile?.display_name ?? '未配置';

  const pickModel = useCallback(async (p: ModelProfile): Promise<boolean> => {
    if (!p.ready) { toast.warn(`需先配置 ${p.api_key_env}`); return false; }
    if (activeRole === 'agent' && !p.supports_function_calling) {
      toast.warn('AGENT 角色需要支持函数调用的模型');
      return false;
    }
    const prev = activeProfileId;
    setLocalSelection((s) => ({ ...s, [activeRole]: p.id }));
    try {
      await updateModelsRuntime({ [activeRole]: p.id } as Partial<Record<ModelRole, string>>);
      toast.success(`已切换 ${activeRole === 'agent' ? 'Agent' : '主对话'}：${p.display_name}`);
      // The catalog carries ``selection`` too — refresh both so the
      // Models page reflects the pick without waiting out staleTime.
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['models', 'runtime'] }),
        queryClient.invalidateQueries({ queryKey: ['models', 'catalog'] }),
      ]);
      setLocalSelection({});
      return true;
    } catch {
      setLocalSelection((s) => ({ ...s, [activeRole]: prev }));
      toast.error('切换模型失败');
      return false;
    }
  }, [activeRole, activeProfileId, queryClient]);

  return { profiles, activeRole, activeProfileId, activeModelName, pickModel };
}
