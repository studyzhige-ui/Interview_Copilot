import { useState } from 'react';
import { Cable, Sparkles } from 'lucide-react';
import { useEditionPolicy } from '@/hooks/useEditionPolicy';
import { MCPServersPanel } from './MCPServersPanel';
import { SkillsPanel } from './SkillsPanel';

type Tab = 'skills' | 'mcp';

export function CapabilitiesPage() {
  const [tab, setTab] = useState<Tab>('skills');
  const edition = useEditionPolicy();
  return (
    <div className="h-full overflow-auto bg-stone-50">
      <main className="mx-auto max-w-6xl px-6 py-7">
        <div className="mb-6">
          <h1 className="text-2xl font-semibold text-stone-900">Agent 能力</h1>
          <p className="mt-1.5 text-sm text-stone-500">管理只属于你的 Skill 与 MCP 工具；启用后会自动进入 Agent 对话。</p>
        </div>
        <div className="mb-6 flex w-fit rounded-lg border border-stone-200 bg-white p-1">
          <TabButton active={tab === 'skills'} onClick={() => setTab('skills')} icon={<Sparkles size={15} />}>Skills</TabButton>
          <TabButton active={tab === 'mcp'} onClick={() => setTab('mcp')} icon={<Cable size={15} />}>MCP</TabButton>
        </div>
        {tab === 'skills'
          ? <SkillsPanel />
          : <MCPServersPanel allowedTransports={edition.data?.mcp_transports ?? ['streamable_http']} />}
      </main>
    </div>
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
      onClick={onClick}
      className={`flex items-center gap-1.5 rounded-md px-4 py-2 text-sm transition ${active ? 'bg-primary-50 font-medium text-primary-700' : 'text-stone-500 hover:text-stone-800'}`}
    >
      {icon}{children}
    </button>
  );
}
