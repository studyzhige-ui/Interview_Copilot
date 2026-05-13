import { useEffect, useMemo, useState } from 'react';
import { Lock, RefreshCw, Eye, EyeOff } from 'lucide-react';
import { Pill } from '@/components/ui/Pill';
import { Spinner } from '@/components/ui/Spinner';
import { toast } from '@/store/uiStore';
import { getModelsCatalog, updateModelsRuntime } from '@/api/models';
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

export function ModelsPage() {
  const [profiles, setProfiles] = useState<ModelProfile[]>([]);
  const [primary, setPrimary] = useState<string>('');
  const [loading, setLoading] = useState(true);

  const refresh = async () => {
    setLoading(true);
    try {
      const c = await getModelsCatalog();
      setProfiles(c.profiles);
      setPrimary(c.selection.primary ?? '');
    } catch {
      toast.error('模型目录加载失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { refresh(); }, []);

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

  const onSelect = async (profileId: string, role: ModelRole = 'primary') => {
    const prev = primary;
    if (role === 'primary') setPrimary(profileId);
    try {
      await updateModelsRuntime({ [role]: profileId });
      toast.success('已保存');
    } catch (err) {
      if (role === 'primary') setPrimary(prev);
      const detail = (err as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      toast.error(detail ?? '切换失败');
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
          <div className="eyebrow text-[11px] font-medium uppercase tracking-wider text-stone-500">模型选择</div>
          <h2 className="text-2xl font-semibold text-stone-800 mt-1.5">选择模型与配置</h2>
        </div>
        <button
          onClick={refresh}
          className="p-2 rounded-md text-stone-500 hover:bg-stone-100 ml-auto"
          title="刷新"
        >
          <RefreshCw size={14} />
        </button>
      </div>
      <p className="text-sm text-stone-500 mb-6">
        所有调用走你自己的 API Key。当前 API Key 配置仍通过后端 <code className="font-mono">.env</code>（前端面板提交待后端开放写入端点）。
      </p>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {groups.map((g) => (
          <VendorCard
            key={g.vendor.key}
            vendor={g.vendor}
            list={g.list}
            primaryId={primary}
            onSelect={(id) => onSelect(id)}
          />
        ))}
      </div>
    </div>
  );
}

function VendorCard({
  vendor,
  list,
  primaryId,
  onSelect,
}: {
  vendor: VendorInfo;
  list: ModelProfile[];
  primaryId: string;
  onSelect: (id: string) => void;
}) {
  const anyReady = list.some((p) => p.ready);
  const [showKey, setShowKey] = useState(false);
  // For now the API Key input is informational — the backend resolves keys
  // from the env var named in api_key_env. We render a masked dot string when
  // configured and a placeholder when not.
  const envName = list[0]?.api_key_env ?? '';

  return (
    <div className="bg-white rounded-2xl p-5 border border-stone-200 shadow-xs">
      <div className="flex items-center justify-between mb-3.5">
        <div className="flex items-center gap-2.5">
          <div
            className="w-8 h-8 rounded-lg text-white flex items-center justify-center text-[12px] font-semibold"
            style={{ background: vendor.brand }}
          >
            {vendor.label[0]}
          </div>
          <div className="text-sm font-semibold text-stone-800">{vendor.label}</div>
        </div>
        <Pill tone={anyReady ? 'success' : 'warn'}>{anyReady ? '已配置' : '未配置'}</Pill>
      </div>

      <div className="flex flex-col gap-1.5 mb-3.5">
        {list.map((p) => {
          const sel = p.id === primaryId;
          return (
            <label
              key={p.id}
              className={[
                'flex items-center gap-2.5 px-2.5 py-2 rounded-lg cursor-pointer border transition-colors',
                sel
                  ? 'bg-primary-50 border-primary-200'
                  : 'border-transparent hover:bg-stone-50',
                !p.ready ? 'opacity-50 cursor-not-allowed' : '',
              ].join(' ')}
            >
              <input
                type="radio"
                name={`primary-${vendor.key}`}
                checked={sel}
                disabled={!p.ready}
                onChange={() => p.ready && onSelect(p.id)}
                className="accent-primary-500"
              />
              <span
                className={[
                  'text-[13px] font-mono',
                  sel ? 'text-primary-700' : 'text-stone-700',
                ].join(' ')}
              >
                {p.display_name}
              </span>
            </label>
          );
        })}
      </div>

      <div className="block">
        <div className="text-xs font-medium text-stone-700 mb-1.5">API Key</div>
        <div className="relative">
          <Lock size={12} className="absolute left-3 top-1/2 -translate-y-1/2 text-stone-400" />
          <input
            type={showKey ? 'text' : 'password'}
            readOnly
            value={anyReady ? '••••••••••••••••' : ''}
            placeholder="sk-..."
            className="w-full pl-9 pr-9 py-2 bg-stone-50 border border-stone-200 rounded-md text-sm text-stone-700 outline-none"
          />
          <button
            type="button"
            onClick={() => setShowKey((v) => !v)}
            className="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-stone-400 hover:text-stone-600"
          >
            {showKey ? <EyeOff size={12} /> : <Eye size={12} />}
          </button>
        </div>
        <div className="text-[11px] text-stone-400 mt-1.5">
          通过后端 <code className="font-mono">{envName}</code> 环境变量配置
        </div>
      </div>
    </div>
  );
}
