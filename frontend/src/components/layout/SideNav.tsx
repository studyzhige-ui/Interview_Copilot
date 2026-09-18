import { Link, useLocation } from 'react-router-dom';
import { Sun, BriefcaseBusiness, Mic, Files, History, Settings2, MessageSquare } from 'lucide-react';
import { Logo } from '@/components/ui/Logo';
import { pathMatches, workspaces } from './navigation';

const icons = [Sun, BriefcaseBusiness, Mic, Files, History, Settings2];

export function SideNav() {
  const { pathname } = useLocation();
  return (
    <aside className="workspace-sidebar">
      <Link to="/today" className="workspace-brand" aria-label="Interview Copilot 首页">
        <Logo size={30} /><span>Interview<br /><strong>Copilot</strong></span>
      </Link>
      <nav aria-label="主导航" className="workspace-nav">
        {workspaces.map((area, index) => {
          const Icon = icons[index];
          const active = area.paths.some((path) => pathMatches(pathname, path));
          return <Link key={area.to} to={area.to} aria-current={active ? 'page' : undefined}
            className={`workspace-nav-link ${active ? 'is-active' : ''} ${index === 4 ? 'workspace-nav-secondary' : ''}`}
            title={area.label}>
            <Icon size={19} strokeWidth={1.7} /><span>{area.label}</span>
          </Link>;
        })}
      </nav>
      <div className="workspace-sidebar-footer">
        <Link to="/general-chat" className={`workspace-assistant-link ${pathname === '/general-chat' ? 'is-active' : ''}`}
          aria-current={pathname === '/general-chat' ? 'page' : undefined} title="与 Copilot 协作">
          <MessageSquare size={18} /><span>与 Copilot 协作</span>
        </Link>
        <p>把每一步，向前推进。</p>
      </div>
    </aside>
  );
}
