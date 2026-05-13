import { useEffect, useState } from 'react';
import { NavLink } from 'react-router-dom';
import {
  ClipboardList,
  Mic,
  BarChart3,
  Library,
  Cpu,
  UserRound,
  Pin,
  PinOff,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react';
import { Logo } from '@/components/ui/Logo';

interface NavItem {
  to: string;
  label: string;
  icon: typeof Mic;
}

const ITEMS: NavItem[] = [
  { to: '/review',    label: '复盘',     icon: ClipboardList },
  { to: '/mock',      label: '模拟面试', icon: Mic },
  { to: '/analytics', label: '能力分析', icon: BarChart3 },
  { to: '/library',   label: '资料库',   icon: Library },
  { to: '/models',    label: '模型',     icon: Cpu },
  { to: '/me',        label: '个人中心', icon: UserRound },
];

const PIN_KEY = 'sidenav.pinned';

export function SideNav() {
  const [pinned, setPinned] = useState<boolean>(() => {
    try {
      const v = localStorage.getItem(PIN_KEY);
      return v === null ? true : v === '1'; // default: pinned (expanded)
    } catch { return true; }
  });
  const [hovering, setHovering] = useState(false);

  useEffect(() => {
    try { localStorage.setItem(PIN_KEY, pinned ? '1' : '0'); } catch { /* ignore */ }
  }, [pinned]);

  const expanded = pinned || hovering;
  const widthClass = expanded ? 'w-[220px]' : 'w-[60px]';

  return (
    <aside
      onMouseEnter={() => setHovering(true)}
      onMouseLeave={() => setHovering(false)}
      className={[
        'shrink-0 bg-white border-r border-stone-200 flex flex-col',
        'transition-[width] duration-200 ease-out',
        widthClass,
      ].join(' ')}
    >
      <div className="h-14 px-3 flex items-center gap-2 border-b border-stone-200">
        <Logo size={32} />
        {expanded && (
          <div className="text-sm font-semibold text-stone-800 truncate">Interview Copilot</div>
        )}
      </div>
      <nav className="flex-1 p-2 flex flex-col gap-1">
        {ITEMS.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            title={expanded ? undefined : label}
            className={({ isActive }) =>
              [
                'flex items-center gap-3 rounded-md text-sm transition-colors',
                expanded ? 'px-3 py-2' : 'p-2 justify-center',
                isActive
                  ? 'bg-primary-50 text-primary-700 font-medium'
                  : 'text-stone-600 hover:bg-stone-50 hover:text-stone-800',
              ].join(' ')
            }
          >
            <Icon size={18} className="shrink-0" />
            {expanded && <span className="truncate">{label}</span>}
          </NavLink>
        ))}
      </nav>
      <div className="border-t border-stone-200 p-2 flex items-center">
        <button
          onClick={() => setPinned((p) => !p)}
          title={pinned ? '取消固定（收起）' : '固定（保持展开）'}
          className="flex items-center gap-2 w-full px-2 py-1.5 rounded-md text-stone-500 hover:bg-stone-50 hover:text-stone-700 text-xs"
        >
          {pinned
            ? <>
                <PinOff size={14} className="shrink-0" />
                {expanded && <span>收起</span>}
                {expanded && <ChevronLeft size={12} className="ml-auto" />}
              </>
            : <>
                <Pin size={14} className="shrink-0" />
                {expanded && <span>固定</span>}
                {expanded && <ChevronRight size={12} className="ml-auto" />}
              </>}
        </button>
      </div>
    </aside>
  );
}
