import { useEffect, useMemo, useState } from 'react';
import { Lock, RefreshCw, Eye, EyeOff, ChevronLeft, ChevronRight, Activity } from 'lucide-react';
import { Pill } from '@/components/ui/Pill';
import { Spinner } from '@/components/ui/Spinner';
import { toast } from '@/store/uiStore';
import { getModelsCatalog, pingAllModels, updateModelsRuntime, type ModelPingResult } from '@/api/models';
import type { ModelProfile, ModelRole } from '@/types/api';

interface VendorInfo {
  key: string;
  label: string;
  brand: string;
}

const VENDORS: VendorInfo[] = [
  { key: 'deepseek',  label: 'DeepSeek',          brand: '#3A6AC1' },
  { key: 'openai',    label: 'OpenAI',            brand: '#10A37F' },
  { key: 'anthropic', label: 'Anthropic',         brand: '#C26A4A' },
  { key: 'qwen',      label: 'Qwen (DashScope)',  brand: '#7A5BC0' },
  { key: 'moonshot',  label: 'Moonshot',          brand: '#1E4A78' },
  { key: 'zhipu',     label: 'Zhipu',             brand: '#0F62FE' },
  { key: 'nvidia',    label: 'NVIDIA',            brand: '#76B900' },
];

const MODELS_PER_PAGE = 3;

const ROLE_DESC: Record<ModelRole, { label: string; short: string }> = {
  primary: { label: '主对话', short: '主' },
  fast:    { label: '快速 / 改写', short: '快' },
  agent:   { label: 'Agent · 工具调用', short: 'A' },
};
const ROLES: ModelRole[] = ['primary', 'fast', 'agent'];

export function ModelsPage() {
  const [profiles, setProfiles] = useState<ModelProfile[]>([]);
  const [selection, setSelection] = useState<Record<ModelRole, string>>({
    primary: '', fast: '', agent: '',
  });
  const [loading, setLoading] = useState(true);
  const [pingResults, setPingResults] = useState<Record<string, ModelPingResult>>({});
  const [pinging, setPinging] = useState(false);

  const refresh = async () => {
    setLoading(true);
    try {
      const c = await getModelsCatalog();
      setProfiles(c.profiles);
      setSelection({
        primary: c.selection.primary ?? '',
        fast: c.selection.fast ?? '',
        agent: c.selection.agent ?? '',
      });
    } catch {
      toast.error('模型目录加载失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { refresh(); }, []);

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
    <div className="p-8 max-w-6xl mx-auto">
      <div className="flex items-end gap-3 mb-1">
        <div>
          <div className="text-[11px] font-medium uppercase tracking-wider text-stone-500">模型选择</div>
          <h2 className="text-2xl font-semibold text-stone-800 mt-1.5">选择模型与配置</h2>
        </div>
        <div className="ml-auto flex items-center gap-2">
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
            title="刷新目录"
          >
            <RefreshCw size={14} />
          </button>
        </div>
      </div>
      <p className="text-sm text-stone-500 mb-4">
        每个模型可独立配置为 <Pill tone="primary">主</Pill> <Pill tone="success">快</Pill> <Pill tone="warn">A</Pill> 三个角色中的一个或多个。
      </p>

      {/* Role assignment summary */}
      <div className="grid grid-cols-3 gap-3 mb-6">
        {ROLES.map((r) => {
          const cur = profiles.find((p) => p.id === selection[r]);
          return (
            <div
              key={r}
              className="bg-white rounded-xl border border-stone-200 p-3.5 shadow-xs"
            >
              <div className="text-[11px] text-stone-500 uppercase tracking-wider">
                {ROLE_DESC[r].label}
              </div>
              <div className="mt-1 text-sm font-medium text-stone-800 truncate">
                {cur?.display_name ?? <span className="text-stone-400">未选择</span>}
              </div>
              <div className="mt-0.5 text-[11px] text-stone-500 truncate font-mono">
                {cur?.model ?? ''}
              </div>
              {cur && !cur.ready && (
                <div className="mt-1">
                  <Pill tone="warn">需配置 {cur.api_key_env}</Pill>
                </div>
              )}
            </div>
          );
        })}
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-3">
        {groups.map((g) => (
          <VendorCard
            key={g.vendor.key}
            vendor={g.vendor}
            list={g.list}
            selection={selection}
            onAssign={assign}
            pingResults={pingResults}
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
}: {
  vendor: VendorInfo;
  list: ModelProfile[];
  selection: Record<ModelRole, string>;
  onAssign: (role: ModelRole, id: string) => void;
  pingResults: Record<string, ModelPingResult>;
}) {
  const anyReady = list.some((p) => p.ready);
  const [showKey, setShowKey] = useState(false);
  const [page, setPage] = useState(0);
  const envName = list[0]?.api_key_env ?? '';
  const totalPages = Math.max(1, Math.ceil(list.length / MODELS_PER_PAGE));
  const start = page * MODELS_PER_PAGE;
  const pageItems = list.slice(start, start + MODELS_PER_PAGE);

  return (
    <div className="bg-white rounded-2xl p-4 border border-stone-200 shadow-xs flex flex-col" style={{ minHeight: 340 }}>
      <div className="flex items-center justify-between mb-2.5">
        <div className="flex items-center gap-2">
          <div
            className="w-7 h-7 rounded-md text-white flex items-center justify-center text-[12px] font-semibold"
            style={{ background: vendor.brand }}
          >
            {vendor.label[0]}
          </div>
          <div className="text-[13px] font-semibold text-stone-800 truncate">{vendor.label}</div>
        </div>
        {anyReady
          ? <Pill tone="success">已配置</Pill>
          : <Pill tone="warn">未配置</Pill>}
      </div>

      <div className="flex-1 flex flex-col gap-1.5 mb-2">
        {pageItems.map((p) => (
          <ModelRow
            key={p.id}
            profile={p}
            selectedRoles={ROLES.filter((r) => selection[r] === p.id)}
            onAssign={(role) => onAssign(role, p.id)}
            ping={pingResults[p.id]}
          />
        ))}
        {Array.from({ length: Math.max(0, MODELS_PER_PAGE - pageItems.length) }).map((_, i) => (
          <div key={`pad-${i}`} className="h-[56px]" aria-hidden />
        ))}
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-3 mb-3">
          <button
            onClick={() => setPage((p) => Math.max(0, p - 1))}
            disabled={page === 0}
            className="w-7 h-7 rounded-full text-stone-500 hover:bg-stone-100 disabled:opacity-30 flex items-center justify-center"
          >
            <ChevronLeft size={14} />
          </button>
          <div className="flex items-center gap-1">
            {Array.from({ length: totalPages }).map((_, i) => (
              <button
                key={i}
                onClick={() => setPage(i)}
                className={[
                  'transition-all',
                  i === page ? 'w-5 h-1.5 bg-primary-500 rounded-full' : 'w-1.5 h-1.5 bg-stone-300 rounded-full hover:bg-stone-400',
                ].join(' ')}
                title={`第 ${i + 1} 页`}
              />
            ))}
          </div>
          <button
            onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
            disabled={page === totalPages - 1}
            className="w-7 h-7 rounded-full text-stone-500 hover:bg-stone-100 disabled:opacity-30 flex items-center justify-center"
          >
            <ChevronRight size={14} />
          </button>
        </div>
      )}

      {/* API Key */}
      <div className="pt-2.5 border-t border-stone-100">
        <div className="relative">
          <Lock size={11} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-stone-400" />
          <input
            type={showKey ? 'text' : 'password'}
            readOnly
            value={anyReady ? '••••••••••••' : ''}
            placeholder="sk-..."
            className="w-full pl-7 pr-7 py-1.5 bg-stone-50 border border-stone-200 rounded text-xs text-stone-700 outline-none"
          />
          <button
            type="button"
            onClick={() => setShowKey((v) => !v)}
            className="absolute right-1.5 top-1/2 -translate-y-1/2 p-0.5 text-stone-400 hover:text-stone-600"
          >
            {showKey ? <EyeOff size={11} /> : <Eye size={11} />}
          </button>
        </div>
        <div className="text-[10px] text-stone-400 mt-1 font-mono truncate">{envName}</div>
      </div>
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

  // Ping status takes priority over static readiness — once user pings, that's
  // the source of truth for "actually reachable right now".
  const dotColor = ping
    ? ping.ok
      ? 'bg-success-500'
      : 'bg-danger-500'
    : profile.ready
    ? 'bg-stone-300'
    : 'bg-warning-500';
  const dotTitle = ping
    ? ping.ok
      ? `可达 · ${ping.latency_ms}ms`
      : `不可达：${ping.error ?? '未知'}`
    : profile.ready
    ? '已配置 · 未测试'
    : `未配置 ${profile.api_key_env}`;

  return (
    <div
      className={[
        'rounded-lg border px-2.5 py-2 transition-colors',
        selectedRoles.length > 0
          ? 'border-primary-200 bg-primary-50/40'
          : 'border-stone-200 bg-white',
      ].join(' ')}
    >
      <div className="flex items-center gap-2 mb-1.5">
        <span
          className={`inline-block w-1.5 h-1.5 rounded-full shrink-0 ${dotColor}`}
          title={dotTitle}
        />
        <div className="flex-1 min-w-0">
          <div className="text-[12px] font-medium text-stone-800 truncate">{profile.display_name}</div>
        </div>
        {ping && ping.ok && (
          <span className="text-[10px] text-stone-400 font-mono shrink-0">{ping.latency_ms}ms</span>
        )}
      </div>

      {/* Glass role tabs */}
      <div
        className="inline-flex items-center p-0.5 rounded-full border border-stone-200/80"
        style={{
          background: 'rgba(255,255,255,0.55)',
          backdropFilter: 'blur(10px)',
          WebkitBackdropFilter: 'blur(10px)',
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
                'px-2.5 py-0.5 rounded-full text-[11px] font-medium transition-all',
                active
                  ? 'bg-primary-500 text-white shadow-sm'
                  : available
                  ? 'text-stone-600 hover:bg-white hover:text-stone-800'
                  : 'text-stone-300 cursor-not-allowed',
              ].join(' ')}
            >
              {ROLE_DESC[r].short}
            </button>
          );
        })}
      </div>
    </div>
  );
}
