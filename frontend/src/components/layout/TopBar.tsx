import { useEffect, useRef, useState } from 'react';
import { LogOut, ChevronDown, UserRound, Sparkles, Settings } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useAuthStore } from '@/store/authStore';
import { Avatar } from '@/components/ui/Avatar';
import { useSettingsModalStore } from '@/store/settingsModalStore';

export function TopBar({ pageTitle }: { pageTitle?: string }) {
  const subjectId = useAuthStore((s) => s.subjectId);
  const me = useAuthStore((s) => s.me);
  const fetchMe = useAuthStore((s) => s.fetchMe);
  const logout = useAuthStore((s) => s.logout);
  const openSettings = useSettingsModalStore((s) => s.openModal);
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

  const displayName = me?.nickname || me?.username || '用户';
  const avatarUrl = me?.avatar_url;

  return (
    <header className="h-16 bg-white/80 backdrop-blur-md border-b border-slate-200/70 flex items-center px-6 shrink-0 justify-between z-20">
      <div className="flex items-center gap-3">
        <h1 className="text-base font-semibold text-slate-800 tracking-tight flex items-center gap-2">
          {pageTitle ?? ''}
        </h1>
      </div>

      <div className="flex items-center gap-3 ml-auto">
        <div className="hidden sm:flex items-center gap-1.5 px-3 py-1 rounded-full bg-blue-50/80 border border-blue-100/80 text-blue-700 text-xs font-medium">
          <Sparkles size={13} className="text-blue-600" />
          <span>AI 实时连接中</span>
        </div>

        <div className="relative" ref={ref}>
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            className="flex items-center gap-2.5 px-2.5 py-1.5 rounded-full hover:bg-slate-100/80 transition-colors"
          >
            <Avatar
              src={avatarUrl}
              name={displayName}
              colorSeed={me?.username ?? subjectId ?? ''}
              className="w-8 h-8 rounded-full ring-1 ring-slate-200"
              fallbackClassName="text-xs font-semibold"
            />
            <span className="text-sm font-medium text-slate-700 hidden sm:inline">
              {displayName}
            </span>
            <ChevronDown size={14} className="text-slate-400" />
          </button>

          {open && (
            <div className="absolute right-0 top-full mt-1.5 w-48 bg-white rounded-2xl shadow-xl border border-slate-200/90 p-1.5 z-40 animate-in fade-in zoom-in-95 duration-150">
              <div className="px-3 py-2 border-b border-slate-100 mb-1">
                <p className="text-sm font-semibold text-slate-800 truncate">{displayName}</p>
                <p className="text-xs text-slate-400 truncate">{me?.email ?? '已登录'}</p>
              </div>

              <button
                type="button"
                onClick={() => {
                  setOpen(false);
                  openSettings('general');
                }}
                className="w-full flex items-center gap-2.5 px-3 py-2 rounded-xl text-xs font-medium text-slate-700 hover:bg-slate-50 transition-colors"
              >
                <Settings size={15} className="text-slate-500" />
                <span>系统设置</span>
              </button>

              <button
                type="button"
                onClick={() => {
                  setOpen(false);
                  navigate('/me');
                }}
                className="w-full flex items-center gap-2.5 px-3 py-2 rounded-xl text-xs font-medium text-slate-700 hover:bg-slate-50 transition-colors"
              >
                <UserRound size={15} className="text-slate-500" />
                <span>个人中心</span>
              </button>

              <button
                type="button"
                onClick={async () => {
                  await logout();
                  window.location.href = '/auth';
                }}
                className="w-full flex items-center gap-2.5 px-3 py-2 rounded-xl text-xs font-medium text-red-600 hover:bg-red-50 transition-colors"
              >
                <LogOut size={15} className="text-red-500" />
                <span>退出登录</span>
              </button>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
