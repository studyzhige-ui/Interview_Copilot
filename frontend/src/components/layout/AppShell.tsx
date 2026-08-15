import { ReactNode } from 'react';
import { useLocation } from 'react-router-dom';
import { SideNav } from './SideNav';
import { TopBar } from './TopBar';
import { ClientActionBridge } from './ClientActionBridge';

const PAGE_TITLES: Record<string, string> = {
  '/review':    '面试复盘',
  '/mock':      '模拟面试',
  '/general-chat': '求职 Copilot',
  '/history': '历史记录',
  '/analytics': '能力成长',
  '/career-profile': '求职档案',
  '/career-process': '求职进程',
  '/career-insights': '行动与决策',
  '/artifacts': '求职材料',
  '/library':   '资料库',
  '/models':    '回答模型',
  '/capabilities': '插件市场',
  '/plugins': '插件市场',
  '/settings/personalization': '协作偏好',
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
        <ClientActionBridge />
      </div>
    </div>
  );
}
