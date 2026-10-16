import type { ModelPingResult } from '@/api/models';
import type { ModelProfile, ModelRole } from '@/types/api';
import { MODEL_ROW_HEIGHT_PX, ROLE_DESC, ROLES } from './constants';

export function ModelRow({ profile, selectedRoles, onAssign, ping }: {
  profile: ModelProfile;
  selectedRoles: ModelRole[];
  onAssign: (role: ModelRole) => void;
  ping?: ModelPingResult;
}) {
  const status = ping ? (ping.ok ? `连接正常 · ${ping.latency_ms}ms` : `连接失败：${ping.error ?? '未知原因'}`)
    : profile.ready ? '已配置，尚未测试连接' : '请先配置提供商';
  return <div className={`flex shrink-0 items-center gap-3 rounded-lg border px-3 ${selectedRoles.length ? 'border-primary-200 bg-primary-50' : 'border-stone-200 bg-white'}`} style={{ height: MODEL_ROW_HEIGHT_PX }}>
    <div className="min-w-0 flex-1" title={profile.model}>
      <div className="truncate text-sm font-medium text-stone-800">{profile.display_name}</div>
      <p className={`mt-1 truncate text-[10px] ${ping && !ping.ok ? 'text-danger-600' : 'text-stone-400'}`} title={status}>{status}</p>
    </div>
    {ROLES.map((role) => <button key={role} type="button" aria-label={`将 ${profile.display_name} 设为${ROLE_DESC[role].label}`} aria-pressed={selectedRoles.includes(role)} disabled={!profile.ready} onClick={() => onAssign(role)}
      className="shrink-0 rounded-md px-2 py-1 text-xs text-primary-700 hover:bg-primary-100 disabled:text-stone-300">
      {selectedRoles.includes(role) ? '使用中' : '使用'}
    </button>)}
  </div>;
}
