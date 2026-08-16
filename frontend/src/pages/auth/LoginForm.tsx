import { FormEvent, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { User, Lock, Sparkles } from 'lucide-react';
import { Btn } from '@/components/ui/Btn';
import { Field } from '@/components/ui/Field';
import { login } from '@/api/auth';
import { useAuthStore } from '@/store/authStore';
import { loginErr } from '@/lib/errors';
import { toast } from '@/store/uiStore';

const MIN_PWD = 6;

interface Props {
  /** Hop over to the register tab. */
  onSwitchToRegister?: () => void;
  onForgotPassword?: () => void;
}

export function LoginForm({ onSwitchToRegister, onForgotPassword }: Props = {}) {
  const setSession = useAuthStore((s) => s.setSession);
  const setMe = useAuthStore((s) => s.setMe);
  const navigate = useNavigate();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);

  const canSubmit =
    username.trim().length > 0 && password.length >= MIN_PWD && !loading;

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!canSubmit) return;
    setLoading(true);
    try {
      const tk = await login(username.trim(), password);
      setSession(tk.access_token, tk.refresh_token);
      navigate('/today', { replace: true });
    } catch (err) {
      toast.error(loginErr(err));
    } finally {
      setLoading(false);
    }
  };

  const handleDemoPreview = () => {
    // Generate valid base64 payload for demo preview without needing backend
    const payload = btoa(unescape(encodeURIComponent(JSON.stringify({ sub: '1001', username: '体验官', nickname: '体验官 · Alex' }))));
    const mockJwt = `eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.${payload}.mockSignature`;
    setSession(mockJwt, mockJwt);
    setMe({
      username: '体验官',
      email: 'demo@interview-copilot.ai',
      nickname: '体验官 · Alex',
      avatar_url: null,
      bio: '求职操作系统设计体验官',
      default_execution_mode: 'standard',
      email_verified: true,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    });
    toast.success('已进入前端纯享设计体验模式（免启动后端）');
    navigate('/today', { replace: true });
  };

  return (
    <form onSubmit={onSubmit}>
      <Field
        label="用户名"
        icon={<User size={16} />}
        placeholder="请输入用户名"
        autoComplete="username"
        value={username}
        onChange={setUsername}
      />
      <Field
        label="密码"
        type="password"
        icon={<Lock size={16} />}
        placeholder={`至少 ${MIN_PWD} 位`}
        autoComplete="current-password"
        value={password}
        onChange={setPassword}
      />
      <div className="flex items-center justify-between text-xs text-stone-400 mb-4">
        <span>—</span>
        <button
          type="button"
          onClick={onForgotPassword}
          className="text-blue-600 hover:text-blue-800 underline underline-offset-2 cursor-pointer"
        >
          忘记密码？
        </button>
      </div>

      <div className="space-y-2.5">
        <Btn type="submit" full loading={loading} disabled={!canSubmit}>
          登录系统
        </Btn>

        {/* Demo Pure-Frontend Design Preview Button */}
        <button
          type="button"
          onClick={handleDemoPreview}
          className="w-full py-2.5 px-4 rounded-2xl bg-blue-50 hover:bg-blue-100 text-blue-700 text-xs font-bold transition-all flex items-center justify-center gap-1.5 border border-blue-200/80 cursor-pointer shadow-2xs active:scale-98"
        >
          <Sparkles size={14} className="text-blue-600" />
          <span>⚡ 纯前端免后端一键体验设计</span>
        </button>
      </div>

      {onSwitchToRegister && (
        <div className="mt-4 text-center text-xs text-stone-500">
          还没账号？
          <button
            type="button"
            onClick={onSwitchToRegister}
            className="ml-1 text-blue-600 hover:text-blue-800 underline underline-offset-2 font-medium cursor-pointer"
          >
            去注册
          </button>
        </div>
      )}
    </form>
  );
}
