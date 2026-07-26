import { useState } from 'react';
import { Lock, Settings2 } from 'lucide-react';
import { Pill } from '@/components/ui/Pill';
import type { ModelPingResult, ProviderInfo } from '@/api/models';
import type { ModelProfile, ModelRole } from '@/types/api';
import {
  MODEL_ROW_GAP_PX, MODEL_ROW_HEIGHT_PX, MODELS_VISIBLE_ROWS, ROLES,
} from './constants';
import { ModelRow } from './ModelRow';
import { VendorAvatar } from './VendorAvatar';
import { VendorSettingsModal } from './VendorSettingsModal';

export function VendorCard({
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
  showAdvancedSettings,
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
  showAdvancedSettings: boolean;
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
        * backend pipeline; we just preserve that order.
        *
        * No bottom fade gradient: with MODELS_VISIBLE_ROWS=2 the card
        * is 136px tall and a 32px fade would obscure half of the
        * second model row. The "下滑查看全部" text hint above the
        * scroll area already signals there's more content. */}
      <div className="mb-2" style={{ height: modelsAreaHeight }}>
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
          showAdvancedSettings={showAdvancedSettings}
        />
      )}
    </div>
  );
}
