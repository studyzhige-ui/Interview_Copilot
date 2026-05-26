import { useEffect, useMemo, useState } from 'react';
import { Lock, RefreshCw, Activity, Settings2, Trash2, X, Sparkles, Plus, Globe } from 'lucide-react';
import { Pill } from '@/components/ui/Pill';
import { Spinner } from '@/components/ui/Spinner';
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
import type { ModelProfile, ModelRole } from '@/types/api';
import { useIsMounted } from '@/hooks/useIsMounted';

// Brand colors for the vendor avatar tile. Static — these don't come from
// the backend, and they shouldn't be user-configurable. Provider ids
// without a colour fall back to a neutral stone tone, which is fine.
const BRAND_COLORS: Record<string, string> = {
  deepseek:     '#3A6AC1',
  openai:       '#10A37F',
  anthropic:    '#C26A4A',
  gemini:       '#4285F4',
  qwen:         '#7A5BC0',
  moonshot:     '#1E4A78',
  zai:          '#0F62FE',
  xiaomi:       '#FF6900',
  nvidia_nim:   '#76B900',
  mistral:      '#FE5D26',
  cohere:       '#FF7A0E',
  groq:         '#F55036',
  together_ai:  '#0F76FB',
  fireworks_ai: '#F58025',
  perplexity:   '#1C4D5F',
  xai:          '#000000',
  novita:       '#7B61FF',
};

// Visible rows in each vendor card's scrollable model list. 4 rows + the
// "下滑查看全部" hint and bottom fade gradient make the overflow obvious;
// vendors with 10+ models still scroll inside the same card height.
const MODELS_VISIBLE_ROWS = 4;
const MODEL_ROW_HEIGHT_PX = 64;
const MODEL_ROW_GAP_PX = 8;

const ROLE_DESC: Record<ModelRole, { label: string; short: string }> = {
  primary:        { label: '主对话', short: '主' },
  agent:          { label: 'Agent · 工具调用', short: 'A' },
  mock_interview: { label: '模拟面试', short: '模' },
  fast:           { label: '快速 / 改写', short: '快' }, // not shown in UI; kept for type
};
const ROLES: ModelRole[] = ['primary', 'agent', 'mock_interview'];


export function ModelsPage() {
  const [profiles, setProfiles] = useState<ModelProfile[]>([]);
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [selection, setSelection] = useState<Record<ModelRole, string>>({
    primary: '', fast: '', agent: '', mock_interview: '',
  });
  const [loading, setLoading] = useState(true);
  const [pingResults, setPingResults] = useState<Record<string, ModelPingResult>>({});
  const [pinging, setPinging] = useState(false);
  const [refreshingCatalog, setRefreshingCatalog] = useState(false);
  const [apiKeys, setApiKeys] = useState<UserApiKeyStatus>({});
  const [showMoreOpen, setShowMoreOpen] = useState(false);

  const isMounted = useIsMounted();

  /** Refresh both the per-user provider settings AND the catalog. */
  const refresh = async () => {
    setLoading(true);
    try {
      const [catalog, provs] = await Promise.all([
        getModelsCatalog(),
        listProviders(),
      ]);
      if (!isMounted.current) return;
      setProfiles(catalog.profiles);
      setProviders(provs);
      setSelection({
        primary: catalog.selection.primary ?? '',
        fast: catalog.selection.fast ?? '',
        agent: catalog.selection.agent ?? '',
        mock_interview: catalog.selection.mock_interview ?? catalog.selection.fast ?? '',
      });
    } catch {
      if (isMounted.current) toast.error('模型目录加载失败');
    } finally {
      if (isMounted.current) setLoading(false);
    }
  };

  useEffect(() => {
    refresh();
    listMyApiKeys()
      .then((k) => { if (isMounted.current) setApiKeys(k); })
      .catch(() => {});
  }, []);  // eslint-disable-line react-hooks/exhaustive-deps

  const onSaveKey = async (provider: string, key: string) => {
    try {
      const { masked } = await saveMyApiKey(provider, key);
      setApiKeys((k) => ({ ...k, [provider]: { set: true, masked } }));
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
      setApiKeys((k) => {
        const { [provider]: _, ...rest } = k;
        return rest;
      });
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
      setProviders((cur) => cur.map((p) => (p.provider === provider ? updated : p)));
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
    // Optimistic update so the picker feels snappy.
    setProviders((cur) => cur.map((p) => (p.provider === provider ? { ...p, enabled } : p)));
    try {
      await updateProviderSettings(provider, { enabled });
    } catch {
      // Rollback on failure.
      setProviders((cur) => cur.map((p) => (p.provider === provider ? { ...p, enabled: !enabled } : p)));
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

  const pingAll = async () => {
    setPinging(true);
    try {
      const results = await pingAllModels();
      if (!isMounted.current) return;
      const map: Record<string, ModelPingResult> = {};
      for (const r of results) map[r.profile_id] = r;
      setPingResults(map);
      const reachable = results.filter((r) => r.ok).length;
      toast.success(`已 ping ${results.length} 个模型，${reachable} 个可达`);
    } catch {
      if (isMounted.current) toast.error('Ping 失败');
    } finally {
      if (isMounted.current) setPinging(false);
    }
  };

  const refreshCatalog = async () => {
    setRefreshingCatalog(true);
    try {
      const result = await refreshModelCatalog();
      await refresh();
      if (!isMounted.current) return;
      toast.success(
        `已从各厂商官方 /v1/models 拉取 ${result.profiles_total} 个模型 ` +
        `（${result.providers_refreshed} 家厂商）`,
      );
    } catch (err) {
      if (!isMounted.current) return;
      const detail = (err as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      toast.error(detail ?? '刷新模型库失败');
    } finally {
      if (isMounted.current) setRefreshingCatalog(false);
    }
  };

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

  const assign = async (role: ModelRole, profileId: string) => {
    const prev = selection[role];
    if (prev === profileId) return;
    setSelection((s) => ({ ...s, [role]: profileId }));
    try {
      await updateModelsRuntime({ [role]: profileId });
      toast.success(`${ROLE_DESC[role].label}：${profileId}`);
    } catch (err) {
      setSelection((s) => ({ ...s, [role]: prev }));
      const detail = (err as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      toast.error(detail ?? '保存失败');
    }
  };

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
        <h2 className="text-2xl font-semibold text-stone-800">模型配置</h2>
        <span className="text-sm text-stone-500">点卡片上的角色标签即可切换</span>
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
            onClick={refresh}
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


// ── VendorCard ──────────────────────────────────────────────────────────


function VendorCard({
  info,
  list,
  selection,
  onAssign,
  pingResults,
  apiKeyStatus,
  onSaveKey,
  onDeleteKey,
  onSaveSettings,
  onResetSettings,
}: {
  info: ProviderInfo;
  list: ModelProfile[];
  selection: Record<ModelRole, string>;
  onAssign: (role: ModelRole, id: string) => void;
  pingResults: Record<string, ModelPingResult>;
  apiKeyStatus?: { set: boolean; masked: string };
  onSaveKey: (key: string) => Promise<boolean>;
  onDeleteKey: () => void;
  onSaveSettings: (patch: { api_base_override?: string; organization_id?: string }) => Promise<boolean>;
  onResetSettings: () => void;
}) {
  const anyReady = list.some((p) => p.ready);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const userKeySet = info.has_user_api_key || !!apiKeyStatus?.set;

  const modelsAreaHeight =
    MODELS_VISIBLE_ROWS * MODEL_ROW_HEIGHT_PX + (MODELS_VISIBLE_ROWS - 1) * MODEL_ROW_GAP_PX;

  return (
    <div className="bg-white rounded-xl p-3.5 border border-stone-200 shadow-sm flex flex-col">
      <div className="flex items-center justify-between mb-2.5">
        <div className="flex items-center gap-2.5 min-w-0">
          <VendorAvatar info={info} />
          <div className="min-w-0">
            <div className="text-[15px] font-semibold text-stone-800 truncate leading-tight">
              {info.display_label}
            </div>
            <div className="text-[10px] text-stone-400 truncate">
              {list.length} 个模型
              {list.length > MODELS_VISIBLE_ROWS && (
                <span className="ml-1 text-stone-500">· 下滑查看全部</span>
              )}
              {info.api_base_override && (
                <span className="ml-1 text-primary-600" title={info.api_base_override}>
                  · 自定义网关
                </span>
              )}
            </div>
          </div>
        </div>
        {anyReady ? <Pill tone="success">已配置</Pill> : <Pill tone="warn">未配置</Pill>}
      </div>

      {/* Scrollable model list. Models are sorted newest-first by the
        * backend pipeline; we just preserve that order. */}
      <div className="relative mb-2" style={{ height: modelsAreaHeight }}>
        <div
          className="overflow-y-auto pr-1 flex flex-col h-full"
          style={{ gap: MODEL_ROW_GAP_PX }}
        >
          {list.length === 0 ? (
            <div className="text-xs text-stone-400 text-center py-6 leading-relaxed">
              暂无可用模型<br />
              <span className="text-[10px]">
                （配置 API Key 后点"刷新模型库"，即可从该厂商官方拉取）
              </span>
            </div>
          ) : (
            list.map((p) => (
              <ModelRow
                key={p.id}
                profile={p}
                selectedRoles={ROLES.filter((r) => selection[r] === p.id)}
                onAssign={(role) => onAssign(role, p.id)}
                ping={pingResults[p.id]}
              />
            ))
          )}
        </div>
        {list.length > MODELS_VISIBLE_ROWS && (
          <div
            className="pointer-events-none absolute inset-x-0 bottom-0 h-8 rounded-b-xl"
            style={{
              background:
                'linear-gradient(to bottom, rgba(255,255,255,0) 0%, rgba(255,255,255,0.92) 80%, #ffffff 100%)',
            }}
          />
        )}
      </div>

      {/* API Key + advanced settings row */}
      <div className="pt-2 border-t border-stone-100">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5 min-w-0">
            <Lock size={13} className={userKeySet || anyReady ? 'text-success-600' : 'text-stone-400'} />
            {userKeySet || anyReady ? (
              <span className="text-xs text-success-700 truncate font-medium">已配置</span>
            ) : (
              <span className="text-xs text-warning-700 truncate font-medium">未配置</span>
            )}
          </div>
          <div className="flex items-center gap-1 shrink-0">
            <button
              type="button"
              onClick={() => setSettingsOpen(true)}
              className={[
                'inline-flex items-center gap-1 text-xs px-2.5 py-1 rounded-md font-medium transition-colors',
                userKeySet
                  ? 'text-stone-600 hover:bg-stone-100 border border-stone-200'
                  : 'text-stone-800 bg-white hover:bg-stone-50 border border-stone-300 shadow-xs',
              ].join(' ')}
            >
              <Settings2 size={12} />
              {userKeySet ? '设置' : '配置'}
            </button>
          </div>
        </div>
      </div>

      {settingsOpen && (
        <VendorSettingsModal
          info={info}
          apiKeyMasked={apiKeyStatus?.masked}
          onClose={() => setSettingsOpen(false)}
          onSaveKey={onSaveKey}
          onDeleteKey={onDeleteKey}
          onSaveSettings={onSaveSettings}
          onResetSettings={onResetSettings}
        />
      )}
    </div>
  );
}


// ── VendorSettingsModal — P6-M ──────────────────────────────────────────


function VendorSettingsModal({
  info,
  apiKeyMasked,
  onClose,
  onSaveKey,
  onDeleteKey,
  onSaveSettings,
  onResetSettings,
}: {
  info: ProviderInfo;
  apiKeyMasked?: string;
  onClose: () => void;
  onSaveKey: (key: string) => Promise<boolean>;
  onDeleteKey: () => void;
  onSaveSettings: (patch: { api_base_override?: string; organization_id?: string }) => Promise<boolean>;
  onResetSettings: () => void;
}) {
  const [keyDraft, setKeyDraft] = useState('');
  const [apiBase, setApiBase] = useState(info.api_base_override ?? '');
  const [orgId, setOrgId] = useState(info.organization_id ?? '');
  const [saving, setSaving] = useState(false);
  const userKeySet = info.has_user_api_key;

  const handleSaveAll = async () => {
    setSaving(true);
    try {
      // 1) Save the API key if the user typed a new one.
      if (keyDraft.trim()) {
        const ok = await onSaveKey(keyDraft.trim());
        if (!ok) return;
      }
      // 2) Save api_base / org overrides. Pass "" so the backend
      //    treats an empty input as "clear the override" instead of
      //    "don't touch" (which is what undefined would mean).
      const patch: { api_base_override?: string; organization_id?: string } = {};
      const apiBaseTrimmed = apiBase.trim();
      const orgIdTrimmed = orgId.trim();
      if (apiBaseTrimmed !== (info.api_base_override ?? '')) {
        patch.api_base_override = apiBaseTrimmed;
      }
      if (orgIdTrimmed !== (info.organization_id ?? '')) {
        patch.organization_id = orgIdTrimmed;
      }
      if (Object.keys(patch).length > 0) {
        const ok = await onSaveSettings(patch);
        if (!ok) return;
      }
      onClose();
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-2xl shadow-xl w-full max-w-md mx-4 max-h-[90vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-5 py-4 border-b border-stone-100">
          <div className="flex items-center gap-3">
            <VendorAvatar info={info} small />
            <div>
              <div className="text-[15px] font-semibold text-stone-800">{info.display_label} 设置</div>
              <div className="text-[11px] text-stone-400 truncate max-w-[280px]">{info.api_base}</div>
            </div>
          </div>
          <button onClick={onClose} className="p-1 text-stone-400 hover:text-stone-600 rounded">
            <X size={16} />
          </button>
        </div>

        <div className="p-5 space-y-5">
          {/* API Key */}
          <div>
            <label className="text-xs font-semibold text-stone-700 mb-1.5 block">API Key</label>
            <div className="relative">
              <Lock size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-stone-400" />
              <input
                type="password"
                value={keyDraft}
                onChange={(e) => setKeyDraft(e.target.value)}
                placeholder={
                  userKeySet
                    ? `已配置 ${apiKeyMasked ?? ''}（输入新值以替换）`
                    : `粘贴 ${info.api_key_env} 的值`
                }
                className="w-full pl-8 pr-3 py-2 bg-white border border-stone-300 rounded-md text-sm text-stone-800 outline-none focus:border-primary-400 focus:ring-2 focus:ring-primary-100"
              />
            </div>
            {userKeySet && (
              <button
                type="button"
                onClick={async () => { await onDeleteKey(); }}
                className="mt-1.5 inline-flex items-center gap-1 text-[11px] text-danger-600 hover:text-danger-700"
              >
                <Trash2 size={11} /> 删除已保存的密钥
              </button>
            )}
            <div className="text-[10px] text-stone-400 mt-1.5 leading-relaxed">
              密钥使用 Fernet 对称加密入库，不在 GET 接口返回明文。
            </div>
          </div>

          {/* Advanced: api_base override + organization_id */}
          <div className="border-t border-stone-100 pt-4">
            <div className="flex items-center gap-1.5 mb-2">
              <Globe size={13} className="text-stone-500" />
              <span className="text-xs font-semibold text-stone-700">高级（订阅 / 自建网关）</span>
            </div>

            <label className="text-[11px] font-semibold text-stone-600 mb-1 block">
              API Base 覆盖
            </label>
            <input
              type="url"
              value={apiBase}
              onChange={(e) => setApiBase(e.target.value)}
              placeholder={`默认 ${info.api_base}`}
              className="w-full px-3 py-2 bg-white border border-stone-300 rounded-md text-sm text-stone-800 outline-none focus:border-primary-400 focus:ring-2 focus:ring-primary-100 mb-1"
            />
            <div className="text-[10px] text-stone-400 leading-relaxed mb-3">
              必须 HTTPS；内网 / 私网段会被拒绝。留空使用 vendor 默认。
            </div>

            <label className="text-[11px] font-semibold text-stone-600 mb-1 block">
              Organization / Project ID（可选）
            </label>
            <input
              type="text"
              value={orgId}
              onChange={(e) => setOrgId(e.target.value)}
              placeholder="org-xxxxxx / 留空"
              maxLength={100}
              className="w-full px-3 py-2 bg-white border border-stone-300 rounded-md text-sm text-stone-800 outline-none focus:border-primary-400 focus:ring-2 focus:ring-primary-100"
            />
          </div>

          {/* Footer actions */}
          <div className="flex items-center justify-between border-t border-stone-100 pt-4">
            {info.has_user_row ? (
              <button
                type="button"
                onClick={async () => { await onResetSettings(); onClose(); }}
                className="text-[11px] text-stone-500 hover:text-danger-600"
                title="清除 api_base / organization 的覆盖，恢复默认值。不删除 API Key。"
              >
                重置为默认
              </button>
            ) : (
              <span />
            )}
            <div className="flex gap-1.5">
              <button
                type="button"
                onClick={onClose}
                className="text-sm px-4 py-2 rounded-md border border-stone-300 text-stone-600 hover:bg-stone-50"
              >
                取消
              </button>
              <button
                type="button"
                onClick={handleSaveAll}
                disabled={saving}
                className="text-sm px-4 py-2 rounded-md bg-primary-500 text-white hover:bg-primary-600 disabled:opacity-40 font-medium inline-flex items-center gap-1.5"
              >
                {saving ? <Spinner size={11} /> : '保存'}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}


// ── ShowMoreProvidersModal — P6-M ───────────────────────────────────────


function ShowMoreProvidersModal({
  providers,
  onToggle,
  onClose,
}: {
  providers: ProviderInfo[];
  onToggle: (provider: string, enabled: boolean) => void;
  onClose: () => void;
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-2xl shadow-xl w-full max-w-lg mx-4 max-h-[85vh] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-5 py-4 border-b border-stone-100 shrink-0">
          <div>
            <div className="text-[15px] font-semibold text-stone-800">显示更多厂商</div>
            <div className="text-[11px] text-stone-400 mt-0.5">
              勾选后即在主页面显示对应卡片；可随时取消勾选
            </div>
          </div>
          <button onClick={onClose} className="p-1 text-stone-400 hover:text-stone-600 rounded">
            <X size={16} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-2">
          {providers.map((info) => (
            <label
              key={info.provider}
              className="flex items-center gap-3 px-3 py-2.5 rounded-lg hover:bg-stone-50 cursor-pointer border border-stone-100"
            >
              <input
                type="checkbox"
                checked={info.enabled}
                onChange={(e) => onToggle(info.provider, e.target.checked)}
                className="w-4 h-4 accent-primary-500"
              />
              <VendorAvatar info={info} small />
              <div className="flex-1 min-w-0">
                <div className="text-sm font-semibold text-stone-800 truncate">
                  {info.display_label}
                </div>
                <div className="text-[10px] text-stone-400 truncate">{info.provider}</div>
              </div>
              {info.has_user_api_key && <Pill tone="success">已配置</Pill>}
            </label>
          ))}
        </div>

        <div className="border-t border-stone-100 px-5 py-3 shrink-0 flex justify-end">
          <button
            type="button"
            onClick={onClose}
            className="text-sm px-4 py-2 rounded-md bg-primary-500 text-white hover:bg-primary-600 font-medium"
          >
            完成
          </button>
        </div>
      </div>
    </div>
  );
}


// ── VendorAvatar + ModelRow (unchanged from P6-H, accept ProviderInfo) ──


function VendorAvatar({ info, small = false }: { info: ProviderInfo; small?: boolean }) {
  const [failed, setFailed] = useState(false);
  const hasIcon = !!info.icon_slug && !failed;
  const size = small ? 'w-7 h-7' : 'w-9 h-9';
  const iconPx = small ? 14 : 18;
  const brand = BRAND_COLORS[info.provider] ?? '#71717A';
  return (
    <div
      className={`${size} rounded-lg flex items-center justify-center shrink-0 overflow-hidden`}
      style={{ background: brand }}
      aria-label={info.display_label}
    >
      {hasIcon ? (
        <img
          src={`https://cdn.jsdelivr.net/npm/simple-icons@latest/icons/${info.icon_slug}.svg`}
          alt=""
          width={iconPx}
          height={iconPx}
          loading="lazy"
          onError={() => setFailed(true)}
          style={{ width: iconPx, height: iconPx, filter: 'brightness(0) invert(1)' }}
        />
      ) : (
        <span className={`${small ? 'text-xs' : 'text-sm'} font-bold text-white`}>
          {info.display_label[0]}
        </span>
      )}
    </div>
  );
}


function ModelRow({
  profile,
  selectedRoles,
  onAssign,
  ping,
}: {
  profile: ModelProfile;
  selectedRoles: ModelRole[];
  onAssign: (role: ModelRole) => void;
  ping?: ModelPingResult;
}) {
  const isRoleAvailable = (role: ModelRole) =>
    role === 'agent' ? profile.supports_function_calling : true;

  const dotColor = ping
    ? ping.ok
      ? 'bg-success-500'
      : 'bg-danger-500'
    : profile.ready
    ? 'bg-success-500'
    : 'bg-stone-300';
  const dotTitle = ping
    ? ping.ok
      ? `可达 · ${ping.latency_ms}ms`
      : `不可达：${ping.error ?? '未知'}`
    : profile.ready
    ? '已配置 · 可用'
    : `未配置 ${profile.api_key_env}`;

  return (
    <div
      className={[
        'rounded-xl border px-2 py-1 transition-colors shrink-0 flex flex-col items-center justify-center gap-1 relative',
        selectedRoles.length > 0
          ? 'border-primary-300 bg-primary-50'
          : 'border-stone-200 bg-white hover:bg-stone-50',
      ].join(' ')}
      style={{ height: MODEL_ROW_HEIGHT_PX }}
      title={profile.model}
    >
      <span
        className={`absolute top-1.5 right-1.5 inline-block w-2 h-2 rounded-full ${dotColor}`}
        title={dotTitle}
      />
      {ping && ping.ok && (
        <span className="absolute top-1 left-1.5 text-[10px] text-stone-400 font-mono leading-none">
          {ping.latency_ms}ms
        </span>
      )}

      <div
        className="font-semibold text-stone-800 leading-tight text-center px-5 w-full"
        style={{
          fontSize:
            profile.display_name.length <= 14
              ? 15
              : profile.display_name.length <= 20
              ? 13
              : profile.display_name.length <= 26
              ? 12
              : 11,
          whiteSpace: 'nowrap',
        }}
      >
        {profile.display_name}
      </div>

      <div
        className="inline-flex items-center gap-1 p-[3px] rounded-full w-full max-w-[230px]"
        style={{
          background:
            'linear-gradient(120deg, rgba(174,201,250,0.55) 0%, rgba(212,189,240,0.55) 45%, rgba(248,206,200,0.5) 100%)',
          border: '1px solid rgba(255,255,255,0.7)',
          boxShadow:
            '0 4px 14px rgba(80,80,140,0.10), inset 0 1px 1.5px rgba(255,255,255,0.85), inset 0 -1px 1.5px rgba(80,80,140,0.05)',
          backdropFilter: 'blur(20px) saturate(180%)',
          WebkitBackdropFilter: 'blur(20px) saturate(180%)',
        }}
      >
        {ROLES.map((r) => {
          const active = selectedRoles.includes(r);
          const available = isRoleAvailable(r) && profile.ready;
          return (
            <button
              key={r}
              onClick={() => available && onAssign(r)}
              disabled={!available}
              title={
                !profile.ready
                  ? `需配置 ${profile.api_key_env}`
                  : r === 'agent' && !profile.supports_function_calling
                  ? '该模型不支持函数调用'
                  : ROLE_DESC[r].label
              }
              className={[
                'flex-1 px-3 py-1 rounded-full text-[12px] font-semibold transition-all',
                active
                  ? 'text-stone-900'
                  : available
                  ? 'text-stone-700 hover:text-stone-900'
                  : 'text-stone-400 cursor-not-allowed',
              ].join(' ')}
              style={
                active
                  ? {
                      background: 'rgba(255,255,255,0.92)',
                      backdropFilter: 'blur(10px) saturate(180%)',
                      WebkitBackdropFilter: 'blur(10px) saturate(180%)',
                      boxShadow:
                        '0 3px 10px rgba(50,50,93,0.22), inset 0 1px 0 rgba(255,255,255,0.95), 0 0 0 1px rgba(50,50,93,0.08)',
                    }
                  : undefined
              }
            >
              {ROLE_DESC[r].short}
            </button>
          );
        })}
      </div>
    </div>
  );
}
