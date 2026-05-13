import { ReactNode } from 'react';
import { useLocation } from 'react-router-dom';
import { SideNav } from './SideNav';
import { TopBar } from './TopBar';

const PAGE_TITLES: Record<string, string> = {
  '/review':    '复盘',
  '/mock':      '模拟面试',
  '/analytics': '能力分析',
  '/library':   '资料库',
  '/models':    '模型',
  '/me':        '个人中心',
};

export function AppShell({ children }: { children: ReactNode }) {
  const loc = useLocation();
  const title = Object.entries(PAGE_TITLES).find(([p]) =>
    loc.pathname === p || loc.pathname.startsWith(p + '/'),
  )?.[1];

  return (
    <div className="h-full flex bg-cream-50">
      <SideNav />
      <div className="flex-1 min-w-0 flex flex-col">
        <TopBar pageTitle={title} />
        <main className="flex-1 min-h-0 overflow-auto">{children}</main>
      </div>
    </div>
  );
}
