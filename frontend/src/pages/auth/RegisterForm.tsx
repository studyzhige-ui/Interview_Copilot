import { FormEvent, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { User, Lock, Mail, KeyRound, Info } from 'lucide-react';
import { Btn } from '@/components/ui/Btn';
import { Field } from '@/components/ui/Field';
import { login, register, sendVerificationCode } from '@/api/auth';
import { useAuthStore } from '@/store/authStore';
import { registerErr, loginErr, sendCodeErr } from '@/lib/errors';
import { toast } from '@/store/uiStore';

const MIN_PWD = 6;
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

interface Props {
  /** Hop back to the login tab. Used by the inline "已注册？登录" hint. */
  onSwitchToLogin?: () => void;
}

export function RegisterForm({ onSwitchToLogin }: Props = {}) {
  const setSession = useAuthStore((s) => s.setSession);
  const navigate = useNavigate();

  const [email, setEmail] = useState('');
  const [code, setCode] = useState('');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [sending, setSending] = useState(false);
  const [registering, setRegistering] = useState(false);
  const [cooldown, setCooldown] = useState(0);
  const tickRef = useRef<number | null>(null);

  useEffect(() => () => {
    if (tickRef.current !== null) window.clearInterval(tickRef.current);
  }, []);

  const emailValid = EMAIL_RE.test(email);
  const pwdShort = password.length > 0 && password.length < MIN_PWD;
  const mismatch = confirm.length > 0 && confirm !== password;

  const canSend = emailValid && cooldown === 0 && !sending;
  const canSubmit =
    emailValid &&
    code.length === 6 &&
    username.trim().length > 0 &&
    password.length >= MIN_PWD &&
    confirm === password &&
    !registering;

  const startCooldown = (seconds: number) => {
    setCooldown(seconds);
    if (tickRef.current !== null) window.clearInterval(tickRef.current);
    tickRef.current = window.setInterval(() => {
      setCooldown((c) => {
        if (c <= 1) {
          if (tickRef.current !== null) window.clearInterval(tickRef.current);
          tickRef.current = null;
          return 0;
        }
        return c - 1;
      });
    }, 1000);
  };

  const onSendCode = async () => {
    if (!canSend) return;
    setSending(true);
    try {
      await sendVerificationCode(email, 'register');
      toast.success('验证码已发送，请查收邮箱（开发模式见后端日志）');
      startCooldown(60);
    } catch (err) {
      toast.error(sendCodeErr(err));
    } finally {
      setSending(false);
    }
  };

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!canSubmit) return;
    setRegistering(true);
    try {
      await register({
        username: username.trim(),
        password,
        email: email.trim(),
        code: code.trim(),
      });
    } catch (err) {
      toast.error(registerErr(err));
      setRegistering(false);
      return;
    }
    try {
      const tk = await login(username.trim(), password);
      setSession(tk.access_token, tk.refresh_token);
      toast.success('注册成功，已自动登录');
      navigate('/review', { replace: true });
    } catch (err) {
      toast.error(loginErr(err));
    } finally {
      setRegistering(false);
    }
  };

  return (
    <form onSubmit={onSubmit}>
      {/* Anti-enumeration UX hint: /send-code silently ignores already-
        * registered emails (no code is mailed). Tell the user up-front so
        * they don't waste 10 min wondering "为什么没收到验证码".
        *
        * Layout: 13px copy, generous padding, no inline punctuation that
        * could orphan onto its own line. The "请直接登录" link sits at the
        * end of the sentence so wrap point falls naturally before it. */}
      <div className="flex items-start gap-2.5 px-3.5 py-3 mb-5 rounded-lg bg-primary-50/70 border border-primary-100 text-[13px] leading-6 text-primary-800">
        <Info size={15} className="mt-0.5 shrink-0 text-primary-500" />
        <div className="flex-1">
          <span>已完成注册的邮箱不会再收到验证码，已有账号 </span>
          {onSwitchToLogin ? (
            <button
              type="button"
              onClick={onSwitchToLogin}
              className="underline underline-offset-2 font-medium text-primary-700 hover:text-primary-900"
            >
              直接登录 →
            </button>
          ) : (
            <span className="font-medium">直接登录</span>
          )}
        </div>
      </div>
      <Field
        label="邮箱"
        type="email"
        icon={<Mail size={16} />}
        placeholder="you@example.com"
        autoComplete="email"
        value={email}
        onChange={setEmail}
        hint={emailValid ? '点击右侧"发送验证码"' : '请输入有效邮箱'}
      />
      <div className="flex items-end gap-2 -mt-1 mb-3">
        <Field
          label="验证码"
          icon={<KeyRound size={16} />}
          placeholder="6 位数字"
          value={code}
          onChange={(v) => setCode(v.replace(/\D/g, '').slice(0, 6))}
          inputMode="numeric"
          autoComplete="one-time-code"
        />
        <div className="pb-3.5 shrink-0">
          <Btn
            kind="outline"
            size="md"
            type="button"
            onClick={onSendCode}
            disabled={!canSend}
            loading={sending}
          >
            {cooldown > 0 ? `${cooldown}s 后重发` : '发送验证码'}
          </Btn>
        </div>
      </div>
      <Field
        label="用户名"
        icon={<User size={16} />}
        placeholder="登录时使用"
        autoComplete="username"
        value={username}
        onChange={setUsername}
      />
      <Field
        label="密码"
        type="password"
        icon={<Lock size={16} />}
        placeholder={`至少 ${MIN_PWD} 位`}
        autoComplete="new-password"
        value={password}
        onChange={setPassword}
        error={pwdShort ? `密码至少 ${MIN_PWD} 位` : undefined}
      />
      <Field
        label="确认密码"
        type="password"
        icon={<Lock size={16} />}
        placeholder="再输一次"
        autoComplete="new-password"
        value={confirm}
        onChange={setConfirm}
        error={mismatch ? '两次输入不一致' : undefined}
      />
      <Btn type="submit" full loading={registering} disabled={!canSubmit}>
        注册并登录
      </Btn>
    </form>
  );
}
