import { ReactNode } from 'react';
import { useLocation } from 'react-router-dom';
import { SideNav } from './SideNav';
import { TopBar } from './TopBar';
import { ClientActionBridge } from './ClientActionBridge';
import { SettingsModal } from '@/components/settings/SettingsModal';

const PAGE_TITLES: Record<string, string> = {
  '/today':     '今天 · 指令中心',
  '/career':    '求职进程',
  '/interviews': '面试中枢',
  '/materials': '资料与档案',
  '/activities': '活动中心 · Agent 控制台',
  '/review':    '面试复盘与诊断',
  '/mock':      '模拟面试实战',
  '/general-chat': 'Copilot',
  '/history': '历史探索',
  '/analytics': '能力成长分析',
  '/career-profile': '求职档案',
  '/career-process': '求职进程看板',
  '/career-insights': '行动与决策建议',
  '/artifacts': '求职材料库',
  '/library':   '系统资料库',
  '/models':    '回答模型设置',
  '/capabilities': '插件与能力市场',
  '/plugins': '插件与能力市场',
  '/settings/personalization': '协作与个性化偏好',
  '/me':        '个人中心',
};

export function AppShell({ children }: { children: ReactNode }) {
  const loc = useLocation();
  const title = Object.entries(PAGE_TITLES).find(([p]) =>
    loc.pathname === p || loc.pathname.startsWith(p + '/'),
  )?.[1];

  return (
    <div className="h-full flex gemini-ambient-bg text-slate-900 overflow-hidden">
      <SideNav />
      <div className="flex-1 min-w-0 flex flex-col relative h-full">
        <TopBar pageTitle={title} />
        <main className="flex-1 min-h-0 overflow-y-auto relative">{children}</main>
        <ClientActionBridge />
        <SettingsModal />
      </div>
    </div>
  );
}
