import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useSearchParams } from 'react-router-dom';
import {
  ArrowRight,
  Blocks,
  Cable,
  CalendarDays,
  FileText,
  Mail,
  MessageSquare,
  Palette,
  Search,
  ShieldCheck,
  Sparkles,
} from 'lucide-react';
import { getExternalPluginStatus, getGmailIntegration } from '@/api/integrations';
import { Pill } from '@/components/ui/Pill';
import { useEditionPolicy } from '@/hooks/useEditionPolicy';
import { MCPServersPanel } from './MCPServersPanel';
import { SkillsPanel } from './SkillsPanel';
import { PluginConnectionPanel } from './PluginConnectionPanel';
import type { ConnectablePlugin } from './PluginConnectionPanel';

type Tab = 'marketplace' | 'skills' | 'mcp';
type PluginCategory = '效率' | '设计' | '沟通' | '知识';
type PluginStatus = 'connected' | 'available' | 'coming_soon' | 'unavailable';

interface MarketplacePlugin {
  id: string;
  name: string;
  publisher: string;
  description: string;
  category: PluginCategory;
  icon: typeof Mail;
  iconClass: string;
  capabilities: string[];
  status: PluginStatus;
  connectable?: boolean;
}

function projectedPluginStatus(data: {
  adapter_available?: boolean;
  connection_required?: boolean;
  account?: { status?: string } | null;
} | undefined): PluginStatus {
  if (data?.account?.status === 'active' && !data.connection_required) return 'connected';
  return data?.adapter_available === false ? 'unavailable' : 'available';
}

const CATALOG: Omit<MarketplacePlugin, 'status'>[] = [
  {
    id: 'gmail',
    name: 'Gmail',
    publisher: 'Google',
    description: '读取招聘邮件、跟踪流程变化，并将模糊变化留给你确认。',
    category: '沟通',
    icon: Mail,
    iconClass: 'bg-red-50 text-red-600',
    capabilities: ['只读邮箱', 'OAuth', '增量同步'],
    connectable: true,
  },
  {
    id: 'canva',
    name: 'Canva',
    publisher: 'Canva',
    description: '搜索你拥有或获共享的设计，供 Copilot 引用标题与设计链接。',
    category: '设计',
    icon: Palette,
    iconClass: 'bg-violet-50 text-violet-600',
    capabilities: ['设计搜索', '元数据只读', 'OAuth'],
    connectable: true,
  },
  {
    id: 'google-calendar',
    name: 'Google Calendar',
    publisher: 'Google',
    description: '读取面试安排并在明确授权后创建或调整日程。',
    category: '效率',
    icon: CalendarDays,
    iconClass: 'bg-blue-50 text-blue-600',
    capabilities: ['日程读取', '提醒', '写入需确认'],
  },
  {
    id: 'slack',
    name: 'Slack',
    publisher: 'Salesforce',
    description: '从指定工作区读取求职协作信息；外发始终需要明确批准。',
    category: '沟通',
    icon: MessageSquare,
    iconClass: 'bg-amber-50 text-amber-700',
    capabilities: ['限定频道', '只读优先', '外发需确认'],
  },
  {
    id: 'notion',
    name: 'Notion',
    publisher: 'Notion Labs',
    description: '搜索你在授权页明确共享的 Notion 页面标题与链接。',
    category: '知识',
    icon: FileText,
    iconClass: 'bg-stone-100 text-stone-700',
    capabilities: ['共享页搜索', '标题只读', 'OAuth'],
    connectable: true,
  },
];

export function CapabilitiesPage() {
  const [tab, setTab] = useState<Tab>('marketplace');
  const edition = useEditionPolicy();
  return (
    <div className="h-full overflow-auto bg-stone-50">
      <main className="mx-auto max-w-7xl px-4 py-6 md:px-6 md:py-7">
        <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
          <div>
            <div className="mb-2 inline-flex items-center gap-1.5 rounded-full bg-primary-50 px-2.5 py-1 text-xs font-medium text-primary-700">
              <Blocks size={13} /> 插件与能力
            </div>
            <h1 className="text-2xl font-semibold text-stone-900">插件市场</h1>
            <p className="mt-1.5 max-w-2xl text-sm text-stone-500">
              发现并管理 Copilot 可使用的外部服务。每个插件都有独立权限、连接状态和 Tool 边界。
            </p>
          </div>
          <div className="flex items-center gap-1.5 text-xs text-stone-500">
            <ShieldCheck size={15} className="text-accent-700" /> Secret 不进入模型上下文
          </div>
        </div>
        <div className="mb-6 flex w-fit rounded-lg border border-stone-200 bg-white p-1">
          <TabButton active={tab === 'marketplace'} onClick={() => setTab('marketplace')} icon={<Blocks size={15} />}>插件市场</TabButton>
          <TabButton active={tab === 'skills'} onClick={() => setTab('skills')} icon={<Sparkles size={15} />}>Skills</TabButton>
          <TabButton active={tab === 'mcp'} onClick={() => setTab('mcp')} icon={<Cable size={15} />}>MCP</TabButton>
        </div>
        {tab === 'marketplace' && <PluginMarketplace />}
        {tab === 'skills' && <SkillsPanel />}
        {tab === 'mcp' && <MCPServersPanel allowedTransports={edition.data?.mcp_transports ?? ['streamable_http']} />}
      </main>
    </div>
  );
}

function PluginMarketplace() {
  const [query, setQuery] = useState('');
  const [category, setCategory] = useState<'全部' | PluginCategory>('全部');
  const [params, setParams] = useSearchParams();
  const returnedProvider = params.get('plugin_oauth_provider');
  const requestedPlugin = params.get('plugin');
  const initialPlugin = (
    returnedProvider === 'canva' || returnedProvider === 'notion'
      ? returnedProvider
      : params.has('gmail_oauth_outcome')
        ? 'gmail'
        : requestedPlugin
  );
  const selected: ConnectablePlugin | null = (
    initialPlugin === 'gmail' || initialPlugin === 'canva' || initialPlugin === 'notion'
      ? initialPlugin
      : null
  );
  const gmail = useQuery({ queryKey: ['integrations', 'gmail'], queryFn: getGmailIntegration });
  const canva = useQuery({ queryKey: ['integrations', 'canva'], queryFn: () => getExternalPluginStatus('canva') });
  const notion = useQuery({ queryKey: ['integrations', 'notion'], queryFn: () => getExternalPluginStatus('notion') });
  const gmailStatus: PluginStatus = gmail.data?.account?.status === 'active' && !gmail.data.connection_required
    ? 'connected'
    : gmail.data?.adapter_available === false
      ? 'unavailable'
      : 'available';
  const plugins = useMemo<MarketplacePlugin[]>(() => CATALOG.map((plugin) => ({
    ...plugin,
    status: plugin.id === 'gmail'
      ? gmailStatus
      : plugin.id === 'canva'
        ? projectedPluginStatus(canva.data)
        : plugin.id === 'notion'
          ? projectedPluginStatus(notion.data)
          : 'coming_soon',
  })), [canva.data, gmailStatus, notion.data]);
  const visible = useMemo(() => {
    const term = query.trim().toLowerCase();
    return plugins.filter((plugin) => (
      (category === '全部' || plugin.category === category)
      && (!term || `${plugin.name} ${plugin.publisher} ${plugin.description}`.toLowerCase().includes(term))
    ));
  }, [category, plugins, query]);
  const manage = (provider: ConnectablePlugin | null) => {
    const next = new URLSearchParams(params);
    if (provider) next.set('plugin', provider);
    else next.delete('plugin');
    setParams(next, { replace: true });
  };

  return (
    <section>
      <div className="mb-5 rounded-2xl border border-primary-100 bg-gradient-to-r from-primary-50 via-white to-accent-50 p-4 md:p-5">
        <div className="flex flex-col gap-3 md:flex-row md:items-center">
          <label className="relative block flex-1">
            <Search size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-stone-400" />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="搜索插件，例如 Gmail、Canva"
              aria-label="搜索插件"
              className="w-full rounded-xl border border-stone-200 bg-white py-2.5 pl-10 pr-3 text-sm outline-none transition focus:border-primary-300 focus:ring-2 focus:ring-primary-200"
            />
          </label>
          <div className="flex flex-wrap gap-2">
            {(['全部', '效率', '设计', '沟通', '知识'] as const).map((item) => (
              <button
                key={item}
                type="button"
                onClick={() => setCategory(item)}
                className={`rounded-full border px-3 py-1.5 text-xs transition ${category === item ? 'border-primary-200 bg-primary-100 text-primary-800' : 'border-stone-200 bg-white text-stone-600 hover:border-stone-300'}`}
              >
                {item}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {visible.map((plugin) => (
          <PluginCard
            key={plugin.id}
            plugin={plugin}
            selected={selected === plugin.id}
            onManage={() => manage(plugin.id as ConnectablePlugin)}
          />
        ))}
      </div>
      {visible.length === 0 && (
        <div className="rounded-xl border border-dashed border-stone-300 bg-white p-10 text-center text-sm text-stone-500">没有匹配的插件</div>
      )}
      {selected && <PluginConnectionPanel provider={selected} onClose={() => manage(null)} />}
    </section>
  );
}

function PluginCard({ plugin, selected, onManage }: {
  plugin: MarketplacePlugin;
  selected: boolean;
  onManage: () => void;
}) {
  const Icon = plugin.icon;
  const status = {
    connected: { label: '已连接', tone: 'success' as const },
    available: { label: '可连接', tone: 'primary' as const },
    unavailable: { label: '部署未配置', tone: 'neutral' as const },
    coming_soon: { label: '即将支持', tone: 'sand' as const },
  }[plugin.status];
  return (
    <article className={`group flex h-full flex-col rounded-2xl border bg-white p-5 shadow-xs transition ${selected ? 'border-primary-400 ring-2 ring-primary-100' : 'border-stone-200 hover:-translate-y-0.5 hover:border-primary-200 hover:shadow-sm'}`}>
      <div className="flex items-start justify-between gap-3">
        <div className={`flex h-11 w-11 items-center justify-center rounded-xl ${plugin.iconClass}`}><Icon size={22} /></div>
        <Pill tone={status.tone}>{status.label}</Pill>
      </div>
      <div className="mt-4">
        <h2 className="font-semibold text-stone-900">{plugin.name}</h2>
        <p className="mt-0.5 text-[11px] text-stone-400">{plugin.publisher}</p>
      </div>
      <p className="mt-3 flex-1 text-sm leading-relaxed text-stone-600">{plugin.description}</p>
      <div className="mt-4 flex flex-wrap gap-1.5">
        {plugin.capabilities.map((item) => <span key={item} className="rounded-full bg-stone-100 px-2 py-1 text-[10px] text-stone-600">{item}</span>)}
      </div>
      <div className="mt-4 flex items-center justify-between border-t border-stone-100 pt-3 text-xs">
        <span className="text-stone-400">{plugin.category}</span>
        {plugin.connectable ? (
          <button type="button" onClick={onManage} aria-label={`管理 ${plugin.name} 插件`} className="inline-flex items-center gap-1 font-medium text-primary-700 hover:text-primary-900">
            {selected ? '正在管理' : '连接与管理'} <ArrowRight size={13} />
          </button>
        ) : (
          <span className="text-stone-400">等待真实 Adapter</span>
        )}
      </div>
    </article>
  );
}

function TabButton({ active, onClick, icon, children }: {
  active: boolean;
  onClick: () => void;
  icon: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`flex items-center gap-1.5 rounded-md px-4 py-2 text-sm transition ${active ? 'bg-primary-50 font-medium text-primary-700' : 'text-stone-500 hover:text-stone-800'}`}
    >
      {icon}{children}
    </button>
  );
}
