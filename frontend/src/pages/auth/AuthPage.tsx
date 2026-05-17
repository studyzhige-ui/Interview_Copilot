import { useState } from 'react';
import { Logo } from '@/components/ui/Logo';
import { LoginForm } from './LoginForm';
import { RegisterForm } from './RegisterForm';

type Tab = 'login' | 'register';

export function AuthPage() {
  const [tab, setTab] = useState<Tab>('login');

  return (
    <div className="min-h-screen flex items-center justify-center bg-cream-50 px-4">
      <div className="w-full max-w-md bg-white rounded-xl shadow-md border border-stone-200 p-8">
        <div className="flex items-center gap-3 mb-6">
          <Logo size={36} />
          <div>
            <div className="text-lg font-semibold text-stone-800">Interview Copilot</div>
            <div className="text-xs text-stone-500">面试复盘 / 模拟训练 / 能力分析</div>
          </div>
        </div>

        <div className="flex gap-1 p-1 bg-stone-100 rounded-md mb-6">
          <TabBtn active={tab === 'login'} onClick={() => setTab('login')}>登录</TabBtn>
          <TabBtn active={tab === 'register'} onClick={() => setTab('register')}>注册</TabBtn>
        </div>

        {tab === 'login'
          ? <LoginForm onSwitchToRegister={() => setTab('register')} />
          : <RegisterForm onSwitchToLogin={() => setTab('login')} />}
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
        'flex-1 py-1.5 text-sm rounded transition-colors',
        active
          ? 'bg-white text-stone-800 shadow-xs font-medium'
          : 'text-stone-500 hover:text-stone-700',
      ].join(' ')}
    >
      {children}
    </button>
  );
}
