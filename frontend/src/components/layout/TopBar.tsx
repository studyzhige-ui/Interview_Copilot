import { useEffect, useRef, useState } from 'react';
import { LogOut, ChevronDown, UserRound } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useAuthStore } from '@/store/authStore';
import { Avatar } from '@/components/ui/Avatar';

export function TopBar({ pageTitle }: { pageTitle?: string }) {
  const subjectId = useAuthStore((s) => s.subjectId);
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

  const displayName = me?.nickname || me?.username || '?';
  const avatarUrl = me?.avatar_url;

  return (
    <header className="h-16 bg-white border-b border-stone-200 flex items-center px-6 shrink-0">
      <div className="text-base font-medium text-stone-800">{pageTitle ?? ''}</div>
      <div className="ml-auto relative" ref={ref}>
        <button
          onClick={() => setOpen((v) => !v)}
          className="flex items-center gap-2.5 px-2.5 py-1.5 rounded-md hover:bg-stone-50"
        >
          <Avatar
            src={avatarUrl}
            name={displayName}
            colorSeed={me?.username ?? subjectId ?? ''}
            className="w-8 h-8"
            fallbackClassName="text-sm"
          />
          <span className="text-sm text-stone-700">{displayName}</span>
          <ChevronDown size={16} className="text-stone-400" />
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
              onClick={async () => {
                // Await so the backend revocation lands before the page nav
                // cancels the in-flight POST. logout() always resolves.
                await logout();
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
