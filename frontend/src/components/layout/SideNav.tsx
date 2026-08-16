import { useEffect, useRef, useState } from 'react';
import { NavLink, useNavigate } from 'react-router-dom';
import {
  Sun,
  Workflow,
  Mic2,
  FolderGit2,
  Zap,
  Settings,
  LogOut,
  HelpCircle,
  PanelLeftClose,
} from 'lucide-react';
import { Logo } from '@/components/ui/Logo';
import { useAuthStore } from '@/store/authStore';
import { Avatar } from '@/components/ui/Avatar';
import { useSettingsModalStore } from '@/store/settingsModalStore';
import { toast } from '@/store/uiStore';

interface NavItem {
  to: string;
  label: string;
  icon: typeof Sun;
  badge?: string;
}

// Exactly 4 First-Class User Areas according to Specification v0.1
const PRIMARY_NAV_ITEMS: NavItem[] = [
  { to: '/today', label: '今天', icon: Sun },
  { to: '/career', label: '求职', icon: Workflow },
  { to: '/interviews', label: '面试', icon: Mic2 },
  { to: '/materials', label: '资料', icon: FolderGit2 },
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

  const isExpanded = !collapsed || hovering;
  const displayName = me?.nickname || me?.username || '用户';

  return (
    <aside
      onMouseEnter={() => collapsed && setHovering(true)}
      onMouseLeave={() => collapsed && setHovering(false)}
      className={[
        'shrink-0 h-full flex flex-col justify-between select-none z-30 transition-all duration-300 ease-out border-r bg-white/95 backdrop-blur-xl border-slate-200/80 shadow-xs',
        isExpanded ? 'w-[210px]' : 'w-[68px]',
      ].join(' ')}
    >
      {/* Top Brand Logo */}
      <div>
        <div className="h-16 px-4 flex items-center justify-between border-b border-slate-100/80">
          <NavLink
            to="/today"
            className="flex items-center gap-2.5 overflow-hidden group py-1"
          >
            <Logo size={28} />
            {isExpanded && (
              <div className="flex flex-col min-w-0 transition-opacity duration-200">
                <span className="font-black text-sm tracking-tight text-slate-900 leading-tight">
                  Interview Copilot
                </span>
                <span className="text-[10px] font-mono font-medium text-slate-400">
                  v0.1 AI OS
                </span>
              </div>
            )}
          </NavLink>

          {isExpanded && (
            <button
              type="button"
              onClick={toggleCollapsed}
              title={collapsed ? '锁定展开侧边栏' : '折叠侧边栏'}
              className="p-1.5 rounded-xl text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition-colors cursor-pointer"
            >
              <PanelLeftClose size={15} />
            </button>
          )}
        </div>

        {/* 4 Primary Navigation Items */}
        <nav className="p-2.5 space-y-1">
          {PRIMARY_NAV_ITEMS.map((item) => {
            const Icon = item.icon;
            return (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) =>
                  [
                    'relative flex items-center gap-3 px-3 py-2.5 rounded-2xl text-xs font-bold transition-all duration-150 group cursor-pointer',
                    isActive
                      ? 'bg-blue-50/90 text-blue-600 shadow-2xs font-extrabold ring-1 ring-blue-200/80'
                      : 'text-slate-600 hover:bg-slate-100/70 hover:text-slate-900',
                    !isExpanded && 'justify-center px-2',
                  ]
                    .filter(Boolean)
                    .join(' ')
                }
              >
                <Icon
                  size={18}
                  className="shrink-0 group-hover:scale-110 transition-transform"
                />
                {isExpanded && (
                  <span className="truncate tracking-tight">{item.label}</span>
                )}
              </NavLink>
            );
          })}
        </nav>
      </div>

      {/* Secondary Bottom Navigation (Activity Center & User Settings) */}
      <div className="p-2.5 border-t border-slate-100/80 space-y-1">
        {/* Activity Center (Secondary Area) */}
        <NavLink
          to="/activities"
          className={({ isActive }) =>
            [
              'relative flex items-center gap-3 px-3 py-2.5 rounded-2xl text-xs font-semibold transition-all duration-150 group cursor-pointer',
              isActive
                ? 'bg-purple-50 text-purple-700 shadow-2xs font-bold ring-1 ring-purple-200'
                : 'text-slate-500 hover:bg-slate-100/70 hover:text-slate-900',
              !isExpanded && 'justify-center px-2',
            ]
              .filter(Boolean)
              .join(' ')
          }
        >
          <Zap size={17} className="shrink-0 text-purple-600 group-hover:scale-110 transition-transform" />
          {isExpanded && <span className="truncate">活动中心</span>}
        </NavLink>

        {/* User Profile & Settings Trigger */}
        <div ref={userMenuRef} className="relative">
          <button
            type="button"
            onClick={() => setUserMenuOpen((prev) => !prev)}
            className={[
              'w-full flex items-center gap-3 p-2 rounded-2xl hover:bg-slate-100/80 transition-all text-left cursor-pointer border border-transparent hover:border-slate-200',
              !isExpanded && 'justify-center p-1.5',
            ].join(' ')}
          >
            <Avatar name={displayName} className="w-7 h-7 rounded-xl text-xs shrink-0" />
            {isExpanded && (
              <div className="min-w-0 flex-1">
                <div className="text-xs font-bold text-slate-800 truncate leading-tight">
                  {displayName}
                </div>
                <div className="text-[10px] text-slate-400 font-mono truncate">
                  ID: #{subjectId || '1001'}
                </div>
              </div>
            )}
          </button>

          {/* User Popover Menu */}
          {userMenuOpen && (
            <div className="absolute left-full bottom-0 ml-2 w-48 bg-white rounded-2xl shadow-lg border border-slate-200/90 py-1.5 z-50 animate-in fade-in duration-150">
              <div className="px-3.5 py-2 border-b border-slate-100">
                <div className="text-xs font-bold text-slate-900 truncate">{displayName}</div>
                <div className="text-[10px] text-slate-400">个人工作台</div>
              </div>

              <button
                type="button"
                onClick={() => {
                  setUserMenuOpen(false);
                  openSettings('general');
                }}
                className="w-full px-3.5 py-2 text-xs text-slate-700 hover:bg-slate-50 flex items-center gap-2 text-left cursor-pointer transition-colors"
              >
                <Settings size={14} className="text-slate-500" />
                <span>系统设置</span>
              </button>

              <button
                type="button"
                onClick={() => {
                  setUserMenuOpen(false);
                  toast.info('Interview Copilot v0.1 - AI 驱动的个人求职操作系统');
                }}
                className="w-full px-3.5 py-2 text-xs text-slate-700 hover:bg-slate-50 flex items-center gap-2 text-left cursor-pointer transition-colors"
              >
                <HelpCircle size={14} className="text-slate-500" />
                <span>使用帮助与关于</span>
              </button>

              <div className="my-1 border-t border-slate-100" />

              <button
                type="button"
                onClick={() => {
                  setUserMenuOpen(false);
                  logout();
                  navigate('/auth');
                }}
                className="w-full px-3.5 py-2 text-xs text-red-600 hover:bg-red-50 flex items-center gap-2 text-left cursor-pointer transition-colors"
              >
                <LogOut size={14} />
                <span>退出登录</span>
              </button>
            </div>
          )}
        </div>
      </div>
    </aside>
  );
}
