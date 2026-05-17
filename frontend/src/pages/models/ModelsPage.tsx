import { useEffect, useMemo, useState } from 'react';
import { Lock, RefreshCw, Activity, Settings2, Trash2, X, Sparkles } from 'lucide-react';
import { Pill } from '@/components/ui/Pill';
import { Spinner } from '@/components/ui/Spinner';
import { toast } from '@/store/uiStore';
import {
  deleteMyApiKey,
  getModelsCatalog,
  listMyApiKeys,
  pingAllModels,
  refreshModelCatalog,
  saveMyApiKey,
  updateModelsRuntime,
  type ModelPingResult,
  type UserApiKeyStatus,
} from '@/api/models';
import type { ModelProfile, ModelRole } from '@/types/api';

interface VendorInfo {
  key: string;
  label: string;
  brand: string;
  // Slug on https://simpleicons.org for the official brand SVG. Loaded from
  // their CDN as a white-on-brand-color glyph; falls back to the letter
  // initial on network error (see <VendorAvatar/>).
  iconSlug?: string;
}

const VENDORS: VendorInfo[] = [
  { key: 'deepseek',  label: 'DeepSeek',          brand: '#3A6AC1', iconSlug: 'deepseek' },
  { key: 'openai',    label: 'OpenAI',            brand: '#10A37F', iconSlug: 'openai' },
  { key: 'anthropic', label: 'Anthropic',         brand: '#C26A4A', iconSlug: 'anthropic' },
  { key: 'google',    label: 'Google Gemini',     brand: '#4285F4', iconSlug: 'googlegemini' },
  { key: 'qwen',      label: '通义 Qwen',          brand: '#7A5BC0', iconSlug: 'alibabacloud' },
  { key: 'moonshot',  label: 'Moonshot Kimi',     brand: '#1E4A78' },
  { key: 'zhipu',     label: '智谱 GLM',           brand: '#0F62FE' },
  { key: 'xiaomi',    label: '小米 MiMo',          brand: '#FF6900', iconSlug: 'xiaomi' },
  { key: 'nvidia',    label: 'NVIDIA',            brand: '#76B900', iconSlug: 'nvidia' },
];

// Visible rows in each vendor card's scrollable model list. Cards stay the
// same height regardless of how many models a vendor has — overflow scrolls.
// Each row renders: 1 line of centered display_name + 1 row of centered
// glass role tabs. The row is intentionally tight (no internal padding
// breathing room); whitespace lives between rows, not inside them.
const MODELS_VISIBLE_ROWS = 2;
const MODEL_ROW_HEIGHT_PX = 64;
const MODEL_ROW_GAP_PX = 8;

const ROLE_DESC: Record<ModelRole, { label: string; short: string }> = {
  primary:        { label: '主对话', short: '主' },
  agent:          { label: 'Agent · 工具调用', short: 'A' },
  mock_interview: { label: '模拟面试', short: '模' },
  fast:           { label: '快速 / 改写', short: '快' }, // not shown in UI; kept for type
};
// Only these three are user-configurable. 'fast' is internal back-compat.
const ROLES: ModelRole[] = ['primary', 'agent', 'mock_interview'];

export function ModelsPage() {
  const [profiles, setProfiles] = useState<ModelProfile[]>([]);
  const [selection, setSelection] = useState<Record<ModelRole, string>>({
    primary: '', fast: '', agent: '', mock_interview: '',
  });
  const [loading, setLoading] = useState(true);
  const [pingResults, setPingResults] = useState<Record<string, ModelPingResult>>({});
  const [pinging, setPinging] = useState(false);
  const [refreshingCatalog, setRefreshingCatalog] = useState(false);
  const [apiKeys, setApiKeys] = useState<UserApiKeyStatus>({});

  const refresh = async () => {
    setLoading(true);
    try {
      const c = await getModelsCatalog();
      setProfiles(c.profiles);
      setSelection({
        primary: c.selection.primary ?? '',
        fast: c.selection.fast ?? '',
        agent: c.selection.agent ?? '',
        mock_interview: c.selection.mock_interview ?? c.selection.fast ?? '',
      });
    } catch {
      toast.error('模型目录加载失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh();
    listMyApiKeys().then(setApiKeys).catch(() => {});
  }, []);

  const onSaveKey = async (provider: string, key: string) => {
    try {
      const { masked } = await saveMyApiKey(provider, key);
      setApiKeys((k) => ({ ...k, [provider]: { set: true, masked } }));
      // Refresh catalog so `ready` flags update for the newly-configured provider
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

  const pingAll = async () => {
    setPinging(true);
    try {
      const results = await pingAllModels();
      const map: Record<string, ModelPingResult> = {};
      for (const r of results) map[r.profile_id] = r;
      setPingResults(map);
      const reachable = results.filter((r) => r.ok).length;
      toast.success(`已 ping ${results.length} 个模型，${reachable} 个可达`);
    } catch {
      toast.error('Ping 失败');
    } finally {
      setPinging(false);
    }
  };

  const refreshCatalog = async () => {
    setRefreshingCatalog(true);
    try {
      const result = await refreshModelCatalog();
      // The refresh call already returned the freshly-discovered list, but
      // pull through the standard catalog endpoint too so this page's local
      // state path matches what /catalog returns elsewhere.
      await refresh();
      toast.success(
        `已刷新 ${result.profiles_total} 个模型，` +
        `其中 ${result.profiles_auto_discovered} 个自动发现`,
      );
    } catch (err) {
      const detail = (err as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      toast.error(detail ?? '刷新模型库失败');
    } finally {
      setRefreshingCatalog(false);
    }
  };

  const groups = useMemo(() => {
    const m = new Map<string, ModelProfile[]>();
    for (const p of profiles) {
      const arr = m.get(p.provider) ?? [];
      arr.push(p);
      m.set(p.provider, arr);
    }
    return VENDORS
      .map((v) => ({ vendor: v, list: m.get(v.key) ?? [] }))
      .filter((g) => g.list.length > 0);
  }, [profiles]);

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
            onClick={refreshCatalog}
            disabled={refreshingCatalog}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm border border-stone-200 text-stone-700 hover:bg-stone-50 disabled:opacity-50"
            title="重新拉取每家厂商 /v1/models 列表（24h 缓存，新模型自动出现在下拉）"
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

      {/* Compact role assignment bar — single row, all three roles inline */}
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
              {cur && !cur.ready && (
                <Pill tone="warn">需配置</Pill>
              )}
            </div>
          );
        })}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
        {groups.map((g) => (
          <VendorCard
            key={g.vendor.key}
            vendor={g.vendor}
            list={g.list}
            selection={selection}
            onAssign={assign}
            pingResults={pingResults}
            apiKeyStatus={apiKeys[g.vendor.key]}
            onSaveKey={(k) => onSaveKey(g.vendor.key, k)}
            onDeleteKey={() => onDeleteKey(g.vendor.key)}
          />
        ))}
      </div>
    </div>
  );
}

function VendorCard({
  vendor,
  list,
  selection,
  onAssign,
  pingResults,
  apiKeyStatus,
  onSaveKey,
  onDeleteKey,
}: {
  vendor: VendorInfo;
  list: ModelProfile[];
  selection: Record<ModelRole, string>;
  onAssign: (role: ModelRole, id: string) => void;
  pingResults: Record<string, ModelPingResult>;
  apiKeyStatus?: { set: boolean; masked: string };
  onSaveKey: (key: string) => Promise<boolean>;
  onDeleteKey: () => void;
}) {
  const anyReady = list.some((p) => p.ready);
  const [keyEditorOpen, setKeyEditorOpen] = useState(false);
  const [keyDraft, setKeyDraft] = useState('');
  const [saving, setSaving] = useState(false);
  const envName = list[0]?.api_key_env ?? '';
  const userKeySet = !!apiKeyStatus?.set;
  // Flat rectangular card: wide aspect ratio, bigger fonts, scrollable model
  // list (no pagination). The model area always shows ~2 rows by default.
  const modelsAreaHeight =
    MODELS_VISIBLE_ROWS * MODEL_ROW_HEIGHT_PX + (MODELS_VISIBLE_ROWS - 1) * MODEL_ROW_GAP_PX;

  return (
    <div className="bg-white rounded-xl p-3.5 border border-stone-200 shadow-sm flex flex-col">
      <div className="flex items-center justify-between mb-2.5">
        <div className="flex items-center gap-2.5 min-w-0">
          <VendorAvatar vendor={vendor} />
          <div className="min-w-0">
            <div className="text-[15px] font-semibold text-stone-800 truncate leading-tight">{vendor.label}</div>
            <div className="text-[10px] text-stone-400 truncate">{list.length} 个模型</div>
          </div>
        </div>
        {anyReady
          ? <Pill tone="success">已配置</Pill>
          : <Pill tone="warn">未配置</Pill>}
      </div>

      {/* Scrollable model list — fixed visible area, content scrolls inside */}
      <div
        className="overflow-y-auto pr-1 mb-2 flex flex-col"
        style={{ height: modelsAreaHeight, gap: MODEL_ROW_GAP_PX }}
      >
        {list.map((p) => (
          <ModelRow
            key={p.id}
            profile={p}
            selectedRoles={ROLES.filter((r) => selection[r] === p.id)}
            onAssign={(role) => onAssign(role, p.id)}
            ping={pingResults[p.id]}
          />
        ))}
      </div>

      {/* API Key — collapsed by default. The plaintext is NEVER displayed
        * back. Status badge shows "✓ 已配置 sk-…abcd" or env var hint. */}
      <div className="pt-2 border-t border-stone-100">
        {!keyEditorOpen ? (
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
              {userKeySet && (
                <button
                  type="button"
                  onClick={onDeleteKey}
                  className="p-1 text-stone-400 hover:text-danger-500 rounded"
                  title="删除已保存的密钥"
                >
                  <Trash2 size={13} />
                </button>
              )}
              <button
                type="button"
                onClick={() => { setKeyDraft(''); setKeyEditorOpen(true); }}
                className={[
                  'inline-flex items-center gap-1 text-xs px-2.5 py-1 rounded-md font-medium transition-colors',
                  userKeySet
                    ? 'text-stone-600 hover:bg-stone-100 border border-stone-200'
                    : 'text-stone-800 bg-white hover:bg-stone-50 border border-stone-300 shadow-xs',
                ].join(' ')}
              >
                <Settings2 size={12} />
                {userKeySet ? '更换' : '配置 API Key'}
              </button>
            </div>
          </div>
        ) : (
          <div>
            <div className="flex items-center justify-between mb-1.5">
              <div className="text-xs font-semibold text-stone-700">输入 {vendor.label} API Key</div>
              <button
                type="button"
                onClick={() => { setKeyEditorOpen(false); setKeyDraft(''); }}
                className="p-1 text-stone-400 hover:text-stone-600 rounded"
                title="取消"
              >
                <X size={13} />
              </button>
            </div>
            <div className="relative">
              <Lock size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-stone-400" />
              <input
                type="password"
                autoFocus
                value={keyDraft}
                onChange={(e) => setKeyDraft(e.target.value)}
                placeholder={`粘贴 ${envName} 的值，加密入库`}
                className="w-full pl-8 pr-3 py-2 bg-white border border-stone-300 rounded-md text-sm text-stone-800 outline-none focus:border-primary-400 focus:ring-2 focus:ring-primary-100"
                onKeyDown={async (e) => {
                  if (e.key === 'Enter' && keyDraft.trim() && !saving) {
                    setSaving(true);
                    const ok = await onSaveKey(keyDraft.trim());
                    setSaving(false);
                    if (ok) { setKeyDraft(''); setKeyEditorOpen(false); }
                  }
                }}
              />
            </div>
            <div className="flex items-center gap-1.5 mt-2">
              <button
                type="button"
                onClick={async () => {
                  if (!keyDraft.trim()) { toast.warn('请先输入 API Key'); return; }
                  setSaving(true);
                  const ok = await onSaveKey(keyDraft.trim());
                  setSaving(false);
                  if (ok) { setKeyDraft(''); setKeyEditorOpen(false); }
                }}
                disabled={!keyDraft.trim() || saving}
                className="flex-1 inline-flex items-center justify-center gap-1.5 text-xs px-3 py-1.5 rounded-md bg-primary-500 text-white hover:bg-primary-600 disabled:opacity-40 font-medium"
              >
                {saving ? <Spinner size={11} /> : '加密保存'}
              </button>
              <button
                type="button"
                onClick={() => { setKeyEditorOpen(false); setKeyDraft(''); }}
                className="text-xs px-3 py-1.5 rounded-md border border-stone-300 text-stone-600 hover:bg-stone-50"
              >
                取消
              </button>
            </div>
            <div className="text-[10px] text-stone-400 mt-1.5 leading-relaxed">
              密钥使用 Fernet 对称加密入库，不在 GET 接口返回明文，前端也不显示。
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function VendorAvatar({ vendor }: { vendor: VendorInfo }) {
  // Brand-color tile + monochrome white glyph fetched from jsdelivr's mirror
  // of simple-icons (more reliable in CN than cdn.simpleicons.org). The SVG
  // ships black; CSS filter recolors it to white. Falls back to letter on
  // 404 / network failure.
  const [failed, setFailed] = useState(false);
  const hasIcon = !!vendor.iconSlug && !failed;
  return (
    <div
      className="w-9 h-9 rounded-lg flex items-center justify-center shrink-0 overflow-hidden"
      style={{ background: vendor.brand }}
      aria-label={vendor.label}
    >
      {hasIcon ? (
        <img
          src={`https://cdn.jsdelivr.net/npm/simple-icons@latest/icons/${vendor.iconSlug}.svg`}
          alt=""
          width={18}
          height={18}
          loading="lazy"
          onError={() => setFailed(true)}
          style={{
            width: 18,
            height: 18,
            // Recolor the black source SVG → white so it sits cleanly on the
            // brand-color tile.
            filter: 'brightness(0) invert(1)',
          }}
        />
      ) : (
        <span className="text-sm font-bold text-white">{vendor.label[0]}</span>
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
  // Agent role requires function-calling support
  const isRoleAvailable = (role: ModelRole) =>
    role === 'agent' ? profile.supports_function_calling : true;

  // Ping status takes priority over static readiness. Without a ping result
  // we color by configured-vs-not (green / gray) so the user can immediately
  // see which models are usable.
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
      {/* status dot + optional latency, top-right corner */}
      <span
        className={`absolute top-1.5 right-1.5 inline-block w-2 h-2 rounded-full ${dotColor}`}
        title={dotTitle}
      />
      {ping && ping.ok && (
        <span className="absolute top-1 left-1.5 text-[10px] text-stone-400 font-mono leading-none">
          {ping.latency_ms}ms
        </span>
      )}

      {/* Model name — centered, font shrinks for long names so the full
        * label always fits (no ellipsis cut). */}
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

      {/* Glass role tabs — soft iridescent gradient, real backdrop blur.
        * gap-1 keeps a 4px breathing space between the three pills so
        * adjacent active pills never visually merge. */}
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
