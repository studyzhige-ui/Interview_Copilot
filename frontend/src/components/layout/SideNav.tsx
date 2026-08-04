import { useEffect, useState } from 'react';
import { NavLink } from 'react-router-dom';
import {
  ClipboardList,
  Mic,
  MessageSquare,
  BarChart3,
  Library,
  Cpu,
  Puzzle,
  Pin,
  PinOff,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react';
import { Logo } from '@/components/ui/Logo';
import { useEditionPolicy } from '@/hooks/useEditionPolicy';

interface NavItem {
  to: string;
  label: string;
  icon: typeof Mic;
}

interface NavGroup {
  label: string;
  items: NavItem[];
}

const GROUPS: NavGroup[] = [
  {
    label: '面试工作台',
    items: [
      { to: '/mock', label: '模拟面试', icon: Mic },
      { to: '/review', label: '面试复盘', icon: ClipboardList },
      { to: '/general-chat', label: '自由对话', icon: MessageSquare },
      { to: '/analytics', label: '能力成长', icon: BarChart3 },
    ],
  },
  {
    label: '资料',
    items: [{ to: '/library', label: '资料与记忆', icon: Library }],
  },
  {
    label: '配置',
    items: [
      { to: '/models', label: '回答模型', icon: Cpu },
      { to: '/capabilities', label: 'Skills 与 MCP', icon: Puzzle },
    ],
  },
];

const PIN_KEY = 'sidenav.pinned';

export function SideNav() {
  const edition = useEditionPolicy();
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
  const widthClass = expanded ? 'w-[64px] md:w-[240px]' : 'w-[64px]';

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
      <div className="h-16 px-3 flex items-center gap-2.5 border-b border-stone-200">
        <Logo size={34} />
        {expanded && (
          <div className="hidden md:block min-w-0">
            <div className="text-base font-semibold text-stone-800 truncate">Interview Copilot</div>
            <div className="text-[10px] uppercase tracking-wide text-stone-400">
              {edition.data?.edition ?? 'community'}
            </div>
          </div>
        )}
      </div>
      <nav className="flex-1 p-2.5 flex flex-col gap-3 overflow-y-auto">
        {GROUPS.map((group) => (
          <div key={group.label} className="flex flex-col gap-1">
            {expanded && (
              <div className="hidden md:block px-3 pt-1 text-[10px] font-medium uppercase tracking-wider text-stone-400">
                {group.label}
              </div>
            )}
            {group.items.map(({ to, label, icon: Icon }) => (
              <NavLink
                key={to}
                to={to}
                title={expanded ? undefined : label}
                aria-label={label}
                className={({ isActive }) =>
                  [
                    'flex items-center gap-3 rounded-md text-[15px] transition-colors',
                    expanded ? 'p-2.5 md:px-3 md:py-2.5 justify-center md:justify-start' : 'p-2.5 justify-center',
                    isActive
                      ? 'bg-primary-50 text-primary-700 font-medium'
                      : 'text-stone-600 hover:bg-stone-50 hover:text-stone-800',
                  ].join(' ')
                }
              >
                <Icon size={20} className="shrink-0" />
                {expanded && <span className="hidden md:block truncate">{label}</span>}
              </NavLink>
            ))}
          </div>
        ))}
      </nav>
      <div className="hidden md:flex border-t border-stone-200 p-2.5 items-center">
        <button
          onClick={() => setPinned((p) => !p)}
          title={pinned ? '取消固定（收起）' : '固定（保持展开）'}
          className="flex items-center gap-2 w-full px-2.5 py-2 rounded-md text-stone-500 hover:bg-stone-50 hover:text-stone-700 text-sm"
        >
          {pinned
            ? <>
                <PinOff size={16} className="shrink-0" />
                {expanded && <span className="hidden md:inline">收起</span>}
                {expanded && <ChevronLeft size={14} className="hidden md:block ml-auto" />}
              </>
            : <>
                <Pin size={16} className="shrink-0" />
                {expanded && <span className="hidden md:inline">固定</span>}
                {expanded && <ChevronRight size={14} className="hidden md:block ml-auto" />}
              </>}
        </button>
      </div>
    </aside>
  );
}
