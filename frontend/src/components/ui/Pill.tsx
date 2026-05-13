import { ReactNode } from 'react';

type Tone = 'neutral' | 'primary' | 'success' | 'warn' | 'danger' | 'sand';

const cls: Record<Tone, string> = {
  neutral: 'bg-stone-100 text-stone-700',
  primary: 'bg-primary-50 text-primary-700',
  success: 'bg-success-50 text-success-700',
  warn:    'bg-warning-50 text-warning-700',
  danger:  'bg-danger-50 text-danger-700',
  sand:    'bg-sand-200 text-stone-700',
};

export function Pill({ children, tone = 'neutral' }: { children: ReactNode; tone?: Tone }) {
  return (
    <span
      className={`inline-flex items-center gap-1 px-2.5 py-0.5 text-[11px] font-medium rounded-full ${cls[tone]}`}
    >
      {children}
    </span>
  );
}
