import { useEffect, useState } from 'react';
import { ShieldCheck, X } from 'lucide-react';
import {
  getSessionCapabilities,
  listMCPServers,
  listSkills,
  setSessionCapabilityPermission,
  type CapabilityDecision,
  type SessionCapabilityState,
  type UserMCPServer,
  type UserSkill,
} from '@/api/capabilities';
import { extractErr } from '@/api/client';
import { toast } from '@/store/uiStore';


export function SessionCapabilities({ sessionId }: { sessionId: string | null }) {
  const [open, setOpen] = useState(false);
  const [state, setState] = useState<SessionCapabilityState | null>(null);
  const [skills, setSkills] = useState<UserSkill[]>([]);
  const [servers, setServers] = useState<UserMCPServer[]>([]);

  useEffect(() => {
    if (!open || !sessionId) return;
    let live = true;
    Promise.all([getSessionCapabilities(sessionId), listSkills(), listMCPServers()])
      .then(([nextState, nextSkills, nextServers]) => {
        if (!live) return;
        setState(nextState);
        setSkills(nextSkills.filter((item) => item.enabled));
        setServers(nextServers.filter((item) => item.enabled));
      })
      .catch((error) => toast.error(extractErr(error, '加载会话权限失败')));
    return () => { live = false; };
  }, [open, sessionId]);

  const change = async (capability: string, decision: CapabilityDecision) => {
    if (!sessionId) return;
    try {
      setState(await setSessionCapabilityPermission(sessionId, capability, decision));
    } catch (error) {
      toast.error(extractErr(error, '更新会话权限失败'));
    }
  };

  return (
    <div className="relative">
      <button
        onClick={() => setOpen((value) => !value)}
        disabled={!sessionId}
        title="设置当前会话的 Skill / MCP 权限"
        className="inline-flex items-center gap-1.5 rounded-full border border-stone-200 bg-white px-2.5 py-1 text-[11px] font-medium text-stone-600 disabled:opacity-50"
      >
        <ShieldCheck size={11} /> 会话权限
      </button>
      {open && sessionId && (
        <div className="absolute bottom-8 left-0 z-30 w-80 rounded-xl border border-stone-200 bg-white p-3 shadow-xl">
          <div className="mb-2 flex items-center justify-between">
            <div>
              <div className="text-sm font-medium text-stone-800">当前会话能力</div>
              <div className="text-[11px] text-stone-400">默认继承用户级启用状态，仅影响后续 turn</div>
            </div>
            <button onClick={() => setOpen(false)} className="p-1 text-stone-400"><X size={14} /></button>
          </div>
          <div className="max-h-64 space-y-1 overflow-auto">
            {skills.map((skill) => (
              <PermissionRow
                key={`skill:${skill.name}`}
                label={`Skill · ${skill.name}`}
                value={state?.permissions[`skill:${skill.name}`] ?? 'inherit'}
                onChange={(value) => { void change(`skill:${skill.name}`, value); }}
              />
            ))}
            {servers.map((server) => (
              <PermissionRow
                key={`mcp_server:${server.id}`}
                label={`MCP · ${server.name}`}
                value={state?.permissions[`mcp_server:${server.id}`] ?? 'inherit'}
                onChange={(value) => { void change(`mcp_server:${server.id}`, value); }}
              />
            ))}
            {skills.length === 0 && servers.length === 0 && (
              <div className="py-4 text-center text-xs text-stone-400">暂无已启用的用户能力</div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}


function PermissionRow({ label, value, onChange }: {
  label: string;
  value: CapabilityDecision;
  onChange: (value: CapabilityDecision) => void;
}) {
  return (
    <label className="flex items-center justify-between gap-2 rounded-lg px-2 py-1.5 hover:bg-stone-50">
      <span className="truncate text-xs text-stone-700">{label}</span>
      <select
        value={value}
        onChange={(event) => onChange(event.target.value as CapabilityDecision)}
        className="rounded border border-stone-200 bg-white px-1.5 py-1 text-[11px] text-stone-600"
      >
        <option value="inherit">继承（允许）</option>
        <option value="allow">允许</option>
        <option value="deny">拒绝</option>
      </select>
    </label>
  );
}
