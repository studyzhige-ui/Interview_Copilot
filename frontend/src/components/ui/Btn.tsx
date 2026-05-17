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

// Disabled keeps the bright hue (just lighter + un-clickable), instead of
// the default fade-to-gray that washes out the saturated palette.
const kindCls: Record<Kind, string> = {
  primary:
    'bg-primary-500 text-white hover:bg-primary-600 shadow-sm disabled:bg-primary-300 disabled:hover:bg-primary-300 disabled:shadow-none',
  secondary:
    'bg-accent-500 text-white hover:bg-accent-600 shadow-sm disabled:bg-accent-300 disabled:hover:bg-accent-300 disabled:shadow-none',
  ghost:
    'bg-stone-100 text-stone-800 hover:bg-stone-200 disabled:opacity-50',
  outline:
    'bg-white text-primary-700 border border-primary-300 hover:bg-primary-50 disabled:text-primary-300 disabled:border-primary-100',
  danger:
    'bg-danger-500 text-white hover:bg-danger-700 shadow-sm disabled:bg-danger-50 disabled:text-danger-500 disabled:shadow-none',
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
