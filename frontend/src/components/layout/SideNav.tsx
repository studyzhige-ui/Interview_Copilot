import { useEffect, useRef, useState } from 'react';
import { NavLink, useNavigate } from 'react-router-dom';
import {
  Sparkles,
  MessageSquarePlus,
  Compass,
  FileBarChart2,
  Mic2,
  Workflow,
  Contact,
  TrendingUp,
  Blocks,
  Zap,
  Clock,
  Settings,
  LogOut,
  HelpCircle,
  PanelLeftClose,
  PanelLeftOpen,
} from 'lucide-react';
import { Logo } from '@/components/ui/Logo';
import { useAuthStore } from '@/store/authStore';
import { Avatar } from '@/components/ui/Avatar';
import { useSettingsModalStore } from '@/store/settingsModalStore';
import { toast } from '@/store/uiStore';

interface NavItem {
  to: string;
  label: string;
  icon: typeof Compass;
  badge?: string;
}

// First-Class Core Navigation Items with Modern Icons & Simplified Labels
const NAV_ITEMS: NavItem[] = [
  { to: '/general-chat', label: 'Copilot', icon: Sparkles },
  { to: '/review', label: '面试复盘', icon: FileBarChart2 },
  { to: '/mock', label: '模拟面试', icon: Mic2 },
  { to: '/growth', label: '持续成长', icon: TrendingUp },
  { to: '/career-process', label: '应聘进程', icon: Workflow },
  { to: '/career-profile', label: '求职档案', icon: Contact },
  { to: '/capabilities', label: '能力与插件', icon: Blocks },
  { to: '/persistent-tasks', label: '自动化监控', icon: Zap },
  { to: '/history', label: '历史记录', icon: Clock },
];

const COLLAPSED_KEY = 'sidenav.collapsed';

export function SideNav() {
  const navigate = useNavigate();
  const me = useAuthStore((s) => s.me);
  const subjectId = useAuthStore((s) => s.subjectId);
  const logout = useAuthStore((s) => s.logout);
  const openSettings = useSettingsModalStore((s) => s.openModal);

  const [collapsed, setCollapsed] = useState<boolean>(() => {
    try {
      const v = localStorage.getItem(COLLAPSED_KEY);
      return v === '1';
    } catch {
      return false;
    }
  });

  const [hovering, setHovering] = useState(false);
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const userMenuRef = useRef<HTMLDivElement | null>(null);

  const toggleCollapsed = () => {
    setCollapsed((prev) => {
      const next = !prev;
      try {
        localStorage.setItem(COLLAPSED_KEY, next ? '1' : '0');
      } catch {
        /* ignore */
      }
      return next;
    });
  };

  // Click outside to close user menu popover
  useEffect(() => {
    const handleOutsideClick = (e: MouseEvent) => {
      if (userMenuRef.current && !userMenuRef.current.contains(e.target as Node)) {
        setUserMenuOpen(false);
      }
    };
    if (userMenuOpen) {
      document.addEventListener('mousedown', handleOutsideClick);
    }
    return () => document.removeEventListener('mousedown', handleOutsideClick);
  }, [userMenuOpen]);

  // If collapsed, hovering temporarily expands the sidebar
  const isExpanded = !collapsed || hovering;
  const displayName = me?.nickname || me?.username || '用户';

  return (
    <aside
      onMouseEnter={() => collapsed && setHovering(true)}
      onMouseLeave={() => collapsed && setHovering(false)}
      className={[
        isExpanded ? 'w-[230px]' : 'w-[68px]',
        'shrink-0 h-full border-r border-slate-200/80 bg-white/95 backdrop-blur-xl',
        'flex flex-col justify-between select-none z-30 transition-all duration-200 ease-out relative',
        collapsed && hovering ? 'shadow-2xl ring-1 ring-slate-200/80' : '',
      ].join(' ')}
    >
      {/* Top Header: Logo & Toggle Button */}
      <div className="p-3.5 flex items-center justify-between">
        <div
          onClick={() => navigate('/general-chat')}
          className="flex items-center gap-2.5 cursor-pointer group min-w-0"
          title="Interview Copilot"
        >
          <Logo size={28} />
          {isExpanded && (
            <div className="flex flex-col min-w-0">
              <span className="font-bold text-sm tracking-tight text-slate-800 truncate">
                Interview Copilot
              </span>
              <span className="text-xs text-slate-400 font-medium tracking-wide">
                智能求职副驾
              </span>
            </div>
          )}
        </div>

        {/* Dedicated Collapse / Expand Button */}
        {isExpanded && (
          <button
            type="button"
            onClick={toggleCollapsed}
            title={collapsed ? '锁定展开侧边栏' : '折叠侧边栏'}
            className="p-1.5 rounded-xl text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition-colors cursor-pointer"
          >
            {collapsed ? <PanelLeftOpen size={16} /> : <PanelLeftClose size={16} />}
          </button>
        )}
      </div>

      {/* When fully collapsed without hover, show single expand icon on top */}
      {!isExpanded && (
        <div className="px-3 pb-2 flex justify-center">
          <button
            type="button"
            onClick={toggleCollapsed}
            title="展开侧边栏"
            className="p-2 rounded-xl text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition-colors cursor-pointer"
          >
            <PanelLeftOpen size={17} />
          </button>
        </div>
      )}

      {/* Floating Action Pills */}
      <div className="px-3 pb-2.5 flex flex-col gap-2">
        <button
          type="button"
          onClick={() => navigate('/general-chat')}
          title="新建对话"
          className={[
            'w-full flex items-center justify-center gap-2 py-2.5 rounded-full font-semibold text-sm transition-all duration-200 cursor-pointer',
            'bg-slate-100 text-slate-700 hover:bg-slate-200 hover:text-slate-900 border border-slate-200/60 shadow-2xs',
            isExpanded ? 'px-4' : 'px-2',
          ].join(' ')}
        >
          <MessageSquarePlus size={16} className="text-blue-600 shrink-0" />
          {isExpanded && <span className="truncate">新建对话</span>}
        </button>

        <button
          type="button"
          onClick={() => navigate('/review')}
          title="新建面试复盘"
          className={[
            'w-full flex items-center justify-center gap-2 py-2.5 rounded-full font-semibold text-sm transition-all duration-200 cursor-pointer',
            'bg-gradient-to-r from-blue-600/10 via-purple-600/10 to-pink-600/10 hover:from-blue-600/15 hover:via-purple-600/15 hover:to-pink-600/15 text-purple-900 border border-purple-200/70 shadow-2xs',
            isExpanded ? 'px-4' : 'px-2',
          ].join(' ')}
        >
          <Sparkles size={15} className="text-purple-600 shrink-0" />
          {isExpanded && <span className="truncate">新建复盘</span>}
        </button>
      </div>

      {/* Navigation Group: 8 First-Class Navigation Items */}
      <nav className="flex-1 px-3 py-1 flex flex-col gap-1 overflow-y-auto overflow-x-hidden">
        {NAV_ITEMS.map(({ to, label, icon: Icon, badge }) => (
          <NavLink
            key={to}
            to={to}
            title={isExpanded ? undefined : label}
            aria-label={label}
            className={({ isActive }) =>
              [
                'flex items-center gap-3 rounded-2xl text-sm font-medium transition-all duration-150 relative cursor-pointer',
                isExpanded ? 'px-3.5 py-2.5' : 'p-2.5 justify-center',
                isActive
                  ? 'bg-blue-50 text-blue-700 font-semibold shadow-xs'
                  : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900',
              ].join(' ')
            }
          >
            <Icon size={18} className="shrink-0 text-slate-500 group-hover:text-slate-800" />
            {isExpanded && <span className="truncate">{label}</span>}
            {isExpanded && badge && (
              <span className="ml-auto text-xs font-bold px-2 py-0.5 rounded-full bg-blue-100 text-blue-700">
                {badge}
              </span>
            )}
          </NavLink>
        ))}
      </nav>

      {/* Bottom Profile Area & Popover Menu */}
      <div ref={userMenuRef} className="border-t border-slate-100 p-2.5 flex flex-col gap-1 relative">
        {/* User Card Trigger */}
        <div
          onClick={() => setUserMenuOpen((v) => !v)}
          className={[
            'flex items-center gap-2.5 p-2 rounded-2xl cursor-pointer hover:bg-slate-100 transition-all duration-150',
            userMenuOpen ? 'bg-slate-100 shadow-2xs ring-1 ring-slate-200' : '',
            isExpanded ? '' : 'justify-center',
          ].join(' ')}
          title="点击打开用户菜单与设置"
          role="button"
          aria-expanded={userMenuOpen}
        >
          <Avatar
            src={me?.avatar_url}
            name={displayName}
            colorSeed={me?.username ?? subjectId ?? ''}
            className="w-8 h-8 rounded-full ring-1 ring-slate-200"
            fallbackClassName="text-xs font-semibold"
          />
          {isExpanded && (
            <div className="flex flex-col min-w-0 flex-1">
              <span className="text-sm font-bold text-slate-800 truncate">
                {displayName}
              </span>
              <span className="text-xs text-slate-400 truncate flex items-center gap-1">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 inline-block" />
                已登录
              </span>
            </div>
          )}
        </div>

        {/* Clean Floating Popover Menu (Above Profile) */}
        {userMenuOpen && (
          <div className="absolute bottom-full left-2 mb-2 w-60 bg-white/95 backdrop-blur-xl rounded-3xl shadow-xl border border-slate-200/90 p-2 z-50 animate-in fade-in zoom-in-95 duration-150 flex flex-col gap-1 text-slate-700">
            {/* Header User Row */}
            <div className="px-3 py-2.5 border-b border-slate-100 flex items-center justify-between">
              <div className="flex items-center gap-2.5">
                <Avatar
                  src={me?.avatar_url}
                  name={displayName}
                  colorSeed={me?.username ?? subjectId ?? ''}
                  className="w-8 h-8 rounded-full"
                  fallbackClassName="text-xs font-semibold"
                />
                <div className="flex flex-col min-w-0">
                  <span className="text-sm font-bold text-slate-800 truncate max-w-[120px]">
                    {displayName}
                  </span>
                  <span className="text-xs text-slate-400 truncate">
                    {me?.username || '用户账号'}
                  </span>
                </div>
              </div>
            </div>

            {/* Menu Options */}
            <div className="py-1 flex flex-col gap-0.5">
              <button
                type="button"
                onClick={() => {
                  setUserMenuOpen(false);
                  openSettings('general');
                }}
                className="w-full flex items-center gap-2.5 px-3 py-2 rounded-2xl text-sm font-medium text-slate-700 hover:bg-slate-100 hover:text-slate-900 transition-colors text-left cursor-pointer"
              >
                <Settings size={16} className="text-slate-600" />
                <span className="flex-1">系统设置</span>
              </button>

              <button
                type="button"
                onClick={() => {
                  setUserMenuOpen(false);
                  toast.success('Interview Copilot 提供全流程求职与面试辅导。');
                }}
                className="w-full flex items-center gap-2.5 px-3 py-2 rounded-2xl text-sm font-medium text-slate-600 hover:bg-slate-100 hover:text-slate-900 transition-colors text-left cursor-pointer"
              >
                <HelpCircle size={16} className="text-slate-400" />
                <span className="flex-1">帮助与说明</span>
              </button>
            </div>

            <div className="border-t border-slate-100 pt-1 flex flex-col gap-0.5">
              <button
                type="button"
                onClick={() => {
                  setUserMenuOpen(false);
                  logout();
                }}
                className="w-full flex items-center gap-2.5 px-3 py-2 rounded-2xl text-sm font-medium text-red-600 hover:bg-red-50 transition-colors text-left cursor-pointer"
              >
                <LogOut size={16} />
                <span className="flex-1">退出登录</span>
              </button>
            </div>
          </div>
        )}
      </div>
    </aside>
  );
}
