import { useState } from 'react';
import { Lock, Trash2, X, Globe } from 'lucide-react';
import { Spinner } from '@/components/ui/Spinner';
import type { ProviderInfo } from '@/api/models';
import { VendorAvatar } from './VendorAvatar';

export function VendorSettingsModal({
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
