import { ReactNode } from 'react';

type Tone = 'neutral' | 'primary' | 'success' | 'warn' | 'danger' | 'sand' | 'sparkle';

const cls: Record<Tone, string> = {
  neutral: 'bg-stone-100 text-stone-700 border-stone-200/80',
  primary: 'bg-primary-50 text-primary-700 border-primary-200/80',
  success: 'bg-success-50 text-success-700 border-success-200/80',
  warn:    'bg-warning-50 text-warning-700 border-warning-200/80',
  danger:  'bg-danger-50 text-danger-700 border-danger-200/80',
  sand:    'bg-sand-200 text-stone-700 border-stone-200/80',
  sparkle: 'bg-gradient-to-r from-blue-50 via-purple-50 to-pink-50 text-purple-800 border-purple-200/80',
};

export function Pill({
  children,
  tone = 'neutral',
  className = '',
}: {
  children: ReactNode;
  tone?: Tone;
  className?: string;
}) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 text-xs font-medium rounded-full border ${cls[tone]} ${className}`}
    >
      {children}
    </span>
  );
}
