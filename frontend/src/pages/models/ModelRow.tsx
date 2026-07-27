import type { ModelPingResult } from '@/api/models';
import type { ModelProfile, ModelRole } from '@/types/api';
import { MODEL_ROW_HEIGHT_PX, ROLE_DESC, ROLES } from './constants';

export function ModelRow({
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
          const available = profile.ready;
          return (
            <button
              key={r}
              onClick={() => available && onAssign(r)}
              disabled={!available}
              title={
                !profile.ready
                  ? `需配置 ${profile.api_key_env}`
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
