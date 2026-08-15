import { ReactNode } from 'react';

interface EmptyStateProps {
  icon?: ReactNode;
  title: string;
  description?: string;
  action?: ReactNode;
  className?: string;
}

export function EmptyState({
  icon,
  title,
  description,
  action,
  className = '',
}: EmptyStateProps) {
  return (
    <div className={`flex flex-col items-center justify-center text-center py-16 px-6 ${className}`}>
      {icon && (
        <div className="w-16 h-16 rounded-3xl bg-gradient-to-b from-blue-50 to-indigo-50/40 border border-blue-100/80 flex items-center justify-center text-blue-600 shadow-sm mb-4">
          {icon}
        </div>
      )}
      <div className="text-lg font-semibold text-slate-800 tracking-tight">{title}</div>
      {description && (
        <div className="text-sm text-slate-500 mt-2 max-w-md leading-relaxed">{description}</div>
      )}
      {action && <div className="mt-6">{action}</div>}
    </div>
  );
}
