import { useEffect, useState } from 'react';
import { LogOut, Save, RefreshCw, AlertCircle, CheckCircle2 } from 'lucide-react';
import { Btn } from '@/components/ui/Btn';
import { Field } from '@/components/ui/Field';
import { Pill } from '@/components/ui/Pill';
import { Spinner } from '@/components/ui/Spinner';
import { toast } from '@/store/uiStore';
import { getMe, updateMe, type MeResponse } from '@/api/auth';
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

export function ProfilePage() {
  const logout = useAuthStore((s) => s.logout);
  const setStoreMe = useAuthStore((s) => s.setMe);
  const [me, setMe] = useState<MeResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [nickname, setNickname] = useState('');
  const [avatarUrl, setAvatarUrl] = useState('');
  const [bio, setBio] = useState('');

  const refresh = async () => {
    setLoading(true);
    try {
      const m = await getMe();
      setMe(m);
      setStoreMe(m);
      setNickname(m.nickname ?? '');
      setAvatarUrl(m.avatar_url ?? '');
      setBio(m.bio ?? '');
    } catch {
      toast.error('个人信息加载失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { refresh(); }, []);

  const dirty =
    !!me &&
    (nickname !== (me.nickname ?? '') ||
      avatarUrl !== (me.avatar_url ?? '') ||
      bio !== (me.bio ?? ''));

  const onSave = async () => {
    setSaving(true);
    try {
      const next = await updateMe({
        nickname: nickname.trim(),
        avatar_url: avatarUrl.trim(),
        bio: bio.trim(),
      });
      setMe(next);
      setStoreMe(next);
      toast.success('已保存');
    } catch {
      toast.error('保存失败');
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="p-6 flex items-center gap-2 text-stone-500 text-sm">
        <Spinner size={14} /> 载入中...
      </div>
    );
  }

  if (!me) return null;

  const initial = (me.nickname || me.username || '?').slice(0, 1).toUpperCase();
  const color = pickColor(me.username);
  const created = me.created_at?.slice(0, 19).replace('T', ' ');

  return (
    <div className="p-6 max-w-3xl mx-auto">
      <div className="bg-white rounded-xl border border-stone-200 p-6 shadow-xs">
        <div className="flex items-center gap-4">
          {avatarUrl ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={avatarUrl}
              alt="头像"
              className="w-20 h-20 rounded-full object-cover border border-stone-200"
              onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = 'none'; }}
            />
          ) : (
            <div
              className={`w-20 h-20 rounded-full ${color} text-white text-3xl font-semibold flex items-center justify-center`}
            >
              {initial}
            </div>
          )}
          <div className="flex-1 min-w-0">
            <div className="text-xl font-semibold text-stone-800">
              {me.nickname || me.username}
            </div>
            <div className="text-xs text-stone-500 mt-0.5">@{me.username}</div>
            <div className="mt-1.5 flex items-center gap-2">
              {me.email_verified ? (
                <Pill tone="success">
                  <CheckCircle2 size={10} /> 邮箱已验证
                </Pill>
              ) : (
                <Pill tone="warn">
                  <AlertCircle size={10} /> 邮箱未验证
                </Pill>
              )}
              <span className="text-[11px] text-stone-400">加入于 {created || '—'}</span>
            </div>
          </div>
          <button
            onClick={refresh}
            className="p-2 rounded-md text-stone-500 hover:bg-stone-100"
            title="刷新"
          >
            <RefreshCw size={14} />
          </button>
        </div>

        <hr className="my-6 border-stone-100" />

        <div className="space-y-1">
          <Field
            label="昵称"
            placeholder="给自己起个昵称"
            value={nickname}
            onChange={setNickname}
            maxLength={64}
            hint="将显示在 TopBar 和复盘记录中"
          />
          <Field
            label="头像 URL"
            placeholder="https://... 留空则用首字母圆形头像"
            value={avatarUrl}
            onChange={setAvatarUrl}
            maxLength={512}
            hint="支持任意可公开访问的图片地址（http/https）"
          />
          <div className="block mb-3.5">
            <div className="text-xs font-medium text-stone-700 mb-1.5">个人简介</div>
            <textarea
              value={bio}
              onChange={(e) => setBio(e.target.value)}
              maxLength={2000}
              rows={4}
              placeholder="一句话介绍你自己（求职方向、技术栈、亮点等）"
              className="w-full bg-stone-50 border border-stone-200 rounded-md outline-none text-sm text-stone-800 placeholder:text-stone-400 focus:border-primary-300 focus:ring-2 focus:ring-primary-300/30 px-3 py-2.5 resize-none"
            />
            <div className="text-[11px] text-stone-400 mt-1 text-right">{bio.length}/2000</div>
          </div>
          <div className="block mb-3.5">
            <div className="text-xs font-medium text-stone-700 mb-1.5">邮箱（只读）</div>
            <div className="px-3 py-2.5 bg-stone-100 border border-stone-200 rounded-md text-sm text-stone-600">
              {me.email ?? '未设置'}
            </div>
            <div className="text-[11px] text-stone-400 mt-1">
              更换邮箱需要邮箱验证流程，将在后续版本支持
            </div>
          </div>
        </div>

        <div className="mt-6 flex items-center gap-2">
          <Btn
            icon={<Save size={14} />}
            onClick={onSave}
            disabled={!dirty || saving}
            loading={saving}
          >
            保存修改
          </Btn>
          {dirty && <span className="text-xs text-warning-700">有未保存的修改</span>}
          <Btn
            kind="outline"
            className="ml-auto"
            icon={<LogOut size={14} />}
            onClick={() => {
              logout();
              window.location.href = '/auth';
            }}
          >
            登出
          </Btn>
        </div>
      </div>
    </div>
  );
}
