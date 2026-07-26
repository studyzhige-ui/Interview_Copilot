/**
 * 模型配置 page — vendor cards + role assignment.
 *
 * Page shell only: layout, header actions, role bar, vendor grid. Server
 * state + actions live in useModelsData; the pieces are one file each
 * (VendorCard / VendorSettingsModal / ShowMoreProvidersModal / ModelRow /
 * VendorAvatar).
 */
import { useMemo, useState } from 'react';
import { RefreshCw, Activity, Sparkles, Plus } from 'lucide-react';
import { Pill } from '@/components/ui/Pill';
import { Spinner } from '@/components/ui/Spinner';
import { useEditionPolicy } from '@/hooks/useEditionPolicy';
import type { ModelProfile } from '@/types/api';
import { ROLE_DESC, ROLES } from './constants';
import { useModelsData } from './useModelsData';
import { VendorCard } from './VendorCard';
import { ShowMoreProvidersModal } from './ShowMoreProvidersModal';

export function ModelsPage() {
  const edition = useEditionPolicy();
  const {
    loading, profiles, providers, apiKeys, selection, pingResults,
    pinging, refreshingCatalog,
    refresh, assign, pingAll, refreshCatalog,
    onSaveKey, onDeleteKey, onSaveProviderSettings, onToggleProvider, onResetProvider,
  } = useModelsData();
  const [showMoreOpen, setShowMoreOpen] = useState(false);

  /** Group profiles by provider, only for providers the user has enabled.
   * The pipeline already sorts each provider's models newest-first
   * (P6-M backend); we just preserve that order. */
  const groups = useMemo(() => {
    const enabledProviderIds = new Set(
      providers.filter((p) => p.enabled).map((p) => p.provider),
    );
    const profilesByProvider = new Map<string, ModelProfile[]>();
    for (const p of profiles) {
      const arr = profilesByProvider.get(p.provider) ?? [];
      arr.push(p);
      profilesByProvider.set(p.provider, arr);
    }
    // Iterate providers in the order the backend returned them so the
    // default-enabled vendors keep their canonical order on the page.
    return providers
      .filter((info) => enabledProviderIds.has(info.provider))
      .map((info) => ({
        info,
        list: profilesByProvider.get(info.provider) ?? [],
      }));
  }, [providers, profiles]);

  if (loading) {
    return (
      <div className="p-6 flex items-center gap-2 text-stone-500 text-sm">
        <Spinner size={14} /> 载入中...
      </div>
    );
  }

  return (
    <div className="p-8 max-w-7xl mx-auto">
      <div className="flex items-center gap-3 mb-4">
        <div>
          <h2 className="text-2xl font-semibold text-stone-800">
            {edition.data?.edition === 'cloud' ? 'LLM 模型' : '模型配置'}
          </h2>
          <p className="mt-1 text-sm text-stone-500">
            {edition.data?.edition === 'cloud'
              ? '选择偏好的对话模型；语音、检索与排序能力由平台统一提供。'
              : '配置模型提供商，并为不同对话角色选择模型。'}
          </p>
        </div>
        <div className="ml-auto flex items-center gap-2">
          <button
            onClick={() => setShowMoreOpen(true)}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm border border-stone-200 text-stone-700 hover:bg-stone-50"
            title="勾选默认隐藏的厂商，使其在主页面显示"
          >
            <Plus size={13} />
            <span>显示更多厂商</span>
          </button>
          <button
            onClick={refreshCatalog}
            disabled={refreshingCatalog}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm border border-stone-200 text-stone-700 hover:bg-stone-50 disabled:opacity-50"
            title="重新调用每家厂商官方 /v1/models 拉取最新模型清单"
          >
            {refreshingCatalog ? <Spinner size={12} /> : <Sparkles size={13} />}
            <span>刷新模型库</span>
          </button>
          <button
            onClick={pingAll}
            disabled={pinging}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm border border-stone-200 text-stone-700 hover:bg-stone-50 disabled:opacity-50"
            title="测试每个模型的可达性"
          >
            {pinging ? <Spinner size={12} /> : <Activity size={13} />}
            <span>Ping 测试</span>
          </button>
          <button
            onClick={() => refresh()}
            className="p-2 rounded-md text-stone-500 hover:bg-stone-100"
            title="重新载入页面缓存（不打厂商 API）"
          >
            <RefreshCw size={14} />
          </button>
        </div>
      </div>

      {/* Compact role assignment bar */}
      <div className="bg-white rounded-xl border border-stone-200 shadow-xs px-4 py-2.5 mb-6 flex items-stretch divide-x divide-stone-200">
        {ROLES.map((r) => {
          const cur = profiles.find((p) => p.id === selection[r]);
          return (
            <div
              key={r}
              className="flex-1 flex items-center gap-3 px-3 first:pl-0 last:pr-0 min-w-0"
              title={cur?.model ?? ''}
            >
              <span className="text-[12px] text-stone-500 shrink-0">{ROLE_DESC[r].label}</span>
              <span className="text-[14px] font-semibold text-stone-800 truncate">
                {cur?.display_name ?? <span className="text-stone-400 font-normal">未选择</span>}
              </span>
              {cur && !cur.ready && <Pill tone="warn">需配置</Pill>}
            </div>
          );
        })}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
        {groups.map((g) => (
          <VendorCard
            key={g.info.provider}
            info={g.info}
            list={g.list}
            selection={selection}
            onAssign={assign}
            pingResults={pingResults}
            apiKeyStatus={apiKeys[g.info.provider]}
            onSaveKey={(k) => onSaveKey(g.info.provider, k)}
            onDeleteKey={() => onDeleteKey(g.info.provider)}
            onSaveSettings={(patch) => onSaveProviderSettings(g.info.provider, patch)}
            onResetSettings={() => onResetProvider(g.info.provider)}
            showAdvancedSettings={edition.data?.show_advanced_model_settings ?? false}
          />
        ))}
      </div>

      {showMoreOpen && (
        <ShowMoreProvidersModal
          providers={providers}
          onToggle={onToggleProvider}
          onClose={() => setShowMoreOpen(false)}
        />
      )}
    </div>
  );
}
