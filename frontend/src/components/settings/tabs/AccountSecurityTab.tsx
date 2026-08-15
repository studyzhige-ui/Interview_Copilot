import { useState } from 'react';
import { Trash2, LogOut, User } from 'lucide-react';
import { useAuthStore } from '@/store/authStore';
import { toast } from '@/store/uiStore';
import { Btn } from '@/components/ui/Btn';
import { updateMe } from '@/api/auth';
import { extractErr } from '@/api/client';
import { useEditionPolicy } from '@/hooks/useEditionPolicy';

export function AccountSecurityTab() {
  const me = useAuthStore((s) => s.me);
  const logout = useAuthStore((s) => s.logout);
  const fetchMe = useAuthStore((s) => s.fetchMe);
  const edition = useEditionPolicy();

  const [nickname, setNickname] = useState(me?.nickname || '');
  const [bio, setBio] = useState(me?.bio || '');
  const [savingProfile, setSavingProfile] = useState(false);

  const handleUpdateProfile = async (e: React.FormEvent) => {
    e.preventDefault();
    setSavingProfile(true);
    try {
      await updateMe({
        nickname: nickname.trim() || undefined,
        bio: bio.trim() || undefined,
      });
      await fetchMe();
      toast.success('个人资料已成功更新');
    } catch (err) {
      toast.error(extractErr(err));
    } finally {
      setSavingProfile(false);
    }
  };

  const handleClearCache = () => {
    if (window.confirm('确定要清理本地缓存吗？这不会删除你的云端复盘记录与求职档案。')) {
      localStorage.clear();
      toast.success('本地缓存已清理完成');
      setTimeout(() => window.location.reload(), 500);
    }
  };

  return (
    <div className="space-y-6 text-slate-800 animate-in fade-in duration-200">
      <div>
        <h3 className="text-lg font-bold text-slate-900 tracking-tight">账户与安全设置</h3>
        <p className="text-xs text-slate-500 mt-1">管理你的个人信息展示、账户版本权益及本地数据缓存。</p>
      </div>

      {/* Account Info Card */}
      <div className="p-4 rounded-2xl bg-slate-50 border border-slate-200/80 flex items-center justify-between gap-4">
        <div className="flex items-center gap-3.5">
          <div className="w-12 h-12 rounded-2xl bg-gradient-to-tr from-blue-500 to-indigo-600 text-white flex items-center justify-center font-bold text-lg shadow-sm">
            {me?.username?.slice(0, 1).toUpperCase() || 'U'}
          </div>
          <div>
            <div className="text-sm font-bold text-slate-900 flex items-center gap-2">
              <span>{me?.username || '当前用户'}</span>
              <span className="text-[11px] px-2 py-0.5 rounded-full bg-blue-100 text-blue-800 font-semibold">
                {edition.data?.edition === 'cloud' ? 'Pro 订阅版' : '社区版'}
              </span>
            </div>
            <div className="text-xs text-slate-500 mt-0.5">
              {me?.email || '已绑定本地安全加密会话'}
            </div>
          </div>
        </div>

        <Btn
          kind="ghost"
          size="sm"
          onClick={logout}
          className="text-red-600 hover:bg-red-50 hover:text-red-700"
        >
          <LogOut size={14} />
          <span>退出登录</span>
        </Btn>
      </div>

      {/* Profile Info Form */}
      <form onSubmit={handleUpdateProfile} className="space-y-3 pt-2">
        <div className="text-xs font-bold text-slate-500 uppercase tracking-wider flex items-center gap-1.5">
          <User size={13} className="text-blue-600" />
          <span>基本展示信息</span>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div className="space-y-1.5">
            <label className="text-sm font-semibold text-slate-700">展示昵称</label>
            <input
              type="text"
              placeholder="请输入自定义称呼"
              value={nickname}
              onChange={(e) => setNickname(e.target.value)}
              className="w-full px-3.5 py-2.5 bg-slate-50 border border-slate-200/80 rounded-2xl text-sm text-slate-800 placeholder-slate-400 outline-none focus:border-blue-400 focus:bg-white transition-all"
            />
          </div>
          <div className="space-y-1.5">
            <label className="text-sm font-semibold text-slate-700">一句话个人介绍 / 目标岗位</label>
            <input
              type="text"
              placeholder="例如：3年资深后端架构师，冲刺一线大厂"
              value={bio}
              onChange={(e) => setBio(e.target.value)}
              className="w-full px-3.5 py-2.5 bg-slate-50 border border-slate-200/80 rounded-2xl text-sm text-slate-800 placeholder-slate-400 outline-none focus:border-blue-400 focus:bg-white transition-all"
            />
          </div>
        </div>

        <div className="flex justify-end pt-1">
          <Btn
            type="submit"
            kind="primary"
            size="sm"
            loading={savingProfile}
          >
            保存资料修改
          </Btn>
        </div>
      </form>

      {/* Storage & Privacy Controls */}
      <div className="pt-4 border-t border-slate-100 flex items-center justify-between">
        <div className="space-y-0.5">
          <div className="text-sm font-semibold text-slate-800 flex items-center gap-1.5">
            <Trash2 size={15} className="text-slate-500" />
            <span>本地客户端缓存重置</span>
          </div>
          <div className="text-xs text-slate-500">清除浏览器本地 UI 缓存与草稿状态</div>
        </div>
        <Btn kind="ghost" size="sm" onClick={handleClearCache}>
          重置缓存
        </Btn>
      </div>
    </div>
  );
}
