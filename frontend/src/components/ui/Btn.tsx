import { ButtonHTMLAttributes, ReactNode } from 'react';

type Kind = 'primary' | 'secondary' | 'ghost' | 'outline' | 'danger' | 'sparkle' | 'subtle';
type Size = 'sm' | 'md' | 'lg' | 'icon';

interface BtnProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'type'> {
  kind?: Kind;
  size?: Size;
  icon?: ReactNode;
  full?: boolean;
  pill?: boolean;
  loading?: boolean;
  type?: 'button' | 'submit' | 'reset';
}

const kindCls: Record<Kind, string> = {
  primary:
    'bg-blue-600 text-white hover:bg-blue-700 shadow-sm shadow-blue-500/20 active:scale-[0.98] disabled:bg-blue-300 disabled:shadow-none',
  sparkle:
    'bg-gradient-to-r from-blue-600 via-purple-600 to-rose-500 text-white hover:opacity-95 shadow-md shadow-purple-500/25 active:scale-[0.98] disabled:opacity-50 disabled:shadow-none',
  secondary:
    'bg-emerald-600 text-white hover:bg-emerald-700 shadow-sm shadow-emerald-500/20 active:scale-[0.98] disabled:bg-emerald-300 disabled:shadow-none',
  ghost:
    'bg-transparent text-slate-700 hover:bg-slate-100 hover:text-slate-900 active:bg-slate-200/70 disabled:opacity-40',
  subtle:
    'bg-slate-100 text-slate-700 hover:bg-slate-200 hover:text-slate-900 active:bg-slate-300/70 disabled:opacity-40',
  outline:
    'bg-white text-slate-700 border border-slate-200 hover:bg-slate-50 hover:border-slate-300 hover:text-slate-900 shadow-xs active:bg-slate-100 disabled:opacity-50',
  danger:
    'bg-red-500 text-white hover:bg-red-600 shadow-sm shadow-red-500/20 active:scale-[0.98] disabled:bg-red-300 disabled:shadow-none',
};

const sizeCls: Record<Size, string> = {
  sm: 'px-3 py-1.5 text-xs',
  md: 'px-4 py-2 text-sm',
  lg: 'px-6 py-2.5 text-base',
  icon: 'p-2 text-sm',
};

export function Btn({
  children,
  kind = 'primary',
  size = 'md',
  icon,
  full,
  pill = true,
  loading,
  disabled,
  type = 'button',
  className = '',
  ...rest
}: BtnProps) {
  return (
    <button
      type={type}
      disabled={disabled || loading}
      className={[
        'inline-flex items-center justify-center gap-2 font-medium select-none cursor-pointer',
        pill ? 'rounded-full' : 'rounded-xl',
        'transition-all duration-150 ease-out',
        'disabled:cursor-not-allowed',
        full ? 'w-full' : '',
        kindCls[kind],
        sizeCls[size],
        className,
      ].join(' ')}
      {...rest}
    >
      {loading ? <Spinner /> : icon}
      {children}
    </button>
  );
}

function Spinner() {
  return (
    <span
      className="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-r-transparent shrink-0"
      aria-hidden
    />
  );
}
