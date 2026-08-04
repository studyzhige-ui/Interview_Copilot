import { FormEvent, useState } from 'react';
import { ArrowLeft, Info, KeyRound, Lock, Mail } from 'lucide-react';
import { resetPassword } from '@/api/auth';
import { Btn } from '@/components/ui/Btn';
import { Field } from '@/components/ui/Field';
import { resetPasswordErr } from '@/lib/errors';
import { toast } from '@/store/uiStore';
import { useVerificationCode } from './useVerificationCode';

const MIN_PWD = 6;
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

interface Props {
  onBackToLogin: () => void;
}

export function ResetPasswordForm({ onBackToLogin }: Props) {
  const [email, setEmail] = useState('');
  const [code, setCode] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [resetting, setResetting] = useState(false);
  const { sending, cooldown, send } = useVerificationCode();

  const emailValid = EMAIL_RE.test(email);
  const pwdShort = password.length > 0 && password.length < MIN_PWD;
  const mismatch = confirm.length > 0 && confirm !== password;
  const canSend = emailValid && cooldown === 0 && !sending;
  const canSubmit =
    emailValid &&
    code.length === 6 &&
    password.length >= MIN_PWD &&
    confirm === password &&
    !resetting;

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    if (!canSubmit) return;
    setResetting(true);
    try {
      const result = await resetPassword(email.trim(), code, password);
      toast.success(result.message);
      onBackToLogin();
    } catch (error) {
      toast.error(resetPasswordErr(error));
    } finally {
      setResetting(false);
    }
  };

  return (
    <form onSubmit={onSubmit}>
      <div className="flex items-start gap-2.5 px-3.5 py-3 mb-5 rounded-lg bg-primary-50/70 border border-primary-100 text-[13px] leading-6 text-primary-800">
        <Info size={15} className="mt-0.5 shrink-0 text-primary-500" />
        <span>如果邮箱已注册，我们会发送重置验证码。验证码仅能使用一次。</span>
      </div>
      <Field
        label="注册邮箱"
        type="email"
        icon={<Mail size={16} />}
        placeholder="you@example.com"
        autoComplete="email"
        value={email}
        onChange={setEmail}
        hint={emailValid ? '点击右侧“发送验证码”' : '请输入有效邮箱'}
      />
      <div className="flex items-end gap-2 -mt-1 mb-3">
        <Field
          label="验证码"
          icon={<KeyRound size={16} />}
          placeholder="6 位数字"
          value={code}
          onChange={(value) => setCode(value.replace(/\D/g, '').slice(0, 6))}
          inputMode="numeric"
          autoComplete="one-time-code"
        />
        <div className="pb-3.5 shrink-0">
          <Btn
            kind="outline"
            size="md"
            type="button"
            onClick={() => send(email, 'reset_password', '如果邮箱已注册，验证码已发送')}
            disabled={!canSend}
            loading={sending}
          >
            {cooldown > 0 ? `${cooldown}s 后重发` : '发送验证码'}
          </Btn>
        </div>
      </div>
      <Field
        label="新密码"
        type="password"
        icon={<Lock size={16} />}
        placeholder={`至少 ${MIN_PWD} 位`}
        autoComplete="new-password"
        value={password}
        onChange={setPassword}
        error={pwdShort ? `密码至少 ${MIN_PWD} 位` : undefined}
      />
      <Field
        label="确认新密码"
        type="password"
        icon={<Lock size={16} />}
        placeholder="再输一次"
        autoComplete="new-password"
        value={confirm}
        onChange={setConfirm}
        error={mismatch ? '两次输入不一致' : undefined}
      />
      <Btn type="submit" full loading={resetting} disabled={!canSubmit}>
        重置密码
      </Btn>
      <div className="mt-4 text-center text-xs">
        <button
          type="button"
          onClick={onBackToLogin}
          className="inline-flex items-center gap-1 text-primary-600 hover:text-primary-800 underline underline-offset-2 font-medium"
        >
          <ArrowLeft size={13} />
          返回登录
        </button>
      </div>
    </form>
  );
}
