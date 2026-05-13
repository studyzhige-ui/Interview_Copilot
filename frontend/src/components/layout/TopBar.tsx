import { useEffect, useRef, useState } from 'react';
import { LogOut, ChevronDown, UserRound } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useAuthStore } from '@/store/authStore';

const MACARON_BG = [
  'bg-macaron-peach',
  'bg-macaron-mint',
  'bg-macaron-butter',
  'bg-macaron-lavender',
  'bg-macaron-sky',
];

function pickColor(name: string): string {
  if (!name) return MACARON_BG[0];
  let h = 0;
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) >>> 0;
  return MACARON_BG[h % MACARON_BG.length];
}

export function TopBar({ pageTitle }: { pageTitle?: string }) {
  const username = useAuthStore((s) => s.username);
  const me = useAuthStore((s) => s.me);
  const fetchMe = useAuthStore((s) => s.fetchMe);
  const logout = useAuthStore((s) => s.logout);
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    fetchMe().catch(() => {});
  }, [fetchMe]);

  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, []);

  const displayName = me?.nickname || username || '?';
  const avatarUrl = me?.avatar_url;
  const initial = displayName.slice(0, 1).toUpperCase();
  const colorCls = pickColor(username ?? '');

  return (
    <header className="h-14 bg-white border-b border-stone-200 flex items-center px-5 shrink-0">
      <div className="text-sm font-medium text-stone-800">{pageTitle ?? ''}</div>
      <div className="ml-auto relative" ref={ref}>
        <button
          onClick={() => setOpen((v) => !v)}
          className="flex items-center gap-2 px-2 py-1.5 rounded-md hover:bg-stone-50"
        >
          {avatarUrl ? (
            <img
              src={avatarUrl}
              alt=""
              className="w-7 h-7 rounded-full object-cover border border-stone-200"
              onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = 'none'; }}
            />
          ) : (
            <span
              className={`w-7 h-7 rounded-full ${colorCls} text-white text-xs font-semibold flex items-center justify-center`}
            >
              {initial}
            </span>
          )}
          <span className="text-sm text-stone-700">{displayName}</span>
          <ChevronDown size={14} className="text-stone-400" />
        </button>
        {open && (
          <div className="absolute right-0 top-full mt-1 w-44 bg-white rounded-lg shadow-lg border border-stone-200 overflow-hidden z-30">
            <button
              onClick={() => {
                setOpen(false);
                navigate('/me');
              }}
              className="w-full flex items-center gap-2 px-3 py-2 text-sm text-stone-700 hover:bg-stone-50 border-b border-stone-100"
            >
              <UserRound size={14} />
              <span>个人中心</span>
            </button>
            <button
              onClick={() => {
                logout();
                window.location.href = '/auth';
              }}
              className="w-full flex items-center gap-2 px-3 py-2 text-sm text-stone-700 hover:bg-stone-50"
            >
              <LogOut size={14} />
              <span>登出</span>
            </button>
          </div>
        )}
      </div>
    </header>
  );
}
