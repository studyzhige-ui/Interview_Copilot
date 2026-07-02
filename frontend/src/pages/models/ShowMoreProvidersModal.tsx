import { X } from 'lucide-react';
import { Pill } from '@/components/ui/Pill';
import type { ProviderInfo } from '@/api/models';
import { VendorAvatar } from './VendorAvatar';

export function ShowMoreProvidersModal({
  providers,
  onToggle,
  onClose,
}: {
  providers: ProviderInfo[];
  onToggle: (provider: string, enabled: boolean) => void;
  onClose: () => void;
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-2xl shadow-xl w-full max-w-lg mx-4 max-h-[85vh] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-5 py-4 border-b border-stone-100 shrink-0">
          <div>
            <div className="text-[15px] font-semibold text-stone-800">显示更多厂商</div>
            <div className="text-[11px] text-stone-400 mt-0.5">
              勾选后即在主页面显示对应卡片；可随时取消勾选
            </div>
          </div>
          <button onClick={onClose} className="p-1 text-stone-400 hover:text-stone-600 rounded">
            <X size={16} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-2">
          {providers.map((info) => (
            <label
              key={info.provider}
              className="flex items-center gap-3 px-3 py-2.5 rounded-lg hover:bg-stone-50 cursor-pointer border border-stone-100"
            >
              <input
                type="checkbox"
                checked={info.enabled}
                onChange={(e) => onToggle(info.provider, e.target.checked)}
                className="w-4 h-4 accent-primary-500"
              />
              <VendorAvatar info={info} small />
              <div className="flex-1 min-w-0">
                <div className="text-sm font-semibold text-stone-800 truncate">
                  {info.display_label}
                </div>
                <div className="text-[10px] text-stone-400 truncate">{info.provider}</div>
              </div>
              {info.has_user_api_key && <Pill tone="success">已配置</Pill>}
            </label>
          ))}
        </div>

        <div className="border-t border-stone-100 px-5 py-3 shrink-0 flex justify-end">
          <button
            type="button"
            onClick={onClose}
            className="text-sm px-4 py-2 rounded-md bg-primary-500 text-white hover:bg-primary-600 font-medium"
          >
            完成
          </button>
        </div>
      </div>
    </div>
  );
}
