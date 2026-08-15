import { useEffect, Suspense } from 'react';
import {
  X,
  Settings,
  Cpu,
  Sparkles,
  Volume2,
  ShieldCheck,
  ChevronRight,
} from 'lucide-react';
import { useSettingsModalStore, type SettingsTabKey } from '@/store/settingsModalStore';
import { GeneralSettingsTab } from './tabs/GeneralSettingsTab';
import { VoiceSettingsTab } from './tabs/VoiceSettingsTab';
import { AccountSecurityTab } from './tabs/AccountSecurityTab';
import { ModelsSettingsTab } from './tabs/ModelsSettingsTab';
import { PersonalizationSettingsTab } from './tabs/PersonalizationSettingsTab';
import { Spinner } from '@/components/ui/Spinner';

interface NavItem {
  id: SettingsTabKey;
  label: string;
  icon: typeof Settings;
}

const NAV_ITEMS: NavItem[] = [
  { id: 'general', label: '常规设置', icon: Settings },
  { id: 'models', label: '模型配置', icon: Cpu },
  { id: 'personalization', label: '个性化偏好', icon: Sparkles },
  { id: 'voice', label: '语音与音色', icon: Volume2 },
  { id: 'security', label: '账户与安全', icon: ShieldCheck },
];

export function SettingsModal() {
  const { isOpen, activeTab, closeModal, setActiveTab } = useSettingsModalStore();

  // Keyboard shortcut: Esc to close modal
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && isOpen) {
        closeModal();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, closeModal]);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-6 md:p-10 bg-slate-900/40 backdrop-blur-md animate-in fade-in duration-150">
      {/* Background Overlay */}
      <div className="absolute inset-0" onClick={closeModal} />

      {/* Center Modal Card */}
      <div className="relative w-full max-w-4xl max-h-[85vh] h-[680px] bg-white rounded-3xl shadow-2xl border border-slate-200/90 flex flex-col overflow-hidden z-10 animate-in zoom-in-95 duration-150">
        {/* Modal Top Header */}
        <div className="h-16 px-6 border-b border-slate-100 flex items-center justify-between shrink-0 bg-white/90">
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={closeModal}
              title="关闭设置"
              className="p-2 rounded-full text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition-colors cursor-pointer"
            >
              <X size={18} />
            </button>
            <h2 className="text-base font-bold text-slate-900 tracking-tight">系统设置</h2>
          </div>
        </div>

        {/* Modal Body: Left Sidebar Tabs + Right Content Pane */}
        <div className="flex-1 min-h-0 flex flex-col md:flex-row overflow-hidden">
          {/* Left Category Navigation: Always 100% visible */}
          <aside className="w-full md:w-56 shrink-0 bg-slate-50/60 border-b md:border-b-0 md:border-r border-slate-100 p-3 flex md:flex-col gap-1 overflow-x-auto md:overflow-y-auto">
            {NAV_ITEMS.map((item) => {
              const Icon = item.icon;
              const isSelected = activeTab === item.id;

              return (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => setActiveTab(item.id)}
                  className={`w-full flex items-center gap-2.5 px-3.5 py-2.5 rounded-2xl text-sm font-medium transition-all text-left cursor-pointer ${
                    isSelected
                      ? 'bg-white text-blue-700 font-semibold shadow-2xs border border-slate-200/60'
                      : 'text-slate-600 hover:bg-slate-100/80 hover:text-slate-900'
                  }`}
                >
                  <Icon size={17} className={isSelected ? 'text-blue-600' : 'text-slate-400'} />
                  <span className="flex-1 truncate">{item.label}</span>
                  {isSelected && <ChevronRight size={14} className="text-blue-600 hidden md:block" />}
                </button>
              );
            })}
          </aside>

          {/* Right Content Pane */}
          <main className="flex-1 min-w-0 p-6 md:p-8 overflow-y-auto bg-white">
            <Suspense fallback={<div className="p-8 flex items-center justify-center text-slate-400"><Spinner size={20} /></div>}>
              {activeTab === 'general' && <GeneralSettingsTab />}
              {activeTab === 'models' && <ModelsSettingsTab />}
              {activeTab === 'personalization' && <PersonalizationSettingsTab />}
              {activeTab === 'voice' && <VoiceSettingsTab />}
              {activeTab === 'security' && <AccountSecurityTab />}
            </Suspense>
          </main>
        </div>
      </div>
    </div>
  );
}
