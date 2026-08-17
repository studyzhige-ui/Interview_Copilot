import { ReactNode } from 'react';
import { SideNav } from './SideNav';
import { ClientActionBridge } from './ClientActionBridge';
import { SettingsModal } from '@/components/settings/SettingsModal';

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="h-full flex gemini-ambient-bg text-slate-900 overflow-hidden">
      <SideNav />
      <div className="flex-1 min-w-0 flex flex-col relative h-full">
        <main className="flex-1 min-h-0 overflow-y-auto relative">{children}</main>
        <ClientActionBridge />
        <SettingsModal />
      </div>
    </div>
  );
}
