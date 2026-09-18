import { ReactNode, useLayoutEffect, useRef } from 'react';
import { useLocation } from 'react-router-dom';
import { SideNav } from './SideNav';
import { TopBar } from './TopBar';
import { ClientActionBridge } from './ClientActionBridge';
import { workspaceFor } from './navigation';

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
  const contentRef = useRef<HTMLElement>(null);
  useLayoutEffect(() => {
    // The workspace, rather than window, owns page scrolling. A new page
    // must not inherit the previous page's offset; same-page filters keep it.
    if (contentRef.current) contentRef.current.scrollTop = 0;
  }, [loc.pathname]);
  const title = workspaceFor(loc.pathname)?.label ?? Object.entries(PAGE_TITLES).find(([p]) =>
    loc.pathname === p || loc.pathname.startsWith(p + '/'),
  )?.[1];

  return (
    <div className="workspace-shell">
      <a className="skip-to-content" href="#workspace-content">跳到主要内容</a>
      <SideNav />
      <div className="flex-1 min-w-0 min-h-0 flex flex-col">
        <TopBar pageTitle={title} />
        <main ref={contentRef} id="workspace-content" tabIndex={-1} className="workspace-content flex-1 min-h-0 overflow-auto">{children}</main>
        <ClientActionBridge />
      </div>
    </div>
  );
}
