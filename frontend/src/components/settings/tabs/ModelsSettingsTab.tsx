import { useMemo, useState } from 'react';
import {
  Activity,
  Plus,
  Check,
  Globe,
  Trash2,
  Save,
  ArrowLeft,
  ChevronRight,
  ShieldAlert,
  ShieldCheck,
  RefreshCw,
  Zap,
} from 'lucide-react';
import { Spinner } from '@/components/ui/Spinner';
import { useModelsData } from '@/pages/models/useModelsData';
import { VendorAvatar } from '@/pages/models/VendorAvatar';
import { ShowMoreProvidersModal } from '@/pages/models/ShowMoreProvidersModal';
import type { ModelProfile } from '@/types/api';
import type { ProviderInfo } from '@/api/models';
import { toast } from '@/store/uiStore';
import { Btn } from '@/components/ui/Btn';

export function ModelsSettingsTab() {
  const {
    loading,
    profiles,
    providers,
    apiKeys,
    selection,
    pingResults,
    pinging,
    refreshingCatalog,
    assign,
    pingAll,
    refreshCatalog,
    onSaveKey,
    onDeleteKey,
    onSaveProviderSettings,
    onToggleProvider,
  } = useModelsData();

  const [showMoreOpen, setShowMoreOpen] = useState(false);
  // drilldownProvider: null = Level 1 (Directory), non-null = Level 2 (Focused Vendor Panel)
  const [drilldownProvider, setDrilldownProvider] = useState<ProviderInfo | null>(null);

  // Group profiles by provider
  const profilesByProvider = useMemo(() => {
    const map = new Map<string, ModelProfile[]>();
    for (const p of profiles) {
      const arr = map.get(p.provider) ?? [];
      arr.push(p);
      map.set(p.provider, arr);
    }
    return map;
  }, [profiles]);

  const enabledProviders = useMemo(() => providers.filter((p) => p.enabled), [providers]);

  // Find the currently active primary profile
  const activePrimaryProfile = useMemo(
    () => profiles.find((p) => p.id === selection.primary) ?? profiles[0] ?? null,
    [profiles, selection.primary],
  );

  const activeProviderPing = activePrimaryProfile
    ? pingResults[activePrimaryProfile.provider]
    : undefined;

  // Form states for drilldown provider
  const [keyInput, setKeyInput] = useState('');
  const [baseUrlInput, setBaseUrlInput] = useState('');
  const [orgIdInput, setOrgIdInput] = useState('');
  const [savingKey, setSavingKey] = useState(false);
  const [testingPing, setTestingPing] = useState(false);

  const openDrilldown = (provider: ProviderInfo) => {
    setDrilldownProvider(provider);
    setKeyInput('');
    setBaseUrlInput(provider.api_base_override ?? '');
    setOrgIdInput(provider.organization_id ?? '');
  };

  const handleSaveProviderConfig = async () => {
    if (!drilldownProvider) return;
    setSavingKey(true);
    try {
      if (keyInput.trim()) {
        const keyOk = await onSaveKey(drilldownProvider.provider, keyInput.trim());
        if (!keyOk) return;
        setKeyInput('');
      }
      if (
        baseUrlInput.trim() !== (drilldownProvider.api_base_override ?? '') ||
        orgIdInput.trim() !== (drilldownProvider.organization_id ?? '')
      ) {
        await onSaveProviderSettings(drilldownProvider.provider, {
          api_base_override: baseUrlInput.trim() || undefined,
          organization_id: orgIdInput.trim() || undefined,
        });
      }
      toast.success(`${drilldownProvider.display_label} 配置已更新`);
    } catch {
      toast.error('保存失败，请检查格式');
    } finally {
      setSavingKey(false);
    }
  };

  const handleSelectModel = (profile: ModelProfile) => {
    void assign('primary', profile.id);
    toast.success(`默认主模型已设为：${profile.display_name}`);
  };

  if (loading) {
    return (
      <div className="p-12 flex items-center justify-center text-slate-400 gap-2.5 text-sm">
        <Spinner size={20} />
        <span>正在载入模型与算力配置…</span>
      </div>
    );
  }

  // ──────────────────────────────────────────────────────────────────────────
  // LEVEL 2: 厂商专属管理面板 (Provider Detail & Model Selection)
  // ──────────────────────────────────────────────────────────────────────────
  if (drilldownProvider) {
    const isConfigured = Boolean(apiKeys[drilldownProvider.provider]);
    const maskedKey = apiKeys[drilldownProvider.provider]?.masked;
    const vendorProfiles = profilesByProvider.get(drilldownProvider.provider) ?? [];
    const ping = pingResults[drilldownProvider.provider];

    return (
      <div className="space-y-6 text-slate-800 animate-in fade-in duration-150">
        {/* Top Back Navigation Bar */}
        <div className="flex items-center justify-between pb-3 border-b border-slate-100">
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => setDrilldownProvider(null)}
              className="inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-full text-xs font-semibold text-slate-700 hover:text-slate-900 bg-slate-100 hover:bg-slate-200 transition-colors cursor-pointer"
            >
              <ArrowLeft size={14} />
              <span>返回厂商列表</span>
            </button>
            <div className="flex items-center gap-2.5">
              <VendorAvatar info={drilldownProvider} small />
              <h3 className="text-lg font-bold text-slate-900">{drilldownProvider.display_label}</h3>
            </div>
          </div>

          <button
            type="button"
            onClick={async () => {
              setTestingPing(true);
              await pingAll();
              setTestingPing(false);
            }}
            disabled={testingPing || pinging}
            className="inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-full text-xs font-semibold bg-slate-100 hover:bg-slate-200 text-slate-700 transition-all cursor-pointer disabled:opacity-50"
          >
            <Activity size={13} className={testingPing || pinging ? 'animate-pulse text-blue-600' : ''} />
            <span>{testingPing || pinging ? '测速中…' : '测试连接 (Ping)'}</span>
          </button>
        </div>

        {/* Module A: 接口凭据与自定义 URL (Credentials) */}
        <div className="p-6 rounded-3xl bg-slate-50/70 border border-slate-200/90 space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2.5">
              {isConfigured ? (
                <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-emerald-50 border border-emerald-200 text-emerald-700 text-xs font-semibold">
                  <ShieldCheck size={14} />
                  <span>接口已就绪 · API Key 已生效</span>
                </span>
              ) : (
                <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-amber-50 border border-amber-200 text-amber-800 text-xs font-semibold">
                  <ShieldAlert size={14} />
                  <span>尚未配置 API Key</span>
                </span>
              )}

              {ping?.ok && (
                <span className="text-xs font-mono px-2.5 py-0.5 rounded-full bg-emerald-100 text-emerald-800 font-bold">
                  {ping.latency_ms}ms
                </span>
              )}
              {ping && !ping.ok && (
                <span className="text-xs font-mono px-2.5 py-0.5 rounded-full bg-red-100 text-red-700">
                  连通失败
                </span>
              )}
            </div>

            {isConfigured && (
              <button
                type="button"
                onClick={() => {
                  if (window.confirm(`确定删除 ${drilldownProvider.display_label} 的 API Key 吗？`)) {
                    void onDeleteKey(drilldownProvider.provider);
                  }
                }}
                className="inline-flex items-center gap-1 px-3 py-1.5 text-xs text-red-600 hover:bg-red-50 rounded-xl transition-colors cursor-pointer"
              >
                <Trash2 size={13} />
                <span>清除 Key</span>
              </button>
            )}
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 pt-1">
            {/* API Key Input */}
            <div className="space-y-1.5">
              <label className="text-xs font-bold text-slate-700 uppercase tracking-wider flex items-center justify-between">
                <span>API Key</span>
                {isConfigured && (
                  <span className="text-xs font-mono text-slate-400 font-normal">已存: {maskedKey}</span>
                )}
              </label>
              <input
                type="password"
                placeholder={isConfigured ? '输入新 Key 进行覆盖...' : '填入 API Key (如 sk-...)'}
                value={keyInput}
                onChange={(e) => setKeyInput(e.target.value)}
                className="w-full px-3.5 py-2.5 bg-white border border-slate-200/90 rounded-2xl text-sm font-mono text-slate-800 placeholder-slate-400 outline-none focus:border-blue-400 transition-all"
              />
            </div>

            {/* Base URL Input */}
            <div className="space-y-1.5">
              <label className="text-xs font-bold text-slate-700 uppercase tracking-wider flex items-center gap-1.5">
                <Globe size={13} className="text-blue-600" />
                <span>自定义 API 接入点 (Base URL)</span>
              </label>
              <input
                type="text"
                placeholder={drilldownProvider.api_base_override || '官方默认接入点（支持填入反代/兼容地址）'}
                value={baseUrlInput}
                onChange={(e) => setBaseUrlInput(e.target.value)}
                className="w-full px-3.5 py-2.5 bg-white border border-slate-200/90 rounded-2xl text-sm font-mono text-slate-800 placeholder-slate-400 outline-none focus:border-blue-400 transition-all"
              />
            </div>
          </div>

          <div className="flex justify-end pt-1">
            <Btn
              kind="primary"
              size="sm"
              loading={savingKey}
              onClick={handleSaveProviderConfig}
              className="px-6 py-2 rounded-full font-semibold shadow-xs"
            >
              <Save size={14} />
              <span>保存 {drilldownProvider.display_label} 配置</span>
            </Btn>
          </div>
        </div>

        {/* Module B: 该厂商旗下的可用模型清单 (Models Selection) */}
        <div className="space-y-3 pt-2">
          <div className="flex items-center justify-between">
            <div>
              <h4 className="text-sm font-bold text-slate-900">
                选择 {drilldownProvider.display_label} 旗下的主模型
              </h4>
              <p className="text-xs text-slate-500 mt-0.5">
                点击卡片即可将该模型设为全局默认对话与复盘模型。
              </p>
            </div>

            <button
              type="button"
              onClick={() => void refreshCatalog()}
              disabled={refreshingCatalog}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs text-blue-600 hover:text-blue-800 font-semibold cursor-pointer"
            >
              <RefreshCw size={13} className={refreshingCatalog ? 'animate-spin' : ''} />
              <span>{refreshingCatalog ? '拉取中…' : '从官方拉取最新模型'}</span>
            </button>
          </div>

          {!isConfigured ? (
            <div className="p-8 text-center bg-slate-50/50 rounded-3xl border border-dashed border-slate-200 text-slate-500 text-sm space-y-2">
              <p className="font-bold text-slate-700">请先在上方保存 API Key</p>
              <p className="text-xs text-slate-400">
                配置并保存该服务商的 API Key 后，将立即解锁此厂商支持的所有可用模型。
              </p>
            </div>
          ) : vendorProfiles.length === 0 ? (
            <div className="p-8 text-center bg-slate-50/50 rounded-3xl border border-dashed border-slate-200 text-slate-500 text-sm space-y-2">
              <p className="font-bold text-slate-700">未获取到该厂商的模型列表</p>
              <p className="text-xs text-slate-400">
                请点击右上角“从官方拉取最新模型”，或检查 API Key 与 Base URL 是否正确。
              </p>
            </div>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3.5">
              {vendorProfiles.map((profile) => {
                const isSelected = selection.primary === profile.id;

                return (
                  <div
                    key={profile.id}
                    onClick={() => handleSelectModel(profile)}
                    className={`p-4 rounded-3xl border-2 transition-all cursor-pointer flex flex-col justify-between min-h-[88px] ${
                      isSelected
                        ? 'border-blue-600 bg-blue-50/50 shadow-xs ring-2 ring-blue-100'
                        : 'border-slate-200/90 bg-white hover:border-blue-300 hover:bg-slate-50/60'
                    }`}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0 flex-1">
                        <div className="text-sm font-bold text-slate-900 truncate">
                          {profile.display_name}
                        </div>
                        <div className="text-xs font-mono text-slate-400 mt-1 truncate">
                          {profile.model}
                        </div>
                      </div>

                      {isSelected ? (
                        <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full bg-blue-600 text-white text-xs font-bold shrink-0 shadow-2xs">
                          <Check size={12} />
                          <span>当前主模型</span>
                        </span>
                      ) : (
                        <span className="text-xs font-semibold text-blue-600 hover:underline shrink-0 pt-0.5">
                          设为默认
                        </span>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    );
  }

  // ──────────────────────────────────────────────────────────────────────────
  // LEVEL 1: 厂商目录总览 (Provider Directory & Overview)
  // ──────────────────────────────────────────────────────────────────────────
  return (
    <div className="space-y-6 text-slate-800 animate-in fade-in duration-150">
      {/* 1. Dedicated Active Model Status Card (Purely for primary model status) */}
      <div className="p-5 md:p-6 rounded-3xl bg-gradient-to-r from-blue-50/90 via-indigo-50/60 to-purple-50/40 border border-blue-100 shadow-2xs">
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-4 min-w-0">
            <VendorAvatar
              provider={activePrimaryProfile?.provider}
              displayLabel={activePrimaryProfile?.display_name}
              className="w-13 h-13 rounded-2xl shadow-sm ring-2 ring-white"
            />
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <span className="text-xs font-bold text-blue-700 uppercase tracking-wider">
                  当前系统默认主模型
                </span>
                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-emerald-50 border border-emerald-200 text-emerald-700 text-[11px] font-bold">
                  <ShieldCheck size={12} />
                  <span>正常运行</span>
                </span>
              </div>
              <div className="text-lg font-extrabold text-slate-900 tracking-tight mt-1 truncate">
                {activePrimaryProfile?.display_name || '未选择主模型'}
              </div>
              <div className="text-xs text-slate-500 font-mono mt-0.5 truncate">
                服务商: {activePrimaryProfile?.provider || '无'} · 模型标识: {activePrimaryProfile?.model || '无'}
              </div>
            </div>
          </div>

          {activeProviderPing?.ok && (
            <div className="hidden sm:flex flex-col items-end shrink-0">
              <span className="text-[11px] text-slate-400 font-medium">当前网络延迟</span>
              <span className="text-sm font-mono font-bold text-emerald-600 bg-emerald-50 px-2.5 py-0.5 rounded-lg mt-0.5">
                {activeProviderPing.latency_ms}ms
              </span>
            </div>
          )}
        </div>
      </div>

      {/* 2. Provider Directory Section (With Actions in the Section Header) */}
      <div className="space-y-4">
        {/* Section Header with Actions */}
        <div className="flex flex-wrap items-center justify-between gap-3 pt-1">
          <div>
            <h3 className="text-base font-bold text-slate-900 tracking-tight">
              模型服务商 (Provider) 目录
            </h3>
            <p className="text-xs text-slate-500 mt-0.5">
              点击下方厂商卡片进入配置 API Key / 接入点，并从该厂商挑选可用模型。
            </p>
          </div>

          {/* Provider Management Toolbar */}
          <div className="flex items-center gap-2 shrink-0">
            <button
              type="button"
              onClick={() => void pingAll()}
              disabled={pinging}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-semibold bg-white hover:bg-slate-50 text-slate-700 border border-slate-200 shadow-2xs transition-all cursor-pointer disabled:opacity-50"
            >
              <Activity size={13} className={pinging ? 'animate-pulse text-blue-600' : ''} />
              <span>{pinging ? '测速中…' : 'Ping 全部测速'}</span>
            </button>

            <button
              type="button"
              onClick={() => setShowMoreOpen(true)}
              className="inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-full text-xs font-semibold bg-blue-600 hover:bg-blue-700 text-white shadow-xs transition-all cursor-pointer"
            >
              <Plus size={13} />
              <span>启用更多厂商</span>
            </button>
          </div>
        </div>

        {/* Provider Cards Grid */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 items-stretch">
          {enabledProviders.map((provider) => {
            const isConfigured = Boolean(apiKeys[provider.provider]);
            const vendorProfiles = profilesByProvider.get(provider.provider) ?? [];
            const isCurrentActiveVendor = activePrimaryProfile?.provider === provider.provider;
            const ping = pingResults[provider.provider];

            return (
              <div
                key={provider.provider}
                onClick={() => openDrilldown(provider)}
                className={`group p-5 rounded-3xl border transition-all cursor-pointer flex flex-col justify-between min-h-[110px] relative overflow-hidden bg-white shadow-2xs hover:shadow-md ${
                  isCurrentActiveVendor
                    ? 'border-blue-400 ring-2 ring-blue-100/80'
                    : 'border-slate-200/90 hover:border-blue-400'
                }`}
              >
                {/* Top Row: Authentic Logo + Vendor Name + Top Status Badge */}
                <div className="flex items-center justify-between gap-3">
                  <div className="flex items-center gap-3.5 min-w-0">
                    <VendorAvatar info={provider} />
                    <div className="min-w-0">
                      <div className="text-sm font-bold text-slate-900 group-hover:text-blue-600 transition-colors truncate">
                        {provider.display_label}
                      </div>
                      <div className="text-xs text-slate-400 font-mono mt-0.5">
                        {provider.provider}
                      </div>
                    </div>
                  </div>

                  {isCurrentActiveVendor && (
                    <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full bg-blue-600 text-white text-[11px] font-bold shadow-2xs shrink-0">
                      <Zap size={11} />
                      <span>主模型来源</span>
                    </span>
                  )}
                </div>

                {/* Bottom Row: Status Tag + Latency + Action */}
                <div className="mt-3.5 pt-3 border-t border-slate-100 flex items-center justify-between gap-2 text-xs">
                  <div className="flex items-center gap-2 min-w-0">
                    <span
                      className={`font-semibold px-2.5 py-0.5 rounded-full border text-xs shrink-0 ${
                        isConfigured
                          ? 'bg-emerald-50 text-emerald-700 border-emerald-200/80'
                          : 'bg-amber-50 text-amber-700 border-amber-200/80'
                      }`}
                    >
                      {isConfigured ? '● 已就绪' : '○ 未配置 Key'}
                    </span>

                    {isConfigured && vendorProfiles.length > 0 && (
                      <span className="text-slate-400 text-xs hidden md:inline truncate">
                        {vendorProfiles.length} 个模型
                      </span>
                    )}

                    {ping?.ok && (
                      <span className="font-mono text-emerald-600 bg-emerald-50 px-1.5 py-0.5 rounded-md text-[11px] shrink-0">
                        {ping.latency_ms}ms
                      </span>
                    )}
                  </div>

                  <div className="inline-flex items-center gap-1 font-semibold text-slate-400 group-hover:text-blue-600 group-hover:translate-x-0.5 transition-all shrink-0">
                    <span>{isConfigured ? '切换模型' : '进入配置'}</span>
                    <ChevronRight size={14} />
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Show More Providers Modal */}
      {showMoreOpen && (
        <ShowMoreProvidersModal
          providers={providers}
          onClose={() => setShowMoreOpen(false)}
          onToggle={onToggleProvider}
        />
      )}
    </div>
  );
}
