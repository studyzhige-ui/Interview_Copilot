import { FormEvent, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { User, Lock } from 'lucide-react';
import { Btn } from '@/components/ui/Btn';
import { Field } from '@/components/ui/Field';
import { login } from '@/api/auth';
import { useAuthStore } from '@/store/authStore';
import { loginErr } from '@/lib/errors';
import { toast } from '@/store/uiStore';

const MIN_PWD = 6;

export function LoginForm() {
  const setSession = useAuthStore((s) => s.setSession);
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
      navigate('/review', { replace: true });
    } catch (err) {
      toast.error(loginErr(err));
    } finally {
      setLoading(false);
    }
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
          disabled
          className="cursor-not-allowed text-stone-400"
          title="即将上线"
        >
          忘记密码？
        </button>
      </div>
      <Btn type="submit" full loading={loading} disabled={!canSubmit}>
        登录
      </Btn>
    </form>
  );
}
