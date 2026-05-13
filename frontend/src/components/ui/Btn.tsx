import { ButtonHTMLAttributes, ReactNode } from 'react';

type Kind = 'primary' | 'secondary' | 'ghost' | 'outline' | 'danger';
type Size = 'sm' | 'md' | 'lg';

interface BtnProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'type'> {
  kind?: Kind;
  size?: Size;
  icon?: ReactNode;
  full?: boolean;
  loading?: boolean;
  type?: 'button' | 'submit' | 'reset';
}

const kindCls: Record<Kind, string> = {
  primary:
    'bg-accent-500 text-white hover:bg-accent-600 shadow-xs disabled:opacity-50',
  secondary:
    'bg-sand-200 text-stone-800 hover:bg-sand-300 disabled:opacity-50',
  ghost:
    'bg-transparent text-stone-700 hover:bg-stone-100 disabled:opacity-50',
  outline:
    'bg-white text-stone-700 border border-stone-200 hover:bg-stone-50 disabled:opacity-50',
  danger:
    'bg-transparent text-danger-500 hover:bg-danger-50 disabled:opacity-50',
};

const sizeCls: Record<Size, string> = {
  sm: 'px-3 py-1.5 text-xs',
  md: 'px-4 py-2 text-sm',
  lg: 'px-[22px] py-3 text-base',
};

export function Btn({
  children,
  kind = 'primary',
  size = 'md',
  icon,
  full,
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
        'inline-flex items-center justify-center gap-2 rounded-md font-medium',
        'transition-colors duration-fast ease-out',
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
      className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-current border-r-transparent"
      aria-hidden
    />
  );
}
