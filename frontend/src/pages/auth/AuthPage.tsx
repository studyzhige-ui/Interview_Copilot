import { useState } from 'react';
import { Logo } from '@/components/ui/Logo';
import { LoginForm } from './LoginForm';
import { RegisterForm } from './RegisterForm';
import { ResetPasswordForm } from './ResetPasswordForm';

type Tab = 'login' | 'register' | 'reset';

export function AuthPage() {
  const [tab, setTab] = useState<Tab>('login');

  return (
    <div className="min-h-screen flex items-center justify-center gemini-ambient-bg px-4 select-none relative overflow-hidden">
      {/* Background ambient glow circle */}
      <div className="absolute w-[500px] h-[500px] rounded-full bg-gradient-to-tr from-blue-400/15 via-purple-400/10 to-pink-400/10 blur-3xl pointer-events-none -top-20 -left-20" />
      <div className="absolute w-[400px] h-[400px] rounded-full bg-gradient-to-br from-indigo-400/10 to-blue-400/15 blur-3xl pointer-events-none -bottom-20 -right-20" />

      <div className="w-full max-w-md bg-white/90 backdrop-blur-2xl rounded-3xl shadow-xl border border-slate-200/80 p-8 md:p-10 relative z-10 animate-in fade-in zoom-in-95 duration-200">
        {/* Brand Header */}
        <div className="flex items-center gap-3.5 mb-8">
          <Logo size={40} />
          <div>
            <div className="text-xl font-bold tracking-tight text-slate-900 flex items-center gap-1.5">
              <span>Interview Copilot</span>
            </div>
            <div className="text-xs font-medium text-slate-400 mt-0.5">
              AI 全流程求职与面试辅导平台
            </div>
          </div>
        </div>

        {tab === 'reset' ? (
          <div className="mb-6 pb-3 border-b border-slate-100 text-base font-semibold text-slate-800">
            重置密码
          </div>
        ) : (
          <div className="flex p-1 bg-slate-100 rounded-2xl mb-6 border border-slate-200/60">
            <TabBtn active={tab === 'login'} onClick={() => setTab('login')}>
              登录账号
            </TabBtn>
            <TabBtn active={tab === 'register'} onClick={() => setTab('register')}>
              注册新用户
            </TabBtn>
          </div>
        )}

        {tab === 'login' && (
          <LoginForm
            onSwitchToRegister={() => setTab('register')}
            onForgotPassword={() => setTab('reset')}
          />
        )}
        {tab === 'register' && <RegisterForm onSwitchToLogin={() => setTab('login')} />}
        {tab === 'reset' && <ResetPasswordForm onBackToLogin={() => setTab('login')} />}
      </div>
    </div>
  );
}

function TabBtn({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={[
        'flex-1 py-2 text-xs font-semibold rounded-xl transition-all duration-150 cursor-pointer',
        active
          ? 'bg-white text-blue-700 shadow-xs'
          : 'text-slate-500 hover:text-slate-900',
      ].join(' ')}
    >
      {children}
    </button>
  );
}
